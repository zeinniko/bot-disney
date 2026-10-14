import asyncio
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


    # 4. MENUNGGU "WHO'S WATCHING" & KLIK PROFIL
    if progress_cb:
        await progress_cb("👤 Menunggu Autentikasi User…")

    profile_card_selector = (
        '[data-testid="profile-avatar"], [data-testid="profile-item"], '
        'div[data-testid^="profile-"], .profile-avatar'
    )

    try:
        # Tunggu avatar profil muncul (gunakan state="visible" agar elemen benar-benar siap render)
        await page.wait_for_selector(profile_card_selector, state="visible", timeout=35000)
        await page.wait_for_timeout(2000)

        if progress_cb:
            await progress_cb("👇 Mengklik profil utama…")
            
        first_profile = page.locator(profile_card_selector).first
        
        # Coba klik dengan force, jika gagal fallback ke evaluasi JS
        try:
            await first_profile.click(force=True, timeout=5000)
        except Exception:
            await page.evaluate(f"""
                const profile = document.querySelector('{profile_card_selector}');
                if (profile) profile.click();
            """)

        # Tunggu perpindahan URL ke halaman home atau dashboard utama
        try:
            await page.wait_for_url("**/home**", timeout=20000)
        except Exception:
            # Jika URL tidak mengandung /home tapi proses sudah berjalan, biarkan lanjut asal tidak error
            pass

        if telegram_user and "id" in telegram_user:
            await upsert_user(
                telegram_id=telegram_user["id"],
                username=telegram_user.get("username"),
                full_name=telegram_user.get("full_name"),
                role="customer"
            )
        return {"status": "success", "message": "Login berhasil"}

    except Exception as e:
        if await page.is_visible(password_selector) or await page.is_visible('.invalid-feedback'):
            return {"status": "error", "message": "Password salah"}
        
        return {"status": "error", "message": f"Gagal melewati layar profil: {str(e)}"}

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

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS_MODE,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1280,720"
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="en-US",
            viewport={"width": 1280, "height": 720}
        )
        await context.clear_cookies()
        page = await context.new_page()
        try:
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
            navigated = False
            for attempt in range(1, 4):
                await trigger_change_password()
                
                # Cek apakah indikator halaman berikutnya (#choose-delivery-method atau input OTP) sudah muncul
                try:
                    await page.wait_for_selector(
                        '#choose-delivery-method, #otp-code-input-otpCode-0, #recovery-reset',
                        state="visible",
                        timeout=4000
                    )
                    navigated = True
                    break
                except Exception:
                    await progress(f"⏳ Menunggu transisi ke form ubah password (percobaan {attempt}/3)...")
                    await page.wait_for_timeout(1500)

            # FALLBACK DARURAT: Jika klik di UI gagal akibat hydration lock Next.js
            if not navigated:
                await progress("🔄 Event UI tidak merespons, mengeksekusi navigasi langsung via href...")
                target_href = await page.evaluate("""() => {
                    const link = document.querySelector('a[href*="/edit/password"]');
                    return link ? link.getAttribute('href') : null;
                }""")
                if target_href:
                    # Jika href berupa path relatif, gabungkan dengan origin
                    full_url = target_href if target_href.startswith("http") else f"https://my.disney.com{target_href}"
                    await page.goto(full_url, wait_until="domcontentloaded", timeout=15000)
                else:
                    await page.goto("https://my.disney.com/edit/password", wait_until="domcontentloaded", timeout=15000)

            # Beri jeda stabilisasi akhir
            await page.wait_for_timeout(2000)

            choose_delivery_selector = "#choose-delivery-method"
            otp_request_timestamp = time.time()
            try:
                await page.wait_for_selector(
                    choose_delivery_selector,
                    state="visible",
                    timeout=15000
                )
            except Exception:
                otp_first = page.locator("#otp-code-input-otpCode-0")
                if not await otp_first.is_visible():
                    raise Exception("Tombol #choose-delivery-method tidak ditemukan.")
            else:
                choose_delivery_btn = page.locator(choose_delivery_selector)
                await progress("📧 Mengirim kode verifikasi Ubah Password...")
                await choose_delivery_btn.click(force=True)
                await page.wait_for_timeout(1500)
            first_otp_selector = "#otp-code-input-otpCode-0"
            await page.wait_for_selector(
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
                box_locator = page.locator(f"#otp-code-input-otpCode-{i}")
                await box_locator.wait_for(state="visible", timeout=5000)
                await box_locator.focus()
                await box_locator.fill(otp_digits[i])
                await box_locator.dispatch_event("input")
                await box_locator.dispatch_event("change")
                await page.wait_for_timeout(100)
            await page.wait_for_timeout(1000)
            await progress("🔓 Memverifikasi kode OTP...")
            submit_success = await page.evaluate("""
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
            save_btn_selector = 'button[data-testid="new-password-submit"], #new-password-submit'
            save_btn = page.locator(save_btn_selector).first
            await save_btn.wait_for(
                state="visible",
                timeout=10000
            )
            try:
                await page.wait_for_function(
                    """
                    () => {
                        const btn = document.querySelector('#new-password-submit');
                        return btn && !btn.disabled;
                    }
                    """,
                    timeout=10000
                )
            except Exception:
                pass
            await save_btn.click(force=True)
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
            return {
                "status": "success",
                "message": "Kata sandi MyDisney berhasil diubah!"
            }
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
            try:
                await page.close()
            except Exception:
                pass
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
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
    """Mengolah alur Kick All / Logout EveryWhere di MyDisney"""
    tg_id = telegram_user.get("id") if telegram_user else None
    
    async def progress(msg: str):
        if progress_cb:
            await progress_cb(msg)

    try:
        # Selector untuk tombol Kick All Utama
        kick_everywhere_btn = '[data-testid="display-card__button--log-out-everywhere"], button:has-text("Keluar dari semua perangkat"), button:has-text("Log out of all devices")'

        # 1. NAVIGASI KE HALAMAN ACCESS & SECURITY JIKA BELUM TERLIHAT
        if not await popup_page.is_visible(kick_everywhere_btn):
            await progress("⚙️ Berpindah ke menu Keamanan Akun (Access & Security)...")

            # Selector Link berdasarkan HTML Dashboard resmi: href="/access-security" & teks "View all settings"
            security_nav_selector = 'a[href*="/access-security"], a:has-text("View all settings"), a:has-text("Lihat semua pengaturan")'
            
            nav_clicked = False
            try:
                # Coba klik link di Dashboard
                nav_link = popup_page.locator(security_nav_selector).first
                if await nav_link.is_visible(timeout=5000):
                    await nav_link.click(force=True)
                    nav_clicked = True
            except Exception:
                pass

            # Fallback jika link UI tidak merespons: Navigasi langsung via URL
            if not nav_clicked and "access-security" not in popup_page.url:
                await popup_page.goto("https://my.disney.com/access-security", wait_until="domcontentloaded", timeout=15000)

            # Tunggu tombol Kick All muncul di layar
            try:
                await popup_page.wait_for_selector(kick_everywhere_btn, state="visible", timeout=15000)
            except Exception:
                await progress("⚠️ Tombol Kick All tidak ditemukan di halaman Keamanan.")
                return False

        # 2. TEKAN TOMBOL LOG OUT OF ALL DEVICES
        await progress("🔴 Menekan tombol 'Keluar dari semua perangkat'...")
        kick_btn = popup_page.locator(kick_everywhere_btn).first
        await kick_btn.scroll_into_view_if_needed()
        await kick_btn.click(force=True)
        await popup_page.wait_for_timeout(2000)

        # 3. HANDLER TAHAP SEND CODE / VERIFIKASI SSO (JIKA DIPERLUKAN)
        await progress("📩 Memeriksa konfirmasi pengiriman kode verifikasi Kick All...")
        
        # Cari tombol Kirim / Choose Delivery Method baik di main page maupun iframe
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

        # 4. PENANGANAN INPUT OTP KICK ALL
        await progress("📩 Menunggu kolom kode OTP verifikasi Kick All...")
        otp_input_selector = '#otp-code-input-otpCode-0'
        
        target_frame = None
        for _ in range(30):  # Wait up to 15 seconds
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

        # Jika ada modal OTP yang muncul, lakukan pengisian OTP
        if target_frame:
            await progress("📩 Mengambil OTP verifikasi Kick All dari IMAP...")
            request_time = time.time() - 10
            otp_code = await fetch_disney_otp(email=email, max_wait_seconds=60, since_time=request_time)

            if not otp_code or len(str(otp_code).strip()) < 6:
                await progress("❌ Gagal mendapatkan OTP verifikasi Kick All!")
                return False

            otp_code = str(otp_code).strip()
            await progress(f"🔑 Memasukkan OTP Kick All ({otp_code})...")

            # Fill 6 box OTP
            for i in range(6):
                box = target_frame.locator(f'#otp-code-input-otpCode-{i}')
                await box.fill(otp_code[i])
                await box.dispatch_event("input")
                await box.dispatch_event("change")
                await asyncio.sleep(0.05)

            await popup_page.wait_for_timeout(1000)

            # Submit OTP
            await progress("🔘 Memverifikasi OTP Kick All...")
            enter_otp_selector = 'button[data-testid="redeem-otp"], button[type="submit"]'
            try:
                submit_btn = target_frame.locator(enter_otp_selector).first
                await submit_btn.click(force=True)
            except Exception:
                await target_frame.keyboard.press("Enter")

            await popup_page.wait_for_timeout(4000)

        # 5. EKEKUSI TOMBOL KONFIRMASI AKHIR LOGOUT EVERYWHERE
        await progress("⚙️ Menunggu konfirmasi 'Keluar' akhir...")
        final_logout_selector = 'button[data-testid="log-out-everywhere__button--submit-log-out-everywhere"], button:has-text("Log Out"), button:has-text("Keluar")'

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
            # Fallback via JS native di seluruh frame
            for frame in [popup_page] + popup_page.frames:
                try:
                    await frame.evaluate("""() => {
                        const btn = document.querySelector('button[data-testid="log-out-everywhere__button--submit-log-out-everywhere"]');
                        if (btn) btn.click();
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
    
