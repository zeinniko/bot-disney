import asyncio
import time
from playwright.async_api import async_playwright
from services.imap_service import fetch_disney_otp  # Mengimpor fungsi IMAP Python kamu


async def login_disney_via_otp(page, target_email: str):
    # Listener log navigasi
    page.on("framenavigated", lambda frame: print(f"[NAVIGATE] URL berubah ke: {frame.url}") if frame == page.main_frame else None)

    # 1. Membuka halaman utama MyDisney
    console_log("[INFO] Membuka my.disney.com...")
    await page.goto("https://my.disney.com/", wait_until="domcontentloaded", timeout=30000)

    # 2. Klik tombol 'Masuk'
    btn_login = page.locator("#sign_in")
    await btn_login.wait_for(state="attached", timeout=20000)
    await btn_login.click()

    # 3. Tunggu transisi ke login.disney.com
    console_log("[INFO] Menunggu transisi ke halaman Login Disney...")
    await page.wait_for_url(lambda url: "login.disney.com" in url, timeout=20000)

    # 4. Tunggu Input Email muncul
    console_log("[INFO] Menunggu form input email...")
    email_selector = '#lookupValue, input[data-testid="lookupValue"], input[name="lookupValue"]'
    email_input = page.locator(email_selector).first

    await email_input.wait_for(state="visible", timeout=30000)
    console_log("[INFO] Form input email ditemukan. Mengisi email...")

    await email_input.click()
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
        console_log("[INFO] Terdeteksi halaman Kata Sandi. Mengklik 'Kesulitan masuk?'...")
        await btn_recovery.click()
        await page.wait_for_timeout(2000)

    # Skenario B: Klik Tombol 'Kirim Email' jika modal konfirmasi / pilihan cara verifikasi muncul
    otp_request_timestamp = time.time()

    if await btn_send_code.is_visible():
        console_log("[INFO] Modal konfirmasi terdeteksi. Mengklik tombol 'Kirim Email'...")
        otp_request_timestamp = time.time()
        await btn_send_code.click()

        await page.wait_for_selector(first_input_selector, state="visible", timeout=20000)
        console_log("[INFO] Modal tertutup. 6 box input OTP aktif di layar.")
    else:
        console_log("[INFO] Halaman pilihan cara verifikasi terdeteksi. Mengklik 'Kirim'...")

        btn_choose_delivery = page.locator("#choose-delivery-method")
        await btn_choose_delivery.wait_for(state="visible", timeout=15000)

        # Catat timestamp Unix (dalam detik, presisi float)
        otp_request_timestamp = time.time()
        await btn_choose_delivery.click()

        console_log("[INFO] Menunggu 6 box input OTP dirender...")
        await page.wait_for_selector(first_input_selector, state="visible", timeout=20000)

        console_log("[INFO] Menunggu 4 detik agar OTP baru terkirim dari server Disney...")
        await page.wait_for_timeout(4000)

    # 5. Ambil OTP via IMAP Service Python
    console_log("[INFO] Menunggu OTP masuk via IMAP Python...")
    otp_code = await fetch_disney_otp(
        email=target_email, 
        max_wait_seconds=45, 
        interval=3, 
        since_time=otp_request_timestamp
    )

    if not otp_code:
        raise Exception("Gagal mendapatkan kode OTP dari email via IMAP!")

    console_log(f"[INFO] Kode OTP baru berhasil didapatkan: {otp_code}")

    # 6. INPUT OTP DENGAN CARA FILL PER-BOX
    console_log("[INFO] Memasukkan kode OTP ke masing-masing input...")
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
    console_log("[INFO] Menjalankan reCAPTCHA Enterprise & Mengirim OTP...")
    
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

    # 8. REDIRECTION & VERIFIKASI URL MY.DISNEY.COM
    console_log("[INFO] Menunggu proses redirect selesai ke my.disney.com...")
    try:
        # Tunggu sampai URL berubah kembali ke my.disney.com tanpa parameter error
        await page.wait_for_url(lambda url: "my.disney.com" in url and "error=" not in url, timeout=25000)
    except Exception:
        pass

    await page.wait_for_timeout(4000)

    btn_continue = page.locator('#recovery-continue, button[data-testid="continue-button"]')
    if await btn_continue.is_visible():
        console_log("[INFO] Mengklik tombol 'Lanjut' tambahan...")
        await btn_continue.click()
        await page.wait_for_timeout(4000)

def console_log(msg: str):
    print(msg)


async def main():
    email_target = "dizney196@pidercat.site"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            await login_disney_via_otp(page, email_target)
            await asyncio.sleep(8)
        except Exception as e:
            console_log(f"[ERROR] {str(e)}")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())