import asyncio
import time
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from playwright.async_api import async_playwright
from config.settings import HEADLESS_MODE
from bot.states import MenuState
from services.disney_service import login_disney, process_kick_all_in_new_tab
from services.imap_service import fetch_disney_otp

router = Router()

# Tempat menyimpan objek browser aktif agar tidak langsung close
ACTIVE_BROWSER_SESSIONS: dict[int, dict] = {}


# =========================================================================
# HELPER: MENGATUR TEKS DAFTAR PERANGKAT & INLINE KEYBOARD
# =========================================================================
def build_device_view(devices: list, selected_indices: set) -> tuple[str, InlineKeyboardMarkup]:
    formatted_text = "💻 **DAFTAR PERANGKAT TERHUBUNG:**\n\n"
    
    for d in devices:
        idx = d["index"]
        is_current = d["is_current"]
        dev_type = d["type"]
        loc = d["location"]
        t_info = d["time"]

        is_selected = idx in selected_indices

        if is_current:
            formatted_text += f"✅ {idx}. **CURRENT DEVICE** - {dev_type} - {loc} *(Perangkat ini)*\n"
        else:
            prefix = "☑️" if is_selected else "◽️"
            formatted_text += f"{prefix} {idx}. {dev_type} - {loc} — `{t_info}`\n"

    total_selected = len(selected_indices)
    formatted_text += f"\n— **{total_selected} dipilih**\nPilih nomor perangkat yang ingin di-kick:"

    keyboard = []
    row = []

    for d in devices:
        idx = d["index"]
        is_current = d["is_current"]

        if is_current:
            btn = InlineKeyboardButton(text=f"🚫 {idx} (Current)", callback_data="ignore_current")
        else:
            if idx in selected_indices:
                btn = InlineKeyboardButton(text=f"✅ {idx}", callback_data=f"toggle_dev_{idx}", style="success")
            else:
                btn = InlineKeyboardButton(text=f"🔘 {idx}", callback_data=f"toggle_dev_{idx}")

        row.append(btn)
        if len(row) == 3:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    if total_selected > 0:
        kick_selected_btn = InlineKeyboardButton(
            text=f"🔴 Kick Selected ({total_selected})", 
            callback_data="action_kick_selected",
            style="success"
        )
    else:
        kick_selected_btn = InlineKeyboardButton(
            text="⚪️ Kick Selected (0)", 
            callback_data="ignore_empty_selected"
        )

    kick_all_btn = InlineKeyboardButton(text="🔵 Kick All Devices", callback_data="action_kick_all", style="primary")
    cancel_btn = InlineKeyboardButton(text="❌ Cancel", callback_data="action_cancel_lookup", style="danger")

    keyboard.append([kick_all_btn])
    keyboard.append([kick_selected_btn])
    keyboard.append([cancel_btn])

    return formatted_text, InlineKeyboardMarkup(inline_keyboard=keyboard)


def render_code_block(log_list: list) -> str:
    # Membatasi 10 baris terakhir agar tidak melebihi batas 4096 karakter Telegram
    truncated_logs = log_list[-10:]
    content = "\n".join(truncated_logs)
    return f"```\n{content}\n```"


async def close_session(chat_id: int):
    """Fungsi pembantu untuk menutup browser saat proses selesai / dibatalkan"""
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


async def fetch_devices_from_page(page) -> list:
    """Fungsi pembantu membaca elemen daftar device dari DOM"""
    try:
        await page.wait_for_selector('[data-testid^="device-details-"]', state="attached", timeout=20000)
    except Exception:
        pass
    cards = await page.query_selector_all('[data-testid^="device-details-"]')
    
    devices_data = []
    for idx, card in enumerate(cards, 1):
        is_current = await card.query_selector('[data-testid="current-device-label"]') is not None
        
        device_type_el = await card.query_selector('[data-testid="device-type"] span')
        device_type = await device_type_el.inner_text() if device_type_el else "Unknown Device"

        location_el = await card.query_selector('[data-testid="device-location"] span')
        location = await location_el.inner_text() if location_el else "Unknown Location"

        logged_now = await card.query_selector('[data-testid="profile-logged-in-now"]')
        date_el = await card.query_selector('[data-testid="device-profile-date"]')

        if logged_now:
            time_info = "logged in now"
        elif date_el:
            time_info = await date_el.inner_text()
        else:
            time_info = "Unknown"

        devices_data.append({
            "index": idx,
            "is_current": is_current,
            "type": device_type,
            "location": location,
            "time": time_info
        })
    return devices_data


async def handle_otp_if_required(page, email: str, progress_cb=None) -> bool:
    """Handling otomatis jika Disney+ meminta OTP setelah klik Log Out"""
    otp_container_selector = '[data-testid="otp-container"]'
    try:
        if await page.is_visible(otp_container_selector, timeout=4000):
            if progress_cb:
                await progress_cb("📩 Disney meminta verifikasi OTP email...")

            request_time = time.time() - 10
            otp_code = await fetch_disney_otp(email=email, max_wait_seconds=60, since_time=request_time)

            if not otp_code or len(otp_code) < 6:
                if progress_cb:
                    await progress_cb("❌ Gagal mendapatkan OTP dari IMAP!")
                return False

            if progress_cb:
                await progress_cb(f"🔑 Mengisi OTP ({otp_code})...")

            # Mengisi 6 input digit
            for i in range(6):
                digit_input = f'[data-testid="digit-{i}"]'
                await page.fill(digit_input, otp_code[i])
                await asyncio.sleep(0.05)

            # Klik continue
            continue_btn = 'button[data-testid="continue-btn"]'
            if await page.is_visible(continue_btn):
                await page.click(continue_btn, force=True)
                await page.wait_for_timeout(3000)

            return True
    except Exception:
        pass
    return True


# =========================================================================
# 1. RECEIVE INPUT EMAIL|PASSWORD|ACCESS_CODE & START PROCESS
# =========================================================================
@router.message(MenuState.lookup_kick)
async def handle_input_lookup_kick(message: types.Message, state: FSMContext):
    raw_data = message.text.strip()
    parts = [p.strip() for p in raw_data.split("|")]

    if len(parts) < 3:
        await message.answer("⚠️️ Format salah. Gunakan format:\n<code>email|password|kode_akses</code>", parse_mode="HTML")
        return

    email, password, access_code = parts[0], parts[1], parts[2]
    chat_id = message.chat.id

    await close_session(chat_id)

    logs = []
    status_msg = await message.answer("```\n🚀 Memulai...\n```", parse_mode="Markdown")

    async def append_progress(step_text: str):
        logs.append(step_text)
        try:
            await status_msg.edit_text(render_code_block(logs), parse_mode="Markdown")
        except Exception:
            pass

    try:
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
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
                "--lang=en-US,en"
            ]
        )
        context = await browser.new_context(
            storage_state=None,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36", 
            locale="en-US",
            ignore_https_errors=True,
            viewport={'width': 1280, 'height': 720},
            java_script_enabled=True
        )
        await context.clear_cookies()
        page = await context.new_page()

        ACTIVE_BROWSER_SESSIONS[chat_id] = {
            "pw": pw,
            "browser": browser,
            "context": context,
            "page": page,
            "email": email,
            "password": password
        }

        await append_progress("🚀 Memulai browser...")
        await append_progress("🔵 Login ke Disney+...")

        login_res = await login_disney(page, context, email, password, progress_cb=append_progress)
        if login_res["status"] != "success":
            logs.append(f"❌ Gagal: {login_res.get('message')}")
            await status_msg.edit_text(render_code_block(logs), parse_mode="Markdown")
            await close_session(chat_id)
            return

        await append_progress("✅ Login via Password berhasil!")
        await append_progress("⏳ Menunggu autentikasi selesai...")

        profile_selector = '[data-testid="profile-item"], .profile-avatar, [data-testid="profile-avatar"], button[aria-label*="Profile"]'
        try:
            profile_elem = page.locator(profile_selector).first
            if await profile_elem.is_visible(timeout=5000):
                await profile_elem.click(force=True)
                await page.wait_for_timeout(3000)
        except Exception:
            pass

        await append_progress("📱 Membuka daftar perangkat...")
        await page.goto("https://www.disneyplus.com/en-gb/identity/manage-devices", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        devices = await fetch_devices_from_page(page)
        ACTIVE_BROWSER_SESSIONS[chat_id]["devices"] = devices

        await append_progress(f"📋 Ditemukan {len(devices)} perangkat.")

        await state.update_data(email=email, password=password, selected_indices=set(), logs=logs)

        device_text, reply_markup = build_device_view(devices, set())
        full_message = f"{render_code_block(logs)}\n\n{device_text}"

        await status_msg.edit_text(full_message, parse_mode="Markdown", reply_markup=reply_markup)

    except Exception as e:
        logs.append(f"❌ Gagal: {str(e)}")
        await status_msg.edit_text(render_code_block(logs), parse_mode="Markdown")
        await close_session(chat_id)


# =========================================================================
# 2. TOGGLE SELEKSI NOMOR DEVICE
# =========================================================================
@router.callback_query(F.data.startswith("toggle_dev_"))
async def handle_toggle_device(callback: types.CallbackQuery, state: FSMContext):
    try:
        await callback.answer()
    except Exception:
        pass

    chat_id = callback.message.chat.id
    sess = ACTIVE_BROWSER_SESSIONS.get(chat_id)
    if not sess:
        await callback.message.edit_text("❌ Sesi telah expired. Silakan masukkan perintah lookup ulang.")
        return

    data = await state.get_data()
    selected_indices = set(data.get("selected_indices", []))
    logs = data.get("logs", [])

    dev_idx = int(callback.data.split("_")[-1])
    if dev_idx in selected_indices:
        selected_indices.remove(dev_idx)
    else:
        selected_indices.add(dev_idx)

    await state.update_data(selected_indices=selected_indices)

    device_text, reply_markup = build_device_view(sess["devices"], selected_indices)
    full_message = f"{render_code_block(logs)}\n\n{device_text}"

    try:
        await callback.message.edit_text(full_message, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception:
        pass


# =========================================================================
# 3. KICK SELECTED & KICK ALL
# =========================================================================
@router.callback_query(F.data.in_({"action_kick_all", "action_kick_selected"}))
async def handle_execute_kick(callback: types.CallbackQuery, state: FSMContext):
    try:
        await callback.answer()
    except Exception:
        pass

    chat_id = callback.message.chat.id
    sess = ACTIVE_BROWSER_SESSIONS.get(chat_id)

    if not sess:
        await callback.message.edit_text("❌ Sesi browser telah kadaluarsa. Silakan masukkan perintah lookup ulang.")
        return

    data = await state.get_data()
    selected_indices = list(data.get("selected_indices", []))
    logs = data.get("logs", [])
    action_type = callback.data

    async def append_kick_progress(step_text: str):
        logs.append(step_text)
        try:
            await callback.message.edit_text(render_code_block(logs), parse_mode="Markdown")
        except Exception:
            pass

    page = sess["page"]
    email = sess["email"]
    initial_devices = sess["devices"]
    kicked_list = []

    try:
        if action_type == "action_kick_all":
            await append_kick_progress("⏳ Menemukan & mengklik tombol 'log out of all devices'...")

            kick_all_anchor = 'a[data-testid="anchor-link"]:has-text("log out of all devices"), a:has-text("log out of all devices")'
            await page.wait_for_selector(kick_all_anchor, timeout=10000)

            # Klik link & tangkap tab baru yang terbuka
            context = sess["context"]
            async with context.expect_page() as popup_info:
                await page.click(kick_all_anchor, force=True)

            popup_page = await popup_info.value

            # Jalankan alur login & kick di tab baru yang ditangkap
            success = await process_kick_all_in_new_tab(popup_page, email, sess["password"], append_kick_progress)

            if success:
                await append_kick_progress("✅ Berhasil keluar dari semua perangkat!")
            else:
                await append_kick_progress("⚠️ Proses Kick All di tab baru menemui kendala.")

            # Tutup tab baru setelah selesai
            try:
                await popup_page.close()
            except Exception:
                pass
        else:
            sorted_targets = sorted(selected_indices, reverse=True)
            total_targets = len(sorted_targets)

            for i, target_idx in enumerate(sorted_targets, 1):
                await append_kick_progress(f"⏳ Mengeluarkan perangkat... ({i}/{total_targets})")

                dev_info = next((d for d in initial_devices if d["index"] == target_idx), None)
                current_cards = await page.query_selector_all('[data-testid^="device-details-"]')
                
                matched_card = None
                if dev_info:
                    for card in current_cards:
                        type_el = await card.query_selector('[data-testid="device-type"] span')
                        loc_el = await card.query_selector('[data-testid="device-location"] span')
                        
                        card_type = await type_el.inner_text() if type_el else ""
                        card_loc = await loc_el.inner_text() if loc_el else ""

                        if card_type == dev_info["type"] and card_loc == dev_info["location"]:
                            matched_card = card
                            break

                if not matched_card and (target_idx - 1) < len(current_cards):
                    matched_card = current_cards[target_idx - 1]

                if matched_card:
                    remove_btn = await matched_card.query_selector('[data-testid="remove-btn"]')
                    if remove_btn:
                        await remove_btn.click(force=True)
                        await page.wait_for_timeout(1500)

                        # Klik Modal Log Out berdasarkan selector persis: data-testid="modal-primary-button"
                        confirm_btn = 'button[data-testid="modal-primary-button"]'
                        try:
                            if await page.is_visible(confirm_btn, timeout=4000):
                                await page.click(confirm_btn, force=True)
                                await page.wait_for_timeout(2000)
                        except Exception:
                            pass

                        # Cek apakah setelah modal Log Out Disney meminta verifikasi OTP
                        await handle_otp_if_required(page, email, append_kick_progress)

                        if dev_info:
                            kicked_list.append(dev_info)

            await append_kick_progress("✅ Selesai!")

        # Ambil kondisi perangkat tersisa setelah proses selesai
        await page.wait_for_timeout(2000)
        remaining_devices = await fetch_devices_from_page(page)

        # SUSUN LAPORAN AKHIR
        report = "Selesai (Kick Device)\n\n"
        report += f" Email: {sess['email']}\n"
        report += f" Password: {sess['password']}\n"
        
        if action_type == "action_kick_all":
            report += f" Devices kicked: {len(initial_devices) - len(remaining_devices)}/{len(initial_devices)}\n\n"
        else:
            report += f" Devices kicked: {len(kicked_list)}/{len(selected_indices)}\n\n"

        if kicked_list:
            report += "Kicked:\n"
            for k in kicked_list:
                report += f"   {k['type']} - {k['location']} — {k['time']}\n"
            report += "\n"

        report += "Masih terhubung:\n"
        for r in remaining_devices:
            if r["is_current"]:
                report += f"   CURRENT DEVICE - {r['type']} - {r['location']}\n"
            else:
                report += f"   {r['type']} - {r['location']} — {r['time']}\n"

        await callback.message.edit_text(f"```\n{report}\n```", parse_mode="Markdown")

    except Exception as e:
        logs.append(f"❌ Gagal: {str(e)}")
        await callback.message.edit_text(render_code_block(logs), parse_mode="Markdown")

    finally:
        await close_session(chat_id)
        await state.clear()


# =========================================================================
# 4. CANCEL & IGNORING
# =========================================================================
@router.callback_query(F.data == "action_cancel_lookup")
async def handle_cancel_lookup(callback: types.CallbackQuery, state: FSMContext):
    chat_id = callback.message.chat.id
    await close_session(chat_id)
    await state.clear()
    await callback.message.edit_text("❌ Proses Lookup Device dibatalkan.")

@router.callback_query(F.data == "ignore_current")
async def handle_ignore_current(callback: types.CallbackQuery):
    await callback.answer("⚠️ Current device tidak dapat dipilih/di-kick!", show_alert=True)

@router.callback_query(F.data == "ignore_empty_selected")
async def handle_ignore_empty(callback: types.CallbackQuery):
    await callback.answer("⚠️ Pilih setidaknya 1 nomor perangkat terlebih dahulu!", show_alert=True)