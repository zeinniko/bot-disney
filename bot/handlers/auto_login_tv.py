import asyncio
import logging
from typing import Callable, Awaitable, Optional, Dict
from aiogram import Router, types
from aiogram.fsm.context import FSMContext
from playwright.async_api import async_playwright

from bot.states import MenuState
from bot.keyboards import get_main_menu_button
from database.db import log_activity

router = Router()
logger = logging.getLogger(__name__)

ACTIVE_BROWSER_SESSIONS: dict[int, dict] = {}

# Selector halaman Kode TV (/identity/begin)
TV_OTP_SELECTOR = 'input[name="otp"], input[aria-label="Enter the passcode here"], [data-testid="passcode-cells"] input'
TV_CONTINUE_BTN = 'button[data-testid="continue-btn"]'

# Selector alur Login MyDisney setelah Kode TV
EMAIL_SELECTOR = 'input[data-testid="lookupValue"], #lookupValue, input[name="lookupValue"], input[type="email"]'
EMAIL_SUBMIT_BTN = 'button[data-testid="continue-btn"], button[data-testid="id-flow-submit"], #id-flow'
ENTER_PASS_BTN = 'button[data-testid="enter-password-button"], button[data-testid="login-with-password-button"], [data-testid="identity-passcode-password-link"]'
PASSWORD_SELECTOR = 'input[data-testid="password"], input[type="password"], #password'
PASS_SUBMIT_BTN = 'button[data-testid="continue-btn"], button[data-testid="id-flow-submit"], #id-flow'

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['id-ID', 'id', 'en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = { runtime: {} };
"""


def render_code_block(log_list: list) -> str:
    truncated_logs = log_list[-10:]
    content = "\n".join(truncated_logs)
    return f"```\n{content}\n```"


async def close_session(chat_id: int):
    sess = ACTIVE_BROWSER_SESSIONS.get(chat_id)
    if sess:
        try:
            await sess["page"].close()
            await sess["context"].close()
            await sess["browser"].close()
            await sess["pw"].stop()
        except Exception:
            pass
        del ACTIVE_BROWSER_SESSIONS[chat_id]


async def get_element(page, selector: str, timeout: int = 20000, allow_attached: bool = False):
    """Helper untuk mencari elemen di halaman utama maupun dalam iframe"""
    end_time = asyncio.get_event_loop().time() + (timeout / 1000)
    while asyncio.get_event_loop().time() < end_time:
        try:
            el = page.locator(selector).first
            if await el.is_visible() or (allow_attached and await el.count() > 0):
                return el, page
        except Exception:
            pass
        for frame in page.frames:
            try:
                el = frame.locator(selector).first
                if await el.is_visible() or (allow_attached and await el.count() > 0):
                    return el, frame
            except Exception:
                pass
        await asyncio.sleep(0.5)
    raise Exception(f"Timeout {timeout}ms mencari selector: {selector}")


async def process_tv_login(page, email: str, password: str, tv_code: str, progress_cb=None) -> dict:
    """Alur otomatisasi: /identity/begin -> Input Kode TV -> Input Email -> Continue -> Input Password"""
    try:
        clean_code = tv_code.replace("-", "").strip().upper()

        # 1. Buka halaman /identity/begin secara langsung
        if progress_cb:
            await progress_cb("🌐 Membuka disneyplus.com/identity/begin...")

        await page.goto(
            "https://www.disneyplus.com/id-id/identity/begin",
            wait_until="networkidle",
            timeout=45000
        )
        await page.wait_for_timeout(1500)

        if "/identity/begin" not in page.url:
            try:
                start_btn = page.locator('a[href*="identity/begin"], button:has-text("Mulai"), button:has-text("Continue")').first
                if await start_btn.is_visible(timeout=3000):
                    await start_btn.click()
                    await page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                await page.goto("https://www.disneyplus.com/id-id/identity/begin", wait_until="domcontentloaded", timeout=30000)

        # Tutup popup cookie jika muncul
        try:
            cookie_btn = page.locator("#onetrust-accept-btn-handler").first
            if await cookie_btn.is_visible(timeout=2000):
                await cookie_btn.click()
        except Exception:
            pass

        # 2. Input 8-digit Kode TV
        if progress_cb:
            await progress_cb(f"📺 Memasukkan Kode TV: {clean_code}...")

        otp_input, otp_frame = await get_element(page, TV_OTP_SELECTOR, timeout=25000, allow_attached=True)
        await otp_input.click(force=True)
        await page.wait_for_timeout(300)
        await otp_input.fill("")
        await otp_input.press_sequentially(clean_code, delay=90)
        await page.wait_for_timeout(800)

        # 3. Klik Continue setelah input Kode TV
        if progress_cb:
            await progress_cb("🔘 Menekan tombol Continue...")

        continue_btn = otp_frame.locator(TV_CONTINUE_BTN).first
        if await continue_btn.count() > 0:
            try:
                await otp_frame.wait_for_selector(f"{TV_CONTINUE_BTN}:not([disabled])", timeout=6000)
            except Exception:
                pass
            await continue_btn.click()
        else:
            await page.keyboard.press("Enter")

        await page.wait_for_timeout(3500)

        # Cek Error awal Kode TV tidak valid
        is_invalid = await otp_input.get_attribute("aria-invalid") if await otp_input.count() > 0 else "false"
        error_selector = '[data-testid="error-message"], .error-message, [aria-live="assertive"]'
        if is_invalid == "true" or await otp_frame.locator(error_selector).first.is_visible():
            err_el = otp_frame.locator(error_selector).first
            err_text = (await err_el.inner_text()).strip() if await err_el.is_visible() else "Kode TV salah atau kedaluwarsa"
            return {"status": "error", "message": f"Kode TV Error: {err_text}"}

        # 4. Input Email & Klik Continue
        if progress_cb:
            await progress_cb("📧 Mengisi email...")

        email_input, email_frame = await get_element(page, EMAIL_SELECTOR, timeout=25000)
        await email_input.click()
        await email_input.fill("")
        await email_input.press_sequentially(email, delay=40)
        await page.wait_for_timeout(600)

        # Klik tombol Continue khusus form email (bukan tombol header/home)
        submit_email_btn = email_frame.locator(EMAIL_SUBMIT_BTN).first
        if await submit_email_btn.is_visible():
            try:
                await email_frame.wait_for_selector(f"{EMAIL_SUBMIT_BTN}:not([disabled])", timeout=5000)
            except Exception:
                pass
            await submit_email_btn.click()
        else:
            await email_input.press("Enter")

        await page.wait_for_timeout(3500)

        # Cek jika setelah submit email malah ter-redirect ke halaman awal/home
        current_url = page.url.rstrip("/")
        if current_url in ("https://www.disneyplus.com", "https://www.disneyplus.com/id-id", "https://www.disneyplus.com/id-id/home"):
            return {"status": "error", "message": f"Sesi ter-reset ke halaman awal ({page.url}) setelah submit email"}

        # Cek jika akun tidak terdaftar
        if await email_frame.locator('button[data-testid="registration-prompt-submit-btn"]').is_visible():
            return {"status": "error", "message": "Akun tidak terdaftar"}

        # 5. Pilih Metode Login via Password (jika muncul pilihan OTP vs Password)
        try:
            pass_btn_elem, _ = await get_element(page, ENTER_PASS_BTN, timeout=6000)
            if progress_cb:
                await progress_cb("🔐 Memilih metode Password...")
            await pass_btn_elem.click()
            await page.wait_for_timeout(2000)
        except Exception:
            # Langsung masuk ke form input password tanpa layar pilihan metode
            pass

        # 6. Input Password & Klik Continue/Submit
        if progress_cb:
            await progress_cb("🔑 Memasukkan password akun...")

        pass_input, pass_frame = await get_element(page, PASSWORD_SELECTOR, timeout=15000)
        await pass_input.click()
        await pass_input.fill("")
        await pass_input.press_sequentially(password, delay=40)
        await page.wait_for_timeout(600)

        submit_pass_btn = pass_frame.locator(PASS_SUBMIT_BTN).first
        if await submit_pass_btn.is_visible():
            await submit_pass_btn.click()
        else:
            await pass_input.press("Enter")

        if progress_cb:
            await progress_cb("⏳ Menyimpan sesi & menghubungkan perangkat TV...")

        # Tunggu aktif hingga proses login & penyimpanan sesi TV selesai (maksimal 35 detik)
        end_wait = asyncio.get_event_loop().time() + 35
        connected = False

        while asyncio.get_event_loop().time() < end_wait:
            # 1. Cek jika password salah (hanya selector error spesifik, bukan aria-live loading)
            try:
                err_locator = pass_frame.locator('.invalid-feedback, [data-testid="error-message"]').first
                if await err_locator.is_visible():
                    err_text = (await err_locator.inner_text()).strip()
                    if err_text and err_text.lower() not in ("loading", "memuat", "loading..."):
                        return {"status": "error", "message": f"Verifikasi gagal: {err_text}"}
            except Exception:
                pass

            # 2. Cek apakah form login/password sudah hilang dan halaman konfirmasi/sukses TV muncul
            try:
                pass_still_present = await pass_frame.locator(PASSWORD_SELECTOR).count() > 0
                current_url = page.url.lower()
                body_text = (await page.locator("body").inner_text()).lower()

                success_keywords = [
                    "mulai menonton",
                    "start streaming",
                    "all set",
                    "berhasil",
                    "terhubung",
                    "connected",
                    "siap digunakan",
                    "ready to stream",
                ]
                has_success_text = any(kw in body_text for kw in success_keywords)
                redirected_done = any(path in current_url for path in ["/select-profile", "/home", "/begin/success"])

                if not pass_still_present and (has_success_text or redirected_done):
                    connected = True
                    break
            except Exception:
                pass

            await asyncio.sleep(1.0)

        if not connected:
            return {
                "status": "error",
                "message": "Timeout menunggu konfirmasi penyimpanan sesi TV"
            }

        # Beri jeda 3 detik setelah halaman sukses tampil agar request penyimpanan sesi di background tuntas
        await page.wait_for_timeout(3000)

        if progress_cb:
            await progress_cb("✅ Kode TV & Login berhasil dihubungkan!")
        return {"status": "success", "message": "Berhasil terhubung"}

    except Exception as e:
        return {"status": "error", "message": f"Terjadi kesalahan: {str(e)}"}


# =========================================================================
# HANDLER UTAMA TELEGRAM BOT
# =========================================================================
@router.message(MenuState.auto_login_tv)
async def handle_input_auto_login_tv(message: types.Message, state: FSMContext):
    raw_data = message.text.strip()
    parts = [p.strip() for p in raw_data.split("|")]

    if len(parts) < 4:
        await message.answer(
            "⚠️ Format input salah.\n\nGunakan format:\n<code>email|password|kode_akses|kode_tv</code>\n\nContoh:\n<code>john@example.com|P4ssw0rd|A3KN7X|ABCD1234</code>",
            parse_mode="HTML",
            reply_markup=get_main_menu_button()
        )
        return

    email = parts[0]
    password = parts[1]
    access_code = parts[2]
    tv_code = parts[3]

    clean_tv_code = tv_code.replace("-", "").strip().upper()
    if len(clean_tv_code) != 8:
        await message.answer(
            f"⚠️ Kode TV harus 8 karakter (terbaca: <code>{clean_tv_code}</code> - {len(clean_tv_code)} karakter).\n\nPastikan urutan format benar:\n<code>email|password|kode_akses|kode_tv</code>",
            parse_mode="HTML",
            reply_markup=get_main_menu_button()
        )
        return

    chat_id = message.chat.id
    await close_session(chat_id)

    logs = []
    status_msg = await message.answer("```\n🚀 Memulai Proses Auto Login TV...\n```", parse_mode="Markdown")

    async def append_progress(step_text: str):
        logs.append(step_text)
        try:
            await status_msg.edit_text(render_code_block(logs), parse_mode="Markdown")
        except Exception:
            pass

    try:
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=False,
            channel="chrome",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-infobars",
                "--window-size=1366,768",
            ],
            ignore_default_args=["--enable-automation"]
        )
        context = await browser.new_context(
            locale="id-ID",
            timezone_id="Asia/Jakarta",
            viewport={"width": 1366, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        await context.add_init_script(STEALTH_INIT_SCRIPT)
        page = await context.new_page()

        ACTIVE_BROWSER_SESSIONS[chat_id] = {
            "pw": pw,
            "browser": browser,
            "context": context,
            "page": page
        }

        result = await process_tv_login(page, email, password, clean_tv_code, progress_cb=append_progress)

        if result["status"] == "success":
            await append_progress("🎉 Proses Selesai!")
            report = (
                " Selesai (Auto Login TV)\n\n"
                f" Email: {email}\n"
                f" Kode Akses: {access_code.upper()}\n"
                f" Kode TV: {clean_tv_code}\n"
                f" Status: BERHASIL TERHUBUNG"
            )
            await message.answer(f"```\n{report}\n```", parse_mode="Markdown", reply_markup=get_main_menu_button())
            await log_activity(chat_id, "AUTO_LOGIN_TV", clean_tv_code, "SUCCESS", f"Email: {email} | Access: {access_code} | TV: {clean_tv_code}")
        else:
            await append_progress(f"❌ {result['message']}")
            await status_msg.edit_text(render_code_block(logs), parse_mode="Markdown", reply_markup=get_main_menu_button())
            await log_activity(chat_id, "AUTO_LOGIN_TV", clean_tv_code, "FAILED", result['message'])

    except Exception as e:
        logs.append(f"❌ Gagal: {str(e)}")
        await status_msg.edit_text(render_code_block(logs), parse_mode="Markdown", reply_markup=get_main_menu_button())
        await log_activity(chat_id, "AUTO_LOGIN_TV", clean_tv_code, "FAILED", str(e))
    finally:
        await close_session(chat_id)
        await state.clear()