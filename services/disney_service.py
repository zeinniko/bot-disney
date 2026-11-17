import asyncio
import re
import time
from typing import Callable, Awaitable, Optional, Dict
from playwright.async_api import async_playwright
from config.settings import HEADLESS_MODE
from services.imap_service import fetch_disney_otp
from database.db import log_activity, upsert_user, update_account_password

change_pass_btn = 'button[data-testid="change-password"], [data-testid="change-password"]'
enter_pass_btn = 'button[data-testid="enter-password-button"]'
send_passcode_btn = 'button[data-testid="send-passcode-button"]'
password_selector = 'input[data-testid="password"], input[type="password"], #password'
submit_btn = 'button[data-testid="id-flow-submit"], #id-flow, button[type="submit"]'
redeem_btn = 'button[data-testid="redeem-otp"], button[type="submit"]'

async def get_element(page, selector: str, timeout: int = 20000):
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
async def fill_otp_code_and_sync(page,scope, otp_code: str):
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


async def login_disney(page, context, email: str, password: str, progress_cb: Callable[[str], Awaitable[None]] = None, is_chpass = False, telegram_user: Optional[Dict] = None):  
    if progress_cb:
        await progress_cb("🚀 Memulai browser...")
    await page.goto("https://www.disneyplus.com/en-gb/identity/login", wait_until="domcontentloaded")
    await page.wait_for_timeout(6000)
    
    if progress_cb:
        await progress_cb("🔵 Login ke Disney+...")

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
    if await page.is_visible(send_passcode_btn) or await page.is_visible(enter_pass_btn):
        await page.wait_for_timeout(1000)
        if is_chpass:
            if progress_cb:
                await progress_cb("📩 Menekan tombol Send Passcode…")

            # 1. Klik tombol Send
            try:
                send_btn_elem, _ = await get_element(page, send_passcode_btn, timeout=10000)
                await send_btn_elem.click(force=True)
            except Exception:
                await page.click('button[data-testid="send-passcode-button"]', force=True)

            await page.wait_for_timeout(3000)

            if progress_cb:
                await progress_cb("📩 Mengambil kode OTP terbaru dari IMAP…")

            # 2. Ambil OTP dari IMAP
            request_time = time.time() - 10
            otp_confirm = await fetch_disney_otp(email=email, max_wait_seconds=60, since_time=request_time)
            if not otp_confirm:
                return {"status": "error", "message": "Gagal mendapatkan OTP Konfirmasi IMAP"}

            # 3. Tunggu input pertama OTP benar-benar siap & visible
            first_input_selector = '#otp-code-input-otpCode-0'
            await page.wait_for_selector(first_input_selector, state="visible", timeout=15000)
            
            first_input = page.locator(first_input_selector).first
            await first_input.click(force=True)
            await page.wait_for_timeout(300)

            # 4. Ketik OTP angka demi angka menggunakan keyboardPlaywright murni (Trigger React State & Next.js secara alami)
            for digit in str(otp_confirm):
                await page.keyboard.press(digit)
                await page.wait_for_timeout(150)

            # 1. Pastikan reCAPTCHA Enterprise v3 sudah selesai memproses atau jalankan eksekusi token secara eksplisit
            await page.evaluate("""
                async () => {
                    if (typeof grecaptcha !== 'undefined' && grecaptcha.enterprise) {
                        return new Promise((resolve) => {
                            grecaptcha.enterprise.ready(async () => {
                                try {
                                    // Palang atau ambil token reCAPTCHA untuk action redeem/submit
                                    const token = await grecaptcha.enterprise.execute('6Lcx8hUtAAAAAA3X3cEnP2NXw35jJutlVQ_Fb1Ln', {action: 'submit'});
                                    // Masukkan token ke dalam form jika dibutuhkan, atau biarkan sistem menangkapnya
                                    resolve(token);
                                } catch (e) {
                                    resolve(null);
                                }
                            });
                        });
                    }
                }
            """)

            # 2. Berikan jeda sejenak setelah reCAPTCHA siap
            await page.wait_for_timeout(1000)

            # 3. Klik tombol Continue / Redeem OTP menggunakan evaluasi DOM JavaScript
            await page.evaluate("""
                const btn = document.querySelector('button[data-testid="redeem-otp"]');
                if (btn) {
                    btn.removeAttribute('disabled');
                    btn.focus();
                    btn.click();
                }
            """)

            await page.wait_for_timeout(10000)

        elif await page.is_visible(enter_pass_btn):
            await page.click(enter_pass_btn)
            await page.wait_for_timeout(2000)
            # 3. Isi Password & Submit
            if progress_cb:
                await progress_cb("🔑 Memasukkan password akun…")
                
            password_selector = 'input[data-testid="password"], input[type="password"], #password'
            await page.wait_for_selector(password_selector, state="visible", timeout=10000)
            await page.fill(password_selector, password)
            await page.click(submit_btn)
        else:
            return {"status": "error", "message": "User not verified"}

    # 4. TUNGGU REDIRECT SELESAI HINGGA LAYAR PROFIL BENAR-BENAR MUNCUL & KLIK PROFIL
    if progress_cb:
        await progress_cb("👤 Menunggu redirect ke halaman pemilihan profil…")

    select_wrapper = page.locator('[data-testid="select-profile-wrapper"]')
    profile_button_locator = page.locator('div[data-testid^="profile-avatar-"][role="button"]')

    # Pola teks tombol untuk melewati layar Passkey (tanpa dibatasi tag <main>)
    passkey_skip_pattern = re.compile(
        r"(not\s*now|skip|maybe\s*later|set\s*up\s*later|no\s*thanks|cancel|without\s*passkey|lain\s*kali|lewati)",
        re.IGNORECASE,
    )

    try:
        # Tunggu hingga 90 detik agar seluruh rangkaian redirect SSO & Passkey selesai
        deadline = asyncio.get_running_loop().time() + 90
        profile_screen_visible = False
        passkey_clicked = False

        while asyncio.get_running_loop().time() < deadline:
            # Syarat mutlak: layar "Who's watching?" dan card profil harus benar-benar tampil
            if await select_wrapper.is_visible() and await profile_button_locator.count() > 0:
                if await profile_button_locator.first.is_visible():
                    profile_screen_visible = True
                    break

            # Jika tertahan di halaman penawaran Passkey, cari & klik tombol lewati di page maupun iframe
            if "/passkey" in page.url:
                for frame in page.frames:
                    try:
                        skip_btn = frame.locator('button, a, [role="button"]').filter(
                            has_text=passkey_skip_pattern
                        ).first

                        if not await skip_btn.is_visible():
                            skip_btn = frame.locator(
                                '[data-testid*="skip" i], [data-testid*="not-now" i], '
                                '[data-testid*="later" i], [data-testid*="cancel" i], '
                                'button[kind="secondary"]'
                            ).first

                        if await skip_btn.is_visible():
                            if not passkey_clicked and progress_cb:
                                await progress_cb("⏭️ Melewati layar Passkey, menunggu halaman profil…")
                            await skip_btn.click(timeout=3000)
                            passkey_clicked = True
                            await page.wait_for_timeout(1500)
                            break
                    except Exception:
                        continue

            await page.wait_for_timeout(500)

        # Jangan lanjut jika halaman profil belum benar-benar muncul
        if not profile_screen_visible:
            visible_buttons = []
            try:
                btns = await page.locator('button, a, [role="button"]').all_inner_texts()
                visible_buttons = [b.strip() for b in btns if b.strip()]
            except Exception:
                pass
            detail_btn = f" | Tombol terlihat: {visible_buttons}" if visible_buttons else ""
            raise TimeoutError(f"Halaman pemilihan profil belum muncul hingga batas waktu habis{detail_btn}")

        # Tunggu animasi fade-appear & event binding React pada card profil selesai
        first_profile = profile_button_locator.first
        await first_profile.wait_for(state="visible", timeout=15000)
        await page.wait_for_timeout(1000)

        if progress_cb:
            await progress_cb("👇 Halaman profil muncul, mengklik profil utama…")

        try:
            await first_profile.click(timeout=5000)
        except Exception:
            await first_profile.focus()
            await page.keyboard.press("Enter")

        # Pastikan klik profil berhasil memindahkan halaman keluar dari layar pemilihan profil
        await select_wrapper.wait_for(state="hidden", timeout=20000)

        if telegram_user and "id" in telegram_user:
            await upsert_user(
                telegram_id=telegram_user["id"],
                username=telegram_user.get("username"),
                full_name=telegram_user.get("full_name"),
                role="customer",
            )
        return {"status": "success", "message": "Login berhasil"}

    except Exception as e:
        try:
            if await page.locator('input[type="password"]').is_visible() or await page.locator('.invalid-feedback').is_visible():
                return {"status": "error", "message": "Password salah"}
        except Exception:
            pass

        return {"status": "error", "message": f"Gagal melewati layar profil (URL: {page.url}): {str(e)}"}

async def login_mydisney(page, target_email: str, progress_cb: Callable[[str], Awaitable[None]] = None, is_chpass = False, telegram_user: Optional[Dict] = None):
    # 1. Membuka halaman utama MyDisney
    
    await progress_cb("🚀 Memulai browser...")
    await page.goto("https://my.disney.com/", wait_until="domcontentloaded", timeout=30000)

    # 2. Klik tombol 'Masuk'
    btn_login = page.locator("#sign_in")
    await btn_login.wait_for(state="attached", timeout=20000)
    await btn_login.click()

    # 3. Tunggu transisi ke login.disney.com
    
    await progress_cb("🔵 Login ke MyDisney...")
    await page.wait_for_url(lambda url: "login.disney.com" in url, timeout=20000)

    # 4. Tunggu Input Email muncul
    email_selector = '#lookupValue, input[data-testid="lookupValue"], input[name="lookupValue"]'
    email_input = page.locator(email_selector).first

    await email_input.wait_for(state="visible", timeout=30000)

    await email_input.click()
    await progress_cb("📧 Mengisi email…")
    await email_input.fill(target_email)
    await page.wait_for_timeout(500)
    await email_input.press("Enter")
    
    

    # --- HANDLER ALUR VERIFIKASI & MODAL KONFIRMASI ---
    btn_recovery = page.locator("#account-recovery")
    btn_send_code = page.locator('button[data-testid="send-passcode-button"]')
    first_input_selector = "#otp-code-input-otpCode-0"

    # Skenario A: Jika terdeteksi halaman Password -> Klik "Kesulitan masuk?"
    try:
        await page.wait_for_selector(
            '#account-recovery, button[data-testid="send-passcode-button"], #otp-code-input-otpCode-0',
            timeout=15000,
        )
    except Exception:
        pass

    if await btn_recovery.is_visible():
        await btn_recovery.click()
        await page.wait_for_timeout(2000)

    # Skenario B: Klik Tombol 'Kirim Email' jika modal konfirmasi / pilihan cara verifikasi muncul
    otp_request_timestamp = time.time()

    if await btn_send_code.is_visible():
        otp_request_timestamp = time.time()
        await btn_send_code.click()

        await page.wait_for_selector(first_input_selector, state="visible", timeout=20000)
    else:

        btn_choose_delivery = page.locator("#choose-delivery-method")
        await btn_choose_delivery.wait_for(state="visible", timeout=15000)

        # Catat timestamp Unix (dalam detik, presisi float)
        otp_request_timestamp = time.time()
        await btn_choose_delivery.click()

        await page.wait_for_selector(first_input_selector, state="visible", timeout=20000)

        await page.wait_for_timeout(4000)

    # 5. Ambil OTP via IMAP Service Python
    await progress_cb("📩 Mengambil kode OTP terbaru dari IMAP…")
    otp_code = await fetch_disney_otp(
        email=target_email, 
        max_wait_seconds=45, 
        interval=3, 
        since_time=otp_request_timestamp
    )

    if not otp_code:
        raise Exception("Gagal mendapatkan kode OTP dari email via IMAP!")


    # 6. INPUT OTP DENGAN CARA FILL PER-BOX
    otp_digits = list(otp_code)

    for i in range(6):
        box_locator = page.locator(f"#otp-code-input-otpCode-{i}")
        await box_locator.wait_for(state="visible", timeout=5000)
        await box_locator.focus()
        await box_locator.fill(otp_digits[i])
        # Trigger event input & change bawaan DOM React via JavaScript
        await box_locator.dispatch_event("input")
        await box_locator.dispatch_event("change")
        await page.wait_for_timeout(100)

    await page.wait_for_timeout(1000)

    # 7. EKSEKUSI RECAPTCHA & SUBMIT OTP MENGGUNAKAN REDEEM BUTTON  
    await page.evaluate("""
        async () => {
            if (typeof grecaptcha !== 'undefined' && grecaptcha.enterprise) {
                return new Promise((resolve) => {
                    grecaptcha.enterprise.ready(async () => {
                        try {
                            const token = await grecaptcha.enterprise.execute('6Lcx8hUtAAAAAA3X3cEnP2NXw35jJutlVQ_Fb1Ln', {action: 'submit'});
                            resolve(token);
                        } catch (e) {
                            resolve(null);
                        }
                    });
                });
            }
        }
    """)
    await page.wait_for_timeout(1000)

    # Klik tombol redeem/continue OTP spesifik milik MyDisney
    submit_success = await page.evaluate("""
        () => {
            // Cari tombol dengan data-testid redeem-otp atau continue
            const btn = document.querySelector('button[data-testid="redeem-otp"]') || 
                        document.querySelector('button[data-testid="continue-button"]') ||
                        document.querySelector('button[type="submit"]');
            if (btn) {
                btn.removeAttribute('disabled');
                btn.click();
                return true;
            }
            return false;
        }
    """)

    if not submit_success:
        await page.keyboard.press("Enter")


    if telegram_user and "id" in telegram_user:
        await upsert_user(
            telegram_id=telegram_user["id"],
            username=telegram_user.get("username"),
            full_name=telegram_user.get("full_name"),
            role="customer"
        )
    return {"status": "success", "message": "Login berhasil"}

async def change_password_mydisney(
    email: str,
    new_password: str,
    progress_cb: Callable[[str], Awaitable[None]] = None,
    telegram_user: Optional[Dict] = None,
    keep_open: bool = False
):
    tg_id = telegram_user.get("id") if telegram_user else None

    async def progress(message: str):
        if progress_cb:
            await progress_cb(message)

    browser = None
    context = None
    page = None
    try:
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=False,
            channel="chrome",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--window-size=1366,768",
            ]
        )
        context = await browser.new_context(
            locale="id-ID",
            timezone_id="Asia/Jakarta",
            viewport={"width": 1366, "height": 768}
        )
        page = await context.new_page()
        login_res = await login_mydisney(
            page,
            email,
            progress,
            is_chpass=True,
            telegram_user=telegram_user
        )
        if login_res.get("status") != "success":
            return login_res
        
        await progress("🔐 Login berhasil...")
        # 1. Definisikan Selector untuk kedua skenario
        # Skenario A: Halaman Konfirmasi Login / Recovery Complete
        recovery_reset_btn = page.locator('#recovery-reset, button[data-testid="recovery-reset"]')
        # Skenario B: Card "Access & Security" di halaman Home / Dashboard
        dashboard_change_pass_link = page.locator('a[href*="/edit/password"], a:has-text("Ubah kata sandi Anda"), a:has-text("Change your password")')
        # 2. Tunggu salah satu dari kedua elemen ini muncul di DOM (Timeout 15 Detik)
        try:
            await page.wait_for_selector(
                '#recovery-reset, button[data-testid="recovery-reset"], a[href*="/edit/password"]',
                state="visible",
                timeout=20000
            )
        except Exception:
            pass
        # --- EKSEKUSI PENANGANAN SKENARIO DENGAN RETRY & VERIFIKASI ---
        # Helper function untuk mengeklik dan memastikan halaman merespons
        async def trigger_change_password():
            # 1. Coba klik tombol konfirmasi SSO (#recovery-reset) jika ada
            if await recovery_reset_btn.is_visible():
                await progress("⚡ Menekan 'Ubah Kata Sandi' (Halaman Konfirmasi SSO)...")
                try:
                    await recovery_reset_btn.click(force=True)
                except Exception:
                    await page.evaluate("""() => {
                        const btn = document.querySelector('#recovery-reset') || document.querySelector('button[data-testid="recovery-reset"]');
                        if (btn) btn.click();
                    }""")
                return True
            # 2. Coba klik link di Dashboard jika ada
            dash_link = page.locator('a[href*="/edit/password"], a:has-text("Change your password"), a:has-text("Ubah kata sandi")').first
            if await dash_link.is_visible():
                await progress("📌 Menekan link 'Change your password' di Dashboard...")
                try:
                    # Scroll ke elemen & pastikan dapat diklik
                    await dash_link.scroll_into_view_if_needed()
                    await page.wait_for_timeout(500)
                    await dash_link.click(force=True)
                except Exception:
                    await page.evaluate("""() => {
                        const link = document.querySelector('a[href*="/edit/password"]') || 
                                     Array.from(document.querySelectorAll('a')).find(el => 
                                        el.textContent.includes('Change your password') || 
                                        el.textContent.includes('Ubah kata sandi')
                                     );
                        if (link) link.click();
                    }""")
                return True
            return False
        # Jalankan percobaan klik dengan perulangan (Retry sampai 3 kali)
        found_form_frame = None
        for attempt in range(1, 4):
            await trigger_change_password()
            
            # Tunggu sebentar agar popup/iframe punya waktu untuk render
            await page.wait_for_timeout(2000) 
            
            # Cek di Main Page DAN Semua iFrames
            frames_to_check = [page] + page.frames
            for frame in frames_to_check:
                try:
                    # Kita gunakan JS locator untuk deteksi cepat di setiap frame
                    is_visible = await frame.evaluate("""() => {
                        const form1 = document.querySelector('#choose-delivery-method');
                        const form2 = document.querySelector('#otp-code-input-otpCode-0');
                        const form3 = document.querySelector('#recovery-reset');
                        return !!(form1 || form2 || form3);
                    }""")
                    
                    if is_visible:
                        found_form_frame = frame
                        break # Keluar dari loop frame
                except Exception:
                    pass
            
            if found_form_frame:
                await progress("🔍 Form verifikasi ditemukan di dalam halaman/popup.")
                break # Keluar dari loop percobaan klik
                
            await progress(f"⏳ Menunggu transisi ke form ubah password (percobaan {attempt}/3)...")
            await page.wait_for_timeout(1500)

        if not found_form_frame:
            raise Exception("Form verifikasi ubah password gagal dimuat (tidak ditemukan di popup manapun).")
        
        # Beri jeda stabilisasi akhir
        await page.wait_for_timeout(2000)
        choose_delivery_selector = "#choose-delivery-method"
        otp_request_timestamp = time.time()
        
        try:
            # Menggunakan found_form_frame karena form mungkin berada di dalam iframe
            await found_form_frame.wait_for_selector(
                choose_delivery_selector,
                state="visible",
                timeout=10000
            )
            # Jika masuk ke sini, artinya halaman "Pilih cara verifikasi" muncul
            await progress("📧 Halaman pilihan metode verifikasi ditemukan.")
            
            # 1. Pastikan opsi Email terpilih
            # ID radio button untuk email dari HTML adalah #deliveryMethod-0
            email_radio = found_form_frame.locator("#deliveryMethod-0")
            if await email_radio.is_visible():
                 await email_radio.check(force=True)
                 await page.wait_for_timeout(500)
            
            # 2. Klik tombol Kirim
            choose_delivery_btn = found_form_frame.locator(choose_delivery_selector)
            await progress("📧 Mengirim kode verifikasi OTP...")
            await choose_delivery_btn.click(force=True)
            await page.wait_for_timeout(2000)
            
        except Exception:
            # Jika #choose-delivery-method tidak muncul dalam 10 detik, 
            # mungkin langsung dialihkan ke halaman input OTP
            otp_first = found_form_frame.locator("#otp-code-input-otpCode-0")
            if not await otp_first.is_visible(timeout=5000):
                raise Exception("Gagal menemukan tombol Kirim metode OTP maupun form input OTP.")
            else:
                await progress("📧 Langsung masuk ke form input kode OTP.")
     
        first_otp_selector = "#otp-code-input-otpCode-0"
        
        # 1. Gunakan found_form_frame, bukan page
        await found_form_frame.wait_for_selector(
            first_otp_selector,
            state="visible",
            timeout=20000
        )
        
        otp_code = await fetch_disney_otp(
            email=email,
            max_wait_seconds=45,
            interval=3,
            since_time=otp_request_timestamp
        )
        if not otp_code:
            raise Exception("Gagal mendapatkan kode OTP dari email via IMAP.")
        
        otp_code = str(otp_code).strip()
        if not otp_code.isdigit():
            raise Exception(f"OTP tidak valid: {otp_code}")
        if len(otp_code) != 6:
            raise Exception(f"OTP harus 6 digit, tetapi menerima: {otp_code}")
            
        otp_digits = list(otp_code)
        for i in range(6):
            # 2. Gunakan found_form_frame untuk mencari kotak input OTP
            box_locator = found_form_frame.locator(f"#otp-code-input-otpCode-{i}")
            await box_locator.wait_for(state="visible", timeout=5000)
            await box_locator.focus()
            await box_locator.fill(otp_digits[i])
            await box_locator.dispatch_event("input")
            await box_locator.dispatch_event("change")
            await page.wait_for_timeout(100)
            
        await page.wait_for_timeout(1000)
        await progress("🔓 Memverifikasi kode OTP...")
        
        # 3. Gunakan found_form_frame untuk mencari dan klik tombol submit
        submit_success = await found_form_frame.evaluate("""
            () => {
                const btn =
                    document.querySelector('button[data-testid="redeem-otp"]') ||
                    document.querySelector('button[data-testid="continue-button"]') ||
                    document.querySelector('button[type="submit"]');
                if (btn) {
                    btn.removeAttribute("disabled");
                    btn.click();
                    return true;
                }
                return false;
            }
        """)
        
        if not submit_success:
            await page.keyboard.press("Enter")
        await page.wait_for_timeout(3000)
        btn_continue = page.locator(
            '#recovery-continue, button[data-testid="continue-button"]'
        )
        try:
            await btn_continue.wait_for(
                state="visible",
                timeout=10000
            )
            await progress("➡️ Melanjutkan ke pengaturan kata sandi...")
            await btn_continue.click(force=True)
            await page.wait_for_timeout(3000)
        except Exception:
            pass
        
        new_password_selectors = [
            "#password",
            'input[name="password"]',
            'input[type="password"]',
            'input[data-testid="newPassword"]',
            "#password-new",
            'input[name="newPassword"]'
        ]
        new_pass_input = None
        for selector in new_password_selectors:
            locator = page.locator(selector).first
            try:
                await locator.wait_for(
                    state="visible",
                    timeout=5000
                )
                new_pass_input = locator
                break
            except Exception:
                continue
        if new_pass_input is None:
            try:
                html = await page.content()
                with open(
                    "mydisney_password_debug.html",
                    "w",
                    encoding="utf-8"
                ) as f:
                    f.write(html)
            except Exception:
                pass
            raise Exception("Field password baru tidak ditemukan.")
        await progress(f"🔐 Mengisi kata sandi baru: {new_password}")
        await new_pass_input.click()
        await new_pass_input.fill(new_password)
        await new_pass_input.dispatch_event("input")
        await new_pass_input.dispatch_event("change")
        await page.wait_for_timeout(500)
        
        confirm_pass_selectors = [
            'input[data-testid="confirmPassword"]',
            'input[name="confirmPassword"]',
            "#password-confirm",
            'input[name="newPasswordConfirm"]',
            'input[name="passwordConfirmation"]'
        ]
        for selector in confirm_pass_selectors:
            conf_input = page.locator(selector).first
            try:
                if await conf_input.is_visible():
                    await progress("🔐 Mengisi konfirmasi kata sandi...")
                    await conf_input.click()
                    await conf_input.fill(new_password)
                    await conf_input.dispatch_event("input")
                    await conf_input.dispatch_event("change")
                    await page.wait_for_timeout(300)
                    break
            except Exception:
                continue
        await progress("💾 Menyimpan kata sandi baru...")
        
        # Gabungkan semua kemungkinan selector tombol simpan dari kedua skema
        save_btn_selector = 'button[data-testid="edit-password__button--save"], button[data-testid="new-password-submit"], #new-password-submit'
        
        try:
            # Cari tombol menggunakan found_form_frame
            save_btn = found_form_frame.locator(save_btn_selector).first
            await save_btn.wait_for(state="visible", timeout=10000)
            
            # Evaluasi JS untuk memastikan tombol aktif dan langsung klik
            click_success = await found_form_frame.evaluate("""
                (selector) => {
                    const btn = document.querySelector(selector);
                    if (btn) {
                        btn.removeAttribute("disabled");
                        btn.click();
                        return true;
                    }
                    return false;
                }
            """, save_btn_selector)
            
            if not click_success:
                await save_btn.click(force=True)
                
        except Exception as e:
            # Fallback terakhir tekan Enter jika tombol tidak terdeteksi
            await page.keyboard.press("Enter")
            
        await page.wait_for_timeout(4000)
        try:
            await page.wait_for_load_state(
                "networkidle",
                timeout=10000
            )
        except Exception:
            pass
        post_error_selectors = [
            '[role="alert"]',
            ".error",
            ".form-error",
            ".invalid-feedback",
            '[data-testid*="error"]'
        ]
        post_error = None
        for selector in post_error_selectors:
            errors = page.locator(selector)
            try:
                count = await errors.count()
                for i in range(count):
                    item = errors.nth(i)
                    if await item.is_visible():
                        msg = (await item.inner_text()).strip()
                        if msg:
                            post_error = msg
                            break
                if post_error:
                    break
            except Exception:
                continue
        if post_error:
            raise Exception(
                f"MyDisney menolak perubahan password: {post_error}"
            )
        try:
            still_password_form = (
                await page.locator("#new-password-submit").is_visible()
                and await page.locator("#password").is_visible()
            )
        except Exception:
            still_password_form = False
        if still_password_form:
            raise Exception(
                "Form password masih terbuka setelah klik Simpan & Lanjutkan."
            )
        await progress("✅ Password MyDisney berhasil diubah.")
        await update_account_password(
            email,
            new_password
        )
        if tg_id:
            await log_activity(
                tg_id,
                "CHANGE_PASSWORD_MYDISNEY",
                email,
                "SUCCESS",
                "Password berhasil diubah via MyDisney."
            )
        res = {
            "status": "success",
            "message": "Kata sandi MyDisney berhasil diubah!"
        }
        if keep_open:
            res.update({
                "page": page,
                "browser": browser,
                "playwright": pw
            })
        return res
    except Exception as e:
        error_message = str(e)
        await progress(f"❌ Gagal mengubah password: {error_message}")
        if tg_id:
            await log_activity(
                tg_id,
                "CHANGE_PASSWORD_MYDISNEY",
                email,
                "FAILED",
                error_message
            )
        return {
            "status": "error",
            "message": f"Gagal mengubah password MyDisney: {error_message}"
        }
    finally:
        if not keep_open:
            try:
                if page: await page.close()
            except Exception:
                pass
            try:
                if context: await context.close()
            except Exception:
                pass
            try:
                if browser: await browser.close()
            except Exception:
                pass
            try:
                if pw: await pw.stop()
            except Exception:
                pass
            
async def change_password_and_kick_all_mydisney(
    email: str, 
    new_password: str, 
    progress_cb=None, 
    telegram_user: Optional[Dict] = None
) -> dict:
    tg_id = telegram_user.get("id") if telegram_user else None

    # 1. Jalankan ganti password dengan keep_open=True
    chpass_res = await change_password_mydisney(
        email=email,
        new_password=new_password,
        progress_cb=progress_cb,
        telegram_user=telegram_user,
        keep_open=True  # <--- PASSING PARAMETER
    )
    
    if chpass_res.get("status") != "success":
        return chpass_res

    page = chpass_res.get("page")
    browser = chpass_res.get("browser")
    playwright = chpass_res.get("playwright")

    try:
        # 2. Panggil process_kick_all_in_mydisney dengan argumen 'email'
        kick_success = await process_kick_all_in_mydisney(
            popup_page=page, 
            email=email,  # <--- PASTIKAN PARAMETER EMAIL DITERUSKAN
            progress_cb=progress_cb,
            telegram_user=telegram_user
        )
        
        if kick_success:
            return {"status": "success", "message": "Password berhasil diubah dan semua perangkat berhasil di-logout."}
        else:
            return {"status": "failed", "message": "Password berhasil diubah, namun gagal mengeluarkan seluruh perangkat (Kick All)."}

    except Exception as e:
        if tg_id:
            await log_activity(tg_id, "CHANGE_PASS_AND_KICK_ALL", email, "FAILED", str(e))
        return {"status": "failed", "message": f"Password berhasil diubah, tetapi Kick All gagal: {str(e)}"}

    finally:
        # Tutup browser & playwright resource setelah seluruh rangkaian alur selesai
        try:
            if browser:
                await browser.close()
            if playwright:
                await playwright.stop()
        except Exception:
            pass

async def process_kick_all_in_mydisney(popup_page, email: str, progress_cb=None, telegram_user: Optional[Dict] = None) -> bool:
    """Mengolah alur Kick All / Logout Everywhere di MyDisney"""
    tg_id = telegram_user.get("id") if telegram_user else None
    
    async def progress(msg: str):
        if progress_cb:
            await progress_cb(msg)

    try:
        # Selector fleksibel untuk tombol Kick All Utama
        kick_everywhere_btn_selectors = [
            'button[data-testid*="log-out-everywhere"]',
            '[data-testid="display-card__button--log-out-everywhere"]',
            'button:has-text("Keluar dari semua perangkat")',
            'button:has-text("Log out of all devices")',
            'button:has-text("Log Out of All Devices")',
            'button:has-text("Log out everywhere")'
        ]
        kick_everywhere_btn = ", ".join(kick_everywhere_btn_selectors)

        # 1. TUNGGU STABILISASI SESI HALAMAN SETELAH GANTI PASSWORD
        await progress("⚙️ Memeriksa status halaman dan menuju menu Keamanan Akun...")
        await popup_page.wait_for_timeout(2000)

        # 2. NAVIGASI KE HALAMAN ACCESS & SECURITY
        is_on_security_page = "access-security" in popup_page.url
        is_kick_btn_visible = False
        
        try:
            is_kick_btn_visible = await popup_page.is_visible(kick_everywhere_btn)
        except Exception:
            is_kick_btn_visible = False

        if not is_on_security_page or not is_kick_btn_visible:
            # Skenario A: Coba klik Card/Link di Dashboard terlebih dahulu
            nav_selectors = [
                'a[href*="/access-security"]',
                'a[href*="access-security"]',
                'a:has-text("View all settings")',
                'a:has-text("Lihat semua pengaturan")',
                'a:has-text("Access & Security")',
                'a:has-text("Akses & Keamanan")',
                'button:has-text("Access & Security")'
            ]
            
            nav_clicked = False
            for sel in nav_selectors:
                try:
                    elem = popup_page.locator(sel).first
                    if await elem.is_visible(timeout=2000):
                        await elem.click(force=True)
                        nav_clicked = True
                        await popup_page.wait_for_timeout(2000)
                        break
                except Exception:
                    continue

            # Skenario B (Fallback Utama): Navigasi langsung via URL jika klik UI tidak merespons
            if "access-security" not in popup_page.url:
                await progress("🔄 Navigasi langsung ke https://my.disney.com/access-security...")
                await popup_page.goto("https://my.disney.com/access-security", wait_until="domcontentloaded", timeout=20000)
                await popup_page.wait_for_timeout(2000)

        # 3. VERIFIKASI & RETRY JIKA TOMBOL KICK ALL BELUM TERENDER
        kick_found = False
        for attempt in range(1, 4):
            try:
                await popup_page.wait_for_selector(kick_everywhere_btn, state="visible", timeout=6000)
                kick_found = True
                break
            except Exception:
                await progress(f"⏳ Menunggu tombol Kick All muncul (percobaan {attempt}/3)...")
                if attempt == 2 and "access-security" in popup_page.url:
                    # Reload halaman jika hydration Next.js tertahan
                    await popup_page.reload(wait_until="domcontentloaded")
                elif attempt < 3 and "access-security" not in popup_page.url:
                    await popup_page.goto("https://my.disney.com/access-security", wait_until="domcontentloaded", timeout=15000)
                await popup_page.wait_for_timeout(2000)

        if not kick_found:
            await progress("⚠️ Tombol Kick All tidak ditemukan di halaman Keamanan.")
            return False

        # 4. TEKAN TOMBOL LOG OUT OF ALL DEVICES
        await progress("🔴 Menekan tombol 'Keluar dari semua perangkat'...")
        kick_btn = popup_page.locator(kick_everywhere_btn).first
        await kick_btn.scroll_into_view_if_needed()
        await kick_btn.click(force=True)
        await popup_page.wait_for_timeout(2000)

        # 5. HANDLER TAHAP SEND CODE / VERIFIKASI SSO (JIKA DIPERLUKAN)
        await progress("📩 Memeriksa konfirmasi pengiriman kode verifikasi Kick All...")
        
        sent_success = False
        for attempt in range(8):
            frames_to_check = [popup_page] + popup_page.frames
            for frame in frames_to_check:
                try:
                    clicked = await frame.evaluate("""() => {
                        const radio = document.querySelector('#deliveryMethod-0');
                        if (radio) radio.checked = true;

                        const btn = document.querySelector('#choose-delivery-method') 
                                 || document.querySelector('button[data-testid="send-passcode-button"]')
                                 || document.querySelector('button[form="chooseDeliveryMethod"]')
                                 || document.querySelector('button[type="submit"]');

                        if (btn && btn.offsetParent !== null) {
                            btn.removeAttribute('disabled');
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

# 6. PENANGANAN INPUT OTP KICK ALL
        await progress("📩 Menunggu kolom kode OTP verifikasi Kick All...")
        otp_input_selector = '#otp-code-input-otpCode-0'
        
        target_frame = None
        for _ in range(30):
            for frame in [popup_page] + popup_page.frames:
                try:
                    if await frame.is_visible(otp_input_selector):
                        target_frame = frame
                        break
                except Exception:
                    pass
            if target_frame:
                break
            await asyncio.sleep(0.5)

        # Jika modal OTP muncul, jalankan pengisian dan eksekusi reCAPTCHA
        if target_frame:
            await progress("📩 Mengambil OTP verifikasi Kick All dari IMAP...")
            request_time = time.time() - 10
            otp_code = await fetch_disney_otp(email=email, max_wait_seconds=60, since_time=request_time)

            if not otp_code or len(str(otp_code).strip()) < 6:
                await progress("❌ Gagal mendapatkan OTP verifikasi Kick All!")
                return False

            otp_code = str(otp_code).strip()
            await progress(f"🔑 Memasukkan OTP Kick All ({otp_code})...")

            # Isi 6 kotak OTP
            for i in range(6):
                box = target_frame.locator(f'#otp-code-input-otpCode-{i}')
                await box.wait_for(state="visible", timeout=5000)
                await box.focus()
                await box.fill(otp_code[i])
                await box.dispatch_event("input")
                await box.dispatch_event("change")
                await asyncio.sleep(0.05)

            await popup_page.wait_for_timeout(500)

            # Eksekusi reCAPTCHA Enterprise v3 agar React mengizinkan submit
            try:
                await target_frame.evaluate("""
                    async () => {
                        if (typeof grecaptcha !== 'undefined' && grecaptcha.enterprise) {
                            return new Promise((resolve) => {
                                grecaptcha.enterprise.ready(async () => {
                                    try {
                                        const token = await grecaptcha.enterprise.execute('6Lcx8hUtAAAAAA3X3cEnP2NXw35jJutlVQ_Fb1Ln', {action: 'submit'});
                                        resolve(token);
                                    } catch (e) {
                                        resolve(null);
                                    }
                                });
                            });
                        }
                    }
                """)
            except Exception:
                pass

            await popup_page.wait_for_timeout(500)

            # Submit spesifik pada tombol redeem OTP & paksa lepas attribute disabled
            await progress("🔘 Memverifikasi OTP Kick All...")
            submitted = await target_frame.evaluate("""
                () => {
                    const btn = document.querySelector('button[data-testid="redeem-otp"]') || 
                                document.querySelector('button[data-testid="continue-button"]') ||
                                document.querySelector('button[data-testid="otp-submit"]') ||
                                document.querySelector('#otp-recovery button[type="submit"]');
                    if (btn) {
                        btn.removeAttribute('disabled');
                        btn.focus();
                        btn.click();
                        return true;
                    }
                    return false;
                }
            """)

            if not submitted:
                await target_frame.keyboard.press("Enter")

            # Beri jeda agar transisi verifikasi selesai dan modal tertutup sempurna
            await popup_page.wait_for_timeout(4000)
            
        # 7. EKSEKUSI TOMBOL KONFIRMASI AKHIR LOGOUT EVERYWHERE
        await progress("⚙️ Menunggu konfirmasi 'Keluar' akhir...")
        final_logout_selector = 'button[data-testid="log-out-everywhere__button--submit-log-out-everywhere"], button[data-testid*="submit-log-out-everywhere"], button:not(#sign_out):has-text("Keluar dari semua perangkat")'

        final_clicked = False
        for frame in [popup_page] + popup_page.frames:
            try:
                btn = frame.locator(final_logout_selector).first
                if await btn.is_visible(timeout=5000):
                    await progress("🔴 Menekan tombol Konfirmasi Keluar Akhir...")
                    await btn.click(force=True)
                    final_clicked = True
                    break
            except Exception:
                pass

        if not final_clicked:
            print("[LOG] Fallback JS untuk klik Final Logout...")
            for frame in [popup_page] + popup_page.frames:
                try:
                    await frame.evaluate("""() => {
                        const btn = document.querySelector('button[data-testid="log-out-everywhere__button--submit-log-out-everywhere"]')
                                 || document.querySelector('button[data-testid*="submit-log-out-everywhere"]');
                        if (btn && btn.id !== 'sign_out') btn.click();
                    }""")
                except Exception:
                    pass

        await popup_page.wait_for_timeout(3000)
        await progress("✅ Berhasil mengeluarkan seluruh perangkat (Kick All).")

        if tg_id:
            await log_activity(tg_id, "KICK_ALL_DEVICES", email, "SUCCESS", "Berhasil mengeluarkan seluruh perangkat.")
        return True

    except Exception as e:
        error_msg = str(e)
        await progress(f"❌ Error saat Kick All: {error_msg}")
        if tg_id:
            await log_activity(tg_id, "KICK_ALL_DEVICES", email, "FAILED", error_msg)
        return False  
