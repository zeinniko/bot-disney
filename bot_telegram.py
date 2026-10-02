import asyncio
import re
import secrets
import string
from playwright.async_api import async_playwright

# Import fungsi IMAP dari modul services
from services.imap_service import fetch_disney_otp


# ==============================================================================
# HELPER: GENERATOR PASSWORD RANDOM & FILL OTP
# ==============================================================================
def generate_random_password(length: int = 12) -> str:
    """Membuat password acak yang memenuhi syarat keamanan Disney+"""
    chars = string.ascii_letters + string.digits
    random_str = "".join(secrets.choice(chars) for _ in range(length - 4))
    return f"Ds#{random_str}9"


async def fill_otp_inputs(page, otp_code: str):
    """Mengisi 6 digit kode OTP pada form Disney+ secara presisi"""
    single_input = 'input[data-testid="passcode-input"], input[name="code"], input[type="tel"]'
    if await page.is_visible(single_input):
        await page.fill(single_input, otp_code)
        return

    digits = await page.query_selector_all('input[data-testid^="digit-"]')
    if digits and len(digits) == 6:
        for i, digit_el in enumerate(digits):
            await digit_el.fill(otp_code[i])
        return

    await page.keyboard.type(otp_code)


# ==============================================================================
# FUNGSI BARU: CHANGE PASSWORD (PLAYWRIGHT + IMAP OTP)
# ==============================================================================
async def change_disney_password(
    email: str, new_password: str = None, signout_all: bool = False
):
    """
    Fungsi Ganti Password Disney+ (2 Skema: Custom / Random Password)
    dengan verifikasi OTP IMAP otomatis.
    """
    # Skema 1 & 2: Tentukan password target (Custom vs Random)
    target_password = (
        new_password.strip()
        if new_password and new_password.strip()
        else generate_random_password()
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            channel="chrome",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--incognito",
            ],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
            locale="en-US",
        )
        page = await context.new_page()

        try:
            print("🚀 Memulai browser Chrome...")
            await context.clear_cookies()

            print("🔑 Membuka halaman login Disney+...")
            await page.goto(
                "https://www.disneyplus.com/login", wait_until="commit"
            )
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(3000)

            print("📧 Mengisi email...")
            email_selector = 'input[data-testid="lookupValue"], #lookupValue, input[name="lookupValue"]'
            await page.wait_for_selector(
                email_selector, state="visible", timeout=30000
            )
            await page.fill(email_selector, email)

            submit_btn = 'button[data-testid="id-flow-submit"], #id-flow'
            await page.click(submit_btn)
            await page.wait_for_timeout(3000)

            # Cek opsi verifikasi OTP / Passcode
            send_passcode_btn = 'button[data-testid="send-passcode-button"]'
            if await page.is_visible(send_passcode_btn):
                print("📩 Mengeklik 'Send Passcode'...")
                await page.click(send_passcode_btn)
                await page.wait_for_timeout(2000)

            # Ambil OTP menggunakan imap_service yang sudah ada
            print("⏳ Menunggu kode OTP dari IMAP...")
            otp_code = await fetch_disney_otp(email=email, timeout=60)

            if not otp_code:
                return {
                    "status": "failed",
                    "message": "Gagal menerima kode OTP dari IMAP.",
                }

            print(f"🔓 Memasukkan OTP ({otp_code})...")
            await fill_otp_inputs(page, otp_code)
            await page.wait_for_timeout(2000)

            if await page.is_visible(submit_btn):
                await page.click(submit_btn)
                await page.wait_for_timeout(3000)

            # Form Pengaturan Password Baru
            print(f"🔒 Mengatur password baru: {target_password}")
            new_pass_selector = 'input[data-testid="password"], input[data-testid="new-password"], input[name="newPassword"]'
            await page.wait_for_selector(
                new_pass_selector, state="visible", timeout=15000
            )
            await page.fill(new_pass_selector, target_password)
            await page.click(submit_btn)
            await page.wait_for_timeout(4000)

            # Opsional: Mode Change Password + Signout All Devices
            if signout_all:
                print("🔴 Melakukan Signout All Devices...")
                await page.goto(
                    "https://www.disneyplus.com/identity/manage-devices",
                    wait_until="domcontentloaded",
                )
                await page.wait_for_timeout(3000)

                kick_all_anchor = 'a[data-testid="anchor-link"]:has-text("log out of all devices")'
                if await page.is_visible(kick_all_anchor):
                    await page.click(kick_all_anchor)
                    await page.wait_for_timeout(2000)

                    confirm_modal_btn = 'button[data-testid="modal-primary-button"], button:has-text("LOG OUT"), button:has-text("Log Out")'
                    if await page.is_visible(confirm_modal_btn):
                        await page.click(confirm_modal_btn)
                        await page.wait_for_timeout(2000)

            print("✅ Berhasil ganti password!")
            return {
                "status": "success",
                "message": "Berhasil (Change Password)",
                "email": email,
                "password": target_password,
            }

        except Exception as e:
            print(f"❌ Terjadi kesalahan: {e}")
            return {"status": "failed", "message": str(e)}
        finally:
            await browser.close()


# ==============================================================================
# FUNGSI-FUNGSI AWAL (TETAP & TIDAK DIUBAH)
# ==============================================================================
async def login_disney(page, context, email: str, password: str):
    print("🚀 Memulai browser Chrome (Clean Session)...")
    await context.clear_cookies()

    await page.goto("https://www.disneyplus.com/login", wait_until="commit")
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(3000)

    print("🔑 Mengisi email...")
    email_selector = 'input[data-testid="lookupValue"], #lookupValue, input[name="lookupValue"]'
    await page.wait_for_selector(
        email_selector, state="visible", timeout=30000
    )
    await page.fill(email_selector, email)

    submit_btn = 'button[data-testid="id-flow-submit"], #id-flow'
    await page.click(submit_btn)
    await page.wait_for_timeout(3000)

    # 1. Cek Akun Tidak Terdaftar
    if await page.is_visible(
        'button[data-testid="registration-prompt-submit-btn"]'
    ):
        return {"status": "error", "message": "Akun tidak terdaftar"}

    # 2. Cek Layar Confirm Identity
    enter_pass_btn = 'button[data-testid="enter-password-button"]'
    if await page.is_visible(
        'button[data-testid="send-passcode-button"]'
    ) or await page.is_visible(enter_pass_btn):
        if await page.is_visible(enter_pass_btn):
            await page.click(enter_pass_btn)
            await page.wait_for_timeout(2000)
        else:
            return {
                "status": "need_otp",
                "message": "Akun wajib verifikasi OTP",
            }

    # 3. Isi Password & Submit
    print("🔑 Mengisi password...")
    password_selector = (
        'input[data-testid="password"], input[type="password"], #password'
    )
    await page.wait_for_selector(
        password_selector, state="visible", timeout=10000
    )
    await page.fill(password_selector, password)
    await page.click(submit_btn)

    # 4. Tunggu Layar "Who's Watching" / Redirect Selesai
    print("⏳ Menunggu pertukaran token & loading layar 'Who's Watching'...")
    try:
        watching_locator = page.get_by_text("watching", exact=False)
        await watching_locator.first.wait_for(state="visible", timeout=35000)
        print("✅ Layar 'Who's Watching' terdeteksi!")
    except Exception:
        if await page.is_visible(password_selector) or await page.is_visible(
            ".invalid-feedback"
        ):
            print("❌ Password salah!")
            return {"status": "error", "message": "Password salah"}
        await page.wait_for_timeout(5000)

    # 5. Navigasi ke Manage Devices
    print("📱 Membuka halaman Manage Devices...")
    await page.goto(
        "https://www.disneyplus.com/identity/manage-devices",
        wait_until="domcontentloaded",
    )
    await page.wait_for_timeout(4000)

    if "manage-devices" in page.url or await page.is_visible(
        '[data-testid="header"]'
    ):
        print("✅ Login & Navigasi berhasil!")
        return {"status": "success", "message": "Login berhasil"}

    return {"status": "failed", "message": "Gagal memverifikasi status login"}


async def get_disney_devices(email: str, password: str):
    """1. FUNGSI LOOKUP & SCRAPING DAFTAR PERANGKAT"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            channel="chrome",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--incognito",
            ],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
            locale="en-US",
        )
        page = await context.new_page()

        try:
            login_res = await login_disney(page, context, email, password)
            if login_res["status"] != "success":
                return login_res

            print("📱 Parsing data perangkat...")
            await page.wait_for_selector(
                '[data-testid^="device-details-"]', timeout=15000
            )

            cards = await page.query_selector_all(
                '[data-testid^="device-details-"]'
            )

            formatted_text = "💻 **DAFTAR PERANGKAT:**\n\n"
            devices_data = []

            for idx, card in enumerate(cards, 1):
                is_current = (
                    await card.query_selector(
                        '[data-testid="current-device-label"]'
                    )
                    is not None
                )

                device_type_el = await card.query_selector(
                    '[data-testid="device-type"] span'
                )
                device_type = (
                    await device_type_el.inner_text()
                    if device_type_el
                    else "Unknown Device"
                )

                location_el = await card.query_selector(
                    '[data-testid="device-location"] span'
                )
                location = (
                    await location_el.inner_text()
                    if location_el
                    else "Unknown Location"
                )

                logged_now = await card.query_selector(
                    '[data-testid="profile-logged-in-now"]'
                )
                date_el = await card.query_selector(
                    '[data-testid="device-profile-date"]'
                )

                if logged_now:
                    time_info = "logged in now"
                elif date_el:
                    time_info = await date_el.inner_text()
                else:
                    time_info = "Unknown"

                if is_current:
                    line = f"✅ {idx}. CURRENT DEVICE - {device_type} - {location} (Perangkat ini)"
                else:
                    line = f"◽️ {idx}. {device_type} - {location} — {time_info}"

                formatted_text += f"{line}\n"
                devices_data.append({
                    "index": idx,
                    "is_current": is_current,
                    "type": device_type,
                    "location": location,
                    "time": time_info,
                })

            formatted_text += "\n— 0 dipilih\nPilih nomor yang mau di-kick:"

            return {
                "status": "success",
                "devices": devices_data,
                "formatted_text": formatted_text,
            }

        except Exception as e:
            print(f"❌ Terjadi kesalahan: {e}")
            return {"status": "failed", "message": str(e)}
        finally:
            await browser.close()


async def kick_all_devices(email: str, password: str):
    """2. FUNGSI KICK ALL DEVICES"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            channel="chrome",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--incognito",
            ],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
            locale="en-US",
        )
        page = await context.new_page()

        try:
            login_res = await login_disney(page, context, email, password)
            if login_res["status"] != "success":
                return login_res

            print("🔴 Mengeklik 'log out of all devices'...")
            kick_all_anchor = 'a[data-testid="anchor-link"]:has-text("log out of all devices")'
            await page.wait_for_selector(kick_all_anchor, timeout=10000)
            await page.click(kick_all_anchor)
            await page.wait_for_timeout(3000)

            confirm_modal_btn = 'button[data-testid="modal-primary-button"], button:has-text("LOG OUT"), button:has-text("Log Out")'
            if await page.is_visible(confirm_modal_btn):
                print("⚠️ Konfirmasi pop-up modal...")
                await page.click(confirm_modal_btn)
                await page.wait_for_timeout(3000)

            print("✅ Berhasil kick semua perangkat!")
            return {
                "status": "success",
                "message": "Semua perangkat berhasil di-kick!",
            }

        except Exception as e:
            print(f"❌ Terjadi kesalahan: {e}")
            return {"status": "failed", "message": str(e)}
        finally:
            await browser.close()


async def kick_specific_devices(
    email: str, password: str, target_indexes: list
):
    """3. FUNGSI KICK PERANGKAT PILIHAN"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            channel="chrome",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--incognito",
            ],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
            locale="en-US",
        )
        page = await context.new_page()

        try:
            login_res = await login_disney(page, context, email, password)
            if login_res["status"] != "success":
                return login_res

            print(f"🎯 Memproses kick untuk nomor: {target_indexes}")
            kicked_count = 0
            sorted_targets = sorted(target_indexes, reverse=True)

            for idx in sorted_targets:
                card_selector = f'[data-testid="device-details-{idx - 1}"]'
                card = await page.query_selector(card_selector)

                if card:
                    remove_btn = await card.query_selector(
                        '[data-testid="remove-btn"]'
                    )
                    if remove_btn:
                        print(f"🔘 Klik Log Out pada perangkat nomor {idx}...")
                        await remove_btn.click()
                        await page.wait_for_timeout(2000)

                        confirm_btn = 'button[data-testid="modal-primary-button"], button:has-text("LOG OUT"), button:has-text("Log Out")'
                        if await page.is_visible(confirm_btn):
                            await page.click(confirm_btn)
                            await page.wait_for_timeout(2000)

                        kicked_count += 1

            return {
                "status": "success",
                "message": f"Berhasil kick {kicked_count} perangkat pilihan.",
            }

        except Exception as e:
            print(f"❌ Terjadi kesalahan: {e}")
            return {"status": "failed", "message": str(e)}
        finally:
            await browser.close()


# ==============================================================================
# MAIN TESTER (RUNNER)
# ==============================================================================
if __name__ == "__main__":
    TEST_EMAIL = "szkutmag333@kenshin.id"

    # Contoh Test 1: Random Password
    res = asyncio.run(change_disney_password(email=TEST_EMAIL))

    # Contoh Test 2: Custom Password
    # res = asyncio.run(
    #     change_disney_password(email=TEST_EMAIL, new_password="Masukaja6156")
    # )

    print("\n--- HASIL ESEKUSI ---")
    print(res)