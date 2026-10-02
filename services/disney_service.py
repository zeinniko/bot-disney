import asyncio
import time
from typing import Callable, Awaitable, Optional, Dict
from playwright.async_api import async_playwright
from config.settings import HEADLESS_MODE
from services.imap_service import fetch_disney_otp


async def login_disney(page, context, email: str, password: str, progress_cb: Callable[[str], Awaitable[None]] = None):
    if progress_cb:
        await progress_cb("🌐 Memulai browser…")

    await context.clear_cookies()
    
    if progress_cb:
        await progress_cb("🔑 Membuka halaman login…")
    
    await page.goto("https://www.disneyplus.com/en-gb/identity/login", wait_until="domcontentloaded")
    await page.wait_for_timeout(6000)

    if progress_cb:
        await progress_cb("📧 Mengisi email…")
    
    email_selector = 'input[data-testid="lookupValue"], #lookupValue, input[name="lookupValue"]'
    try:
        await page.wait_for_selector(email_selector, state="attached", timeout=35000)
        
        email_input = page.locator(email_selector).first
        await email_input.click(force=True)
        await email_input.fill(email)
        
    except Exception as e:
        pass

    await page.fill(email_selector, email)
    
    submit_btn = 'button[data-testid="id-flow-submit"], #id-flow'
    await page.click(submit_btn)
    await page.wait_for_timeout(3000)

    # 1. Cek Akun Tidak Terdaftar
    if await page.is_visible('button[data-testid="registration-prompt-submit-btn"]'):
        return {"status": "error", "message": "Akun tidak terdaftar"}

    # 2. Cek Confirm Identity / OTP Requirement
    enter_pass_btn = 'button[data-testid="enter-password-button"]'
    if await page.is_visible('button[data-testid="send-passcode-button"]') or await page.is_visible(enter_pass_btn):
        if await page.is_visible(enter_pass_btn):
            await page.click(enter_pass_btn)
            await page.wait_for_timeout(2000)
        else:
            if progress_cb:
                await progress_cb("📩 Meminta kode OTP…")
            otp = await fetch_disney_otp(email)
            if not otp:
                return {"status": "error", "message": "Gagal menerima OTP IMAP"}
            
            if progress_cb:
                await progress_cb("🔓 Memasukkan OTP login…")

    # 3. Isi Password & Submit
    if progress_cb:
        await progress_cb("🔑 Memasukkan password akun…")
        
    password_selector = 'input[data-testid="password"], input[type="password"], #password'
    await page.wait_for_selector(password_selector, state="visible", timeout=10000)
    await page.fill(password_selector, password)
    await page.click(submit_btn)

    # 4. MENUNGGU "WHO'S WATCHING" & KLIK PROFIL
    if progress_cb:
        await progress_cb("👤 Menunggu layar Who's Watching…")

    profile_card_selector = (
        '[data-testid="profile-avatar"], [data-testid="profile-item"], '
        'div[data-testid^="profile-"], .profile-avatar'
    )

    try:
        # Tunggu avatar profil muncul
        await page.wait_for_selector(profile_card_selector, state="visible", timeout=35000)
        await page.wait_for_timeout(1500)

        if progress_cb:
            await progress_cb("👇 Mengklik profil utama…")
            
        first_profile = page.locator(profile_card_selector).first
        
        # Paksa klik pada element profil
        await first_profile.click(force=True)

        # Cek dan tunggu sampai URL berpindah dari layar login/select-profile ke halaman home Disney
        try:
            await page.wait_for_url("**/home**", timeout=15000)
        except Exception:
            # Jika URL tidak berubah otomatis, tunggu beberapa detik agar token session tersimpan
            await page.wait_for_timeout(4000)

    except Exception:
        # Jika gagal masuk/klik profil, cek apakah password salah
        if await page.is_visible(password_selector) or await page.is_visible('.invalid-feedback'):
            return {"status": "error", "message": "Password salah"}

    return {"status": "success", "message": "Login berhasil"}

async def change_disney_password(email: str, current_password: str, new_password: str, progress_cb: Callable[[str], Awaitable[None]] = None):
    """FUNGSI GANTI PASSWORD DISNEY PLUS"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS_MODE, 
            args=[
                "--disable-blink-features=AutomationControlled", 
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--no-first-run",
                "--no-zygote",
                "--disable-infobars",
                "--window-size=1280,720",
                "--lang=en-US,en",
                # Tambahan baru untuk VPS Headless:
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-extensions",
                "--disable-features=IsolateOrigins,site-per-process"
            ]
        )

        # 2. Buat Browser Context BARU yang terisolasi
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            viewport={'width': 390, 'height': 844},
            device_scale_factor=3,
            is_mobile=True,
            has_touch=True
        )

        # 3. Pastikan Cookies & Storage kosong
        await context.clear_cookies()
        
        page = await context.new_page()

        try:
            # 1. Login
            login_res = await login_disney(page, context, email, current_password, progress_cb)
            if login_res["status"] != "success":
                return login_res

            async def get_element(selector: str, timeout: int = 20000):
                end_time = asyncio.get_event_loop().time() + (timeout / 1000)
                while asyncio.get_event_loop().time() < end_time:
                    try:
                        el = page.locator(selector).first
                        if await el.is_visible():
                            return el, page
                    except Exception:
                        pass
                    for frame in page.frames:
                        try:
                            el = frame.locator(selector).first
                            if await el.is_visible():
                                return el, frame
                        except Exception:
                            pass
                    await asyncio.sleep(0.5)
                raise Exception(f"Timeout {timeout}ms mencari selector: {selector}")

            # PERBAIKAN: Sync React State yang aman dari Frame & Bebas Bug Sintaks JS
            async def fill_otp_code_and_sync(scope, otp_code: str):
                """Mengisi 6 digit OTP dan memaksa React/Bootstrap membaca value-nya"""
                for i in range(6):
                    inp_selector = f'#otp-code-input-otpCode-{i}'
                    inp = scope.locator(inp_selector).first
                    await inp.focus()
                    await inp.fill(otp_code[i])
                    # Tembakkan event JS agar React State membaca perubahan nilai
                    await inp.dispatch_event('input')
                    await inp.dispatch_event('change')
                    await asyncio.sleep(0.05)

                # Jalankan evaluasi JS langsung dari scope (Bisa Page atau Frame)
                eval_script = """
                    (otp) => {
                        const container = document.querySelector('[data-testid="otpCode"]');
                        const hiddenInput = document.querySelector('input[type="hidden"][name="otpCode"]');
                        const form = document.querySelector('#otp-recovery') || document.querySelector('[data-testid="otp-redeem-form"]');
                        
                        if (container) container.setAttribute('value', otp);
                        if (hiddenInput) hiddenInput.value = otp;
                        
                        // Hapus status invalid dari Form
                        if (form) {
                            form.classList.remove('is-invalid');
                        }
                    }
                """
                
                # Eksekusi dengan mengirimkan argument otp_code secara aman
                if hasattr(scope, "evaluate"):
                    await scope.evaluate(eval_script, otp_code)
                else:
                    await page.evaluate(eval_script, otp_code)

                await page.wait_for_timeout(500)

            async def handle_choose_delivery_if_present():
                choose_btn_selector = '#choose-delivery-method, button[id="choose-delivery-method"]'
                try:
                    elem, active_scope = await get_element(choose_btn_selector, timeout=4000)
                    if elem:
                        if progress_cb:
                            await progress_cb("📩 Menekan tombol 'Send' untuk mengirim OTP…")
                        await elem.click(force=True)
                        await page.wait_for_timeout(3000)
                        return True
                except Exception:
                    pass
                return False

            profile_selector = '[data-testid="profile-item"], .profile-avatar, [data-testid="profile-avatar"], button[aria-label*="Profile"]'

            async def ensure_not_on_select_profile():
                """Fungsi Penjaga: Hanya aktif jika belum berada di commerce/account"""
                if ("select-profile" in page.url or "whos-watching" in page.url) and "commerce/account" not in page.url:
                    if progress_cb:
                        await progress_cb("⚠️ Terlempar balik ke Select Profile! Memilih profil ulang…")
                    try:
                        prof_elem, _ = await get_element(profile_selector, timeout=5000)
                        await prof_elem.click(force=True)
                        await page.wait_for_timeout(3000)
                    except Exception:
                        pass

            # =========================================================================
            # 2. SELESAIKAN PROSES SELECT PROFILE AWAL
            # =========================================================================
            if progress_cb:
                await progress_cb("👤 Menunggu & Memilih Profil di layar Who's Watching…")

            try:
                profile_elem, _ = await get_element(profile_selector, timeout=20000)
                await profile_elem.click(force=True)
                await page.wait_for_timeout(3000)
            except Exception:
                pass

            # =========================================================================
            # 3. MENGAKSES COMMERCE/ACCOUNT PERTAMA KALI
            # =========================================================================
            if progress_cb:
                await progress_cb("⚙️ Membuka menu Account & MyDisney…")

            await ensure_not_on_select_profile()

            if "commerce/account" not in page.url:
                await page.goto("https://www.disneyplus.com/en-gb/commerce/account", wait_until="domcontentloaded", timeout=40000)
                await page.wait_for_timeout(4000)

            manage_btn_selector = 'button[data-testid="manage-email-and-password"], [data-testid="manage-email-and-password"], a[data-testid="manage-email-and-password"]'
            
            # Perpanjang timeout menjadi 30 detik untuk memberikan waktu iframe/DOM merender tombol
            try:
                manage_elem, active_scope = await get_element(manage_btn_selector, timeout=30000)
            except Exception:
                # Fallback: Jika tombol tidak ketemu, refresh/buka ulang halaman account
                await page.reload(wait_until="domcontentloaded")
                await page.wait_for_timeout(4000)
                manage_elem, active_scope = await get_element(manage_btn_selector, timeout=20000)

            await manage_elem.click(force=True)
            await page.wait_for_timeout(4000)

            # 4. HANDLING VERIFIKASI IDENTITAS TERLEBIH DAHULU
            change_pass_btn = 'button[data-testid="change-password"], [data-testid="change-password"]'
            enter_pass_btn = 'button[data-testid="enter-password-button"]'
            send_passcode_btn = 'button[data-testid="send-passcode-button"]'
            password_selector = 'input[data-testid="password"], input[type="password"], #password'
            submit_btn = 'button[data-testid="id-flow-submit"], #id-flow, button[type="submit"]'
            redeem_btn = 'button[data-testid="redeem-otp"], button[type="submit"]'

            for _ in range(3):
                if await page.locator(change_pass_btn).is_visible():
                    break

                await handle_choose_delivery_if_present()

                if await page.locator(enter_pass_btn).is_visible() or await page.locator(send_passcode_btn).is_visible():
                    if await page.locator(enter_pass_btn).is_visible():
                        if progress_cb:
                            await progress_cb("🔑 Konfirmasi identitas dengan Password saat ini…")
                        await page.click(enter_pass_btn)
                        await page.wait_for_timeout(2000)
                        
                        pass_field, active_scope = await get_element(password_selector, timeout=10000)
                        await pass_field.fill(current_password)
                        submit_confirm, _ = await get_element(submit_btn, timeout=10000)
                        await submit_confirm.click()
                        await page.wait_for_timeout(4000)

                        await handle_choose_delivery_if_present()

                    else:
                        if progress_cb:
                            await progress_cb("📩 Konfirmasi identitas dengan Email OTP…")
                        await page.click(send_passcode_btn, force=True)
                        await page.wait_for_timeout(2000)

                        otp_confirm = await fetch_disney_otp(email=email, max_wait_seconds=60)
                        if not otp_confirm:
                            return {"status": "error", "message": "Gagal mendapatkan OTP Konfirmasi IMAP"}

                        first_otp_elem, active_scope = await get_element('#otp-code-input-otpCode-0', timeout=15000)
                        await fill_otp_code_and_sync(active_scope, otp_confirm)
                        
                        redeem_elem, _ = await get_element(redeem_btn, timeout=8000)
                        await redeem_elem.click()
                        await page.wait_for_timeout(4000)

            # 5. KLIK TOMBOL CHANGE PASSWORD UNTUK MENGIRIM OTP RESET
            try:
                request_otp_time = time.time()
                change_pass_elem, _ = await get_element(change_pass_btn, timeout=1000)
                if progress_cb:
                    await progress_cb("⚙️ Menekan tombol Change Password…")
                await change_pass_elem.click(force=True)
                await page.wait_for_timeout(3000)
            except Exception:
                pass

            # 6. CEK ULANG TERAPKAN METODE PENGIRIMAN OTP (JIKA MUNCUL)
            await handle_choose_delivery_if_present()

            # =========================================================================
            # 7. MINTA & INPUT OTP RESET PASSWORD
            # =========================================================================
            if progress_cb:
                await progress_cb("📩 Meminta & Mengambil OTP Reset Password…")
            
            otp_reset = await fetch_disney_otp(email=email, max_wait_seconds=60, since_time=request_otp_time)
            if not otp_reset:
                return {"status": "error", "message": "Gagal menerima OTP Reset Password dari IMAP"}

            first_otp_elem, active_scope = await get_element('#otp-code-input-otpCode-0', timeout=20000)
            
            if progress_cb:
                await progress_cb(f"🔑 Mengisi OTP Reset Password ({otp_reset}) & Sync React State…")

            # Isi OTP dengan sinkronisasi presisi
            await fill_otp_code_and_sync(active_scope, otp_reset)

            # =========================================================================
            # PROSES SUBMIT FORM OTP
            # =========================================================================
            if progress_cb:
                await progress_cb("🔘 Mengirimkan Form OTP ke Disney…")

            # PERBAIKAN: Submit Form dari Active Scope (Mendukung iFrame)
            submit_form_script = """
                () => {
                    const form = document.querySelector('#otp-recovery') || document.querySelector('[data-testid="otp-redeem-form"]');
                    if (form) {
                        form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                        if (typeof form.requestSubmit === 'function') {
                            form.requestSubmit();
                        }
                    }
                }
            """
            try:
                if hasattr(active_scope, "evaluate"):
                    await active_scope.evaluate(submit_form_script)
                else:
                    await page.evaluate(submit_form_script)
            except Exception:
                pass

            await page.wait_for_timeout(1000)

            # Metode Cadangan: Klik tombol Continue secara fisik
            try:
                btn = active_scope.locator('button[data-testid="redeem-otp"]').first
                if await btn.is_visible():
                    await btn.click(force=True)
            except Exception:
                pass

            # =========================================================================
            # 8. TUNGGU PINDAH KE FORM PASSWORD BARU
            # =========================================================================
            if progress_cb:
                await progress_cb("⏳ Memproses OTP & menunggu halaman password baru…")

            new_pass_input = 'input[data-testid="newPassword"], #password-new, input[name="newPassword"]'
            new_pass_elem, _ = await get_element(new_pass_input, timeout=30000)

            # =========================================================================
            # 9. MENGISI PASSWORD BARU & SIMPAN
            # =========================================================================
            if progress_cb:
                await progress_cb("🔒 Mengisi password baru...")
            
            await new_pass_elem.click()
            await new_pass_elem.fill(new_password)
            await page.wait_for_timeout(500)

            save_btn_selector = 'button[data-testid="new-password-submit"], #new-password-submit'
            save_btn_elem, _ = await get_element(save_btn_selector, timeout=10000)
            
            await save_btn_elem.click(force=True)

            await page.wait_for_timeout(5000)

            return {"status": "success", "message": "Password berhasil diubah!"}

        except Exception as e:
            return {"status": "failed", "message": str(e)}
        finally:
            await page.close()
            await context.close()
            await browser.close()

async def process_kick_all_in_new_tab(popup_page, email: str, password: str, progress_cb=None) -> bool:
    """Mengolah alur SSO & Kick All di Tab Baru yang terbuka dari link Anchor"""
    try:
        if progress_cb:
            await progress_cb("⚙️ Menunggu tab baru SSO MyDisney dimuat...")

        email_selector = 'input[data-testid="lookupValue"], #lookupValue, input[name="lookupValue"]'
        submit_btn = 'button[data-testid="id-flow-submit"], #id-flow, button[type="submit"]'

        # 1. Tunggu Input Email
        await popup_page.wait_for_selector(email_selector, state="visible", timeout=30000)

        if progress_cb:
            await progress_cb("📧 Memasukkan email di tab baru...")

        await popup_page.click(email_selector)
        await popup_page.fill(email_selector, email)
        await popup_page.wait_for_timeout(500)
        await popup_page.press(email_selector, "Enter")
        await popup_page.wait_for_timeout(3500)

        # 2. Cek Jika Kembali ke Halaman Utama (Banner Log In)
        banner_login_btn = 'button[data-testid="banner__button--login"], #sign_in, button:has-text("Log In")'
        try:
            if await popup_page.is_visible(banner_login_btn, timeout=3000):
                if progress_cb:
                    await progress_cb("🔑 Menekan tombol Log In di Halaman Utama...")
                await popup_page.click(banner_login_btn)
                await popup_page.wait_for_timeout(3500)
        except Exception:
            pass

        # 3. Cek Jika Minta Input Email Lagi
        try:
            if await popup_page.is_visible(email_selector, timeout=4000):
                if progress_cb:
                    await progress_cb("📧 Memasukkan ulang email...")
                await popup_page.click(email_selector)
                await popup_page.fill(email_selector, email)
                await popup_page.wait_for_timeout(500)
                await popup_page.press(email_selector, "Enter")
                await popup_page.wait_for_timeout(3500)
        except Exception:
            pass

        # 4. DETEKSI: PASSWORD ATAU SEND OTP
        send_passcode_btn = 'button[data-testid="send-passcode-button"]'
        enter_pass_btn = 'button[data-testid="enter-password-button"]'
        enter_otp = 'button[data-testid="redeem-otp"]'
        password_selector = 'input[data-testid="password"], #password, input[type="password"]'
        otp_input_0 = '#otp-code-input-otpCode-0'

        if await popup_page.is_visible(enter_pass_btn, timeout=3000):
            await popup_page.click(enter_pass_btn)
            await popup_page.wait_for_timeout(2000)

        # CASE A: SEND OTP / PASSCODE
        if await popup_page.is_visible(send_passcode_btn, timeout=3000):
            if progress_cb:
                await progress_cb("📩 Menekan tombol Kirim Kode OTP...")
            await popup_page.click(send_passcode_btn)
            await popup_page.wait_for_timeout(3000)

        # CASE B: INPUT PASSWORD
        if await popup_page.is_visible(password_selector, timeout=3000):
            if progress_cb:
                await progress_cb("🔑 Memasukkan password di SSO MyDisney...")
            await popup_page.click(password_selector)
            await popup_page.fill(password_selector, password)
            await popup_page.wait_for_timeout(500)
            await popup_page.press(password_selector, "Enter")
            await popup_page.wait_for_timeout(4000)

        # 5. CEK PILIHAN METODE VERIFIKASI (JIKA ADA)
        choose_delivery_btn = '#choose-delivery-method, button[id="choose-delivery-method"]'
        if await popup_page.is_visible(choose_delivery_btn, timeout=3000):
            if progress_cb:
                await progress_cb("📩 Memilih pengiriman OTP via Email...")
            await popup_page.click(choose_delivery_btn)
            await popup_page.wait_for_timeout(3000)

        # 6. INPUT OTP & SUBMIT AMAN
        if await popup_page.is_visible(otp_input_0, timeout=5000):
            if progress_cb:
                await progress_cb("📩 Mengambil OTP verifikasi dari IMAP...")

            request_time = time.time() - 10
            otp_code = await fetch_disney_otp(email=email, max_wait_seconds=60, since_time=request_time)

            if not otp_code or len(otp_code) < 6:
                if progress_cb:
                    await progress_cb("❌ Gagal mendapatkan OTP IMAP!")
                return False

            if progress_cb:
                await progress_cb(f"🔑 Memasukkan OTP ({otp_code})...")

            # Isi OTP angka per angka
            for i in range(6):
                inp = f'#otp-code-input-otpCode-{i}'
                await popup_page.fill(inp, otp_code[i])
                await asyncio.sleep(0.05)

            await popup_page.wait_for_timeout(500)

            # Submit via Enter pada input terakhir agar merilis event submit React secara alami
            await popup_page.press(enter_otp, "Enter")
            await popup_page.wait_for_timeout(5000)

        recovery_continue_btn = '#recovery-continue, [data-testid="recovery-continue"]'
        try:
            if await popup_page.is_visible(recovery_continue_btn, timeout=6000):
                if progress_cb:
                    await progress_cb("🔘 Menekan tombol Lanjut (Anda telah masuk ke akun)...")
                await popup_page.click(recovery_continue_btn, force=True)
                await popup_page.wait_for_timeout(4000)
        except Exception:
            pass

        # =========================================================================
        # 7. NAVIGASI INTERNAL KE MENU KECAMATAN / ACCESS & SECURITY (TANPA GOTO)
        # =========================================================================
        kick_everywhere_btn = '[data-testid="display-card__button--log-out-everywhere"], button:has-text("Keluar dari semua perangkat"), button:has-text("Log out of all devices")'

        # Cek apakah tombol kick_everywhere_btn belum kelihatan di halaman saat ini
        if not await popup_page.is_visible(kick_everywhere_btn):
            if progress_cb:
                await progress_cb("⚙️ Berpindah ke menu Keamanan Akun...")

            # Mencari tombol navigasi ke Access & Security secara internal di menu MyDisney
            security_nav_selector = '#access_security_nav, a[href*="access-security"], a:has-text("Keamanan"), a:has-text("Security")'
            
            try:
                await popup_page.wait_for_selector(security_nav_selector, state="visible", timeout=10000)
                await popup_page.click(security_nav_selector, force=True)
                await popup_page.wait_for_timeout(3000)
            except Exception:
                pass

        # =========================================================================
        # 8. KLIK TOMBOL LOG OUT EVERYWHERE DI TAB BARU
        # =========================================================================
        if progress_cb:
            await progress_cb("🔴 Menekan tombol Keluar dari semua perangkat...")

        # Gunakan locator langsung tanpa wait kaku
        kick_btn = popup_page.locator(kick_everywhere_btn).first
        await kick_btn.click(force=True)
        await popup_page.wait_for_timeout(1000)

        # =========================================================================
        # 9. EKSEKUSI KLIK SEND SEGERA (VERIFIKASI KEDUA)
        # =========================================================================
        if progress_cb:
            await progress_cb("📩 Menekan tombol Kirim / Send secara langsung...")

        # Loop pencarian tombol di halaman utama MAUPUN di seluruh iframe
        sent_success = False
        for attempt in range(10):  # Coba periksa setiap 500ms selama 5 detik
            frames_to_check = [popup_page] + popup_page.frames

            for frame in frames_to_check:
                try:
                    # Jalankan JS Native untuk memilih radio Email & Klik tombol Kirim
                    clicked = await frame.evaluate("""() => {
                        // 1. Centang radio email jika ada
                        const radio = document.querySelector('#deliveryMethod-0');
                        if (radio) radio.checked = true;

                        // 2. Cari tombol Kirim
                        const btn = document.querySelector('#choose-delivery-method') 
                                 || document.querySelector('button[form="chooseDeliveryMethod"]')
                                 || document.querySelector('button[type="submit"]');

                        if (btn) {
                            btn.click();
                            return true;
                        }
                        return false;
                    }""")

                    if clicked:
                        sent_success = True
                        break
                except Exception:
                    pass

            if sent_success:
                break
            await asyncio.sleep(0.5)

        if not sent_success and progress_cb:
            await progress_cb("⚠️ Tombol Kirim tidak ditemukan via JS, mencoba tekan Enter...")
            await popup_page.keyboard.press("Enter")

        await popup_page.wait_for_timeout(3000)

        # =========================================================================
        # 9.2. AMBIL & INPUT OTP KEDUA
        # =========================================================================
        if progress_cb:
            await progress_cb("📩 Menunggu kolom OTP kedua...")

        otp_input_0 = '#otp-code-input-otpCode-0'
        enter_otp = 'button[data-testid="redeem-otp"], button[type="submit"]'

        # Tunggu input OTP di halaman utama atau frame
        otp_found = False
        for _ in range(30): # Timeout manual 15 detik
            for frame in [popup_page] + popup_page.frames:
                try:
                    if await frame.is_visible(otp_input_0):
                        otp_found = True
                        target_frame = frame
                        break
                except Exception:
                    pass
            if otp_found:
                break
            await asyncio.sleep(0.5)

        if not otp_found:
            if progress_cb:
                await progress_cb("❌ Kolom OTP kedua tidak kunjung muncul.")
            return False

        if progress_cb:
            await progress_cb("📩 Mengambil OTP verifikasi Kick All dari IMAP...")

        request_time_2 = time.time() - 10
        otp_code_2 = await fetch_disney_otp(email=email, max_wait_seconds=60, since_time=request_time_2)

        if not otp_code_2 or len(otp_code_2) < 6:
            if progress_cb:
                await progress_cb("❌ Gagal mendapatkan OTP verifikasi Kick All!")
            return False

        if progress_cb:
            await progress_cb(f"🔑 Memasukkan OTP Kick All ({otp_code_2})...")

        for i in range(6):
            inp_selector = f'#otp-code-input-otpCode-{i}'
            await target_frame.fill(inp_selector, otp_code_2[i])
            await asyncio.sleep(0.05)

        await popup_page.wait_for_timeout(500)
        enter_otp_selector = 'button[data-testid="redeem-otp"]'

        await target_frame.wait_for_selector(enter_otp_selector, state="visible", timeout=10000)
        
        if progress_cb:
            await progress_cb("🔘 Menekan tombol Lanjut / Submit OTP...")

        # Cukup panggil klik satu kali pada tombol submit OTP
        otp_submit_btn = target_frame.locator(enter_otp_selector).first
        await otp_submit_btn.click(force=True)

        await popup_page.wait_for_timeout(5000)
        if progress_cb:
            await progress_cb("⚙️ Menunggu tombol konfirmasi 'Keluar' akhir...")

        # Tambahkan data-testid tombol "Keluar" yang baru ke dalam selector
        final_logout_selector = (
            'button[data-testid="log-out-everywhere__button--submit-log-out-everywhere"], '
            'button[data-testid="modal-primary-button"], '
            'button[data-testid="sign-out"], '
            'button:has-text("Keluar"), '
            'button:has-text("Log Out"), '
            'button:has-text("Sign Out")'
        )

        try:
            # Tunggu tombol konfirmasi Keluar/Log Out muncul setelah OTP sukses
            await target_frame.wait_for_selector(final_logout_selector, state="visible", timeout=15000)

            if progress_cb:
                await progress_cb("🔴 Menekan tombol Keluar / Log Out akhir...")

            final_btn = target_frame.locator(final_logout_selector).first
            await final_btn.click(force=True)
            await popup_page.wait_for_timeout(3000)

        except Exception as e:
            if progress_cb:
                await progress_cb(f"⚠️ Peringatan pada tombol keluar akhir: {str(e)}")

    except Exception as e:
        if progress_cb:
            await progress_cb(f"❌ Error di Tab Baru SSO: {str(e)}")
        return False


