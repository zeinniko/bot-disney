import asyncio
import logging
from typing import Callable, Awaitable, Optional, Dict
from aiogram import Router, types
from aiogram.fsm.context import FSMContext
from playwright.async_api import async_playwright

from config.settings import HEADLESS_MODE
from bot.states import MenuState
from bot.keyboards import get_main_menu_button
from database.db import log_activity

router = Router()
logger = logging.getLogger(__name__)

ACTIVE_BROWSER_SESSIONS: dict[int, dict] = {}

# Selector yang digunakan pada alur Login Disney+
EMAIL_SELECTOR = 'input[data-testid="lookupValue"], #lookupValue, input[name="lookupValue"]'
SUBMIT_BTN = 'button[data-testid="id-flow-submit"], #id-flow'
ENTER_PASS_BTN = 'button[data-testid="password-btn"], button[data-testid="login-with-password-button"], [data-testid="identity-passcode-password-link"]'
SEND_PASSCODE_BTN = 'button[data-testid="send-passcode-button"]'
PASSWORD_SELECTOR = 'input[data-testid="password"], input[type="password"], #password'


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


async def get_element(page, selector: str, timeout: int = 20000):
    """Helper untuk mencari elemen di halaman utama maupun dalam iframe"""
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


async def process_tv_login(page, email: str, password: str, tv_code: str, progress_cb=None) -> dict:
    """Alur otomatisasi: /begin -> Input Kode TV -> Input Email -> Pilih Password -> Input Password"""
    try:
        clean_code = tv_code.replace("-", "").strip().upper()

        # 1. Buka disneyplus.com/begin & Input Kode TV
        if progress_cb:
            await progress_cb("🌐 Membuka disneyplus.com/begin...")

        await page.goto("https://www.disneyplus.com/begin", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        if progress_cb:
            await progress_cb(f"📺 Memasukkan Kode TV: {clean_code}...")

        otp_selector = 'input[name="otp"], input[autocomplete="one-time-code"]'
        await page.wait_for_selector(otp_selector, state="visible", timeout=10000)
        await page.click(otp_selector)
        await page.fill(otp_selector, "")
        await page.type(otp_selector, clean_code, delay=100)
        await page.wait_for_timeout(1000)

        # Klik Continue setelah input kode TV
        continue_btn = 'button[data-testid="continue-btn"], button[type="submit"]'
        if progress_cb:
            await progress_cb("🔘 Menekan tombol Continue...")

        if await page.is_visible(continue_btn):
            try:
                await page.wait_for_selector(f'{continue_btn}:not([disabled])', timeout=5000)
            except Exception:
                pass
            await page.click(continue_btn, force=True)
        else:
            await page.keyboard.press("Enter")

        await page.wait_for_timeout(4000)

        # Cek Error awal Kode TV tidak valid
        error_selector = '[data-testid="error-message"], .error-message, [aria-live="assertive"]'
        if await page.is_visible(error_selector, timeout=2000):
            err_el = await page.query_selector(error_selector)
            err_text = await err_el.inner_text() if err_el else "Kode TV tidak valid"
            return {"status": "error", "message": f"Kode TV Error: {err_text}"}

        # 2. Input Email
        if progress_cb:
            await progress_cb("📧 Mengisi email...")

        await page.wait_for_selector(EMAIL_SELECTOR, state="attached", timeout=25000)
        email_input = page.locator(EMAIL_SELECTOR).first
        await email_input.click(force=True)
        await email_input.fill(email)
        await page.click(SUBMIT_BTN)
        await page.wait_for_timeout(3000)

        # Cek jika akun tidak terdaftar
        if await page.is_visible('button[data-testid="registration-prompt-submit-btn"]'):
            return {"status": "error", "message": "Akun tidak terdaftar"}

        # 3. Pilih Metode Login via Password
        if progress_cb:
            await progress_cb("🔐 Memilih metode Password...")

        try:
            pass_btn_elem, _ = await get_element(page, ENTER_PASS_BTN, timeout=10000)
            await pass_btn_elem.click(force=True)
            await page.wait_for_timeout(2000)
        except Exception:
            # Jika halaman langsung menampilkan form password tanpa perlu klik pilihan metode
            pass

        # 4. Input Password & Submit
        if progress_cb:
            await progress_cb("🔑 Memasukkan password akun...")

        await page.wait_for_selector(PASSWORD_SELECTOR, state="visible", timeout=15000)
        await page.fill(PASSWORD_SELECTOR, password)
        await page.click(SUBMIT_BTN)
        await page.wait_for_timeout(5000)

        # Cek jika password salah
        if await page.is_visible('.invalid-feedback') or await page.is_visible('[data-testid="error-message"]'):
            return {"status": "error", "message": "Password salah atau verifikasi gagal"}

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

    # Format yang diharapkan: email|password|kode_tv
    if len(parts) < 3:
        await message.answer(
            "⚠️ Format input salah.\n\nGunakan format:\n<code>email|password|kode_tv</code>\n\nContoh:\n<code>user@gmail.com|MyPass123|ABCD1234</code>",
            parse_mode="HTML",
            reply_markup=get_main_menu_button()
        )
        return

    email = parts[0]
    password = parts[1]
    tv_code = parts[2]

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
            proxy={
                "server": "socks5://127.0.0.1:40000"
            },
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
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-extensions"
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
            locale="en-US",
            ignore_https_errors=True,
            viewport={'width': 1280, 'height': 720}
        )
        page = await context.new_page()

        ACTIVE_BROWSER_SESSIONS[chat_id] = {
            "pw": pw,
            "browser": browser,
            "context": context,
            "page": page
        }

        # Jalankan proses login TV lengkap
        result = await process_tv_login(page, email, password, tv_code, progress_cb=append_progress)

        if result["status"] == "success":
            await append_progress("🎉 Proses Selesai!")
            report = (
                " Selesai (Auto Login TV)\n\n"
                f" Email: {email}\n"
                f" Kode TV: {tv_code.upper()}\n"
                f" Status: BERHASIL TERHUBUNG"
            )
            await message.answer(f"```\n{report}\n```", parse_mode="Markdown", reply_markup=get_main_menu_button())
            await log_activity(chat_id, "AUTO_LOGIN_TV", tv_code, "SUCCESS", f"Email: {email} | Code: {tv_code}")
        else:
            await append_progress(f"❌ {result['message']}")
            await log_activity(chat_id, "AUTO_LOGIN_TV", tv_code, "FAILED", result['message'])

    except Exception as e:
        logs.append(f"❌ Gagal: {str(e)}")
        await status_msg.edit_text(render_code_block(logs), parse_mode="Markdown", reply_markup=get_main_menu_button())
        await log_activity(chat_id, "AUTO_LOGIN_TV", tv_code, "FAILED", str(e))
    finally:
        await close_session(chat_id)
        await state.clear()