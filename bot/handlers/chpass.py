import secrets
import string
from aiogram import Router, types
from aiogram.fsm.context import FSMContext

from bot.keyboards import get_main_menu_button, get_stop_keyboard
from bot.states import MenuState
from services.disney_service import change_disney_password
from database.db import get_account_by_access_code, update_account_password, log_activity
from utils.process_manager import clear_process, is_process_active, start_process

router = Router()

def generate_random_password(length: int = 12) -> str:
    chars = string.ascii_letters + string.digits
    random_str = "".join(secrets.choice(chars) for _ in range(length - 4))
    return f"Ds#{random_str}9"

@router.message(MenuState.chpass_only)
async def handle_input_chpass_only(message: types.Message, state: FSMContext):
    raw_data = message.text.strip()
    parts = [p.strip() for p in raw_data.split("|")]

    if len(parts) < 2:
        await message.answer(
            "Format salah! Gunakan format:\n"
            "<code>email|kode_akses</code> atau <code>email|kode_akses|password_baru</code>",
            parse_mode="HTML",
        )
        return

    email = parts[0]
    access_code = parts[1]

    # 1. CEK DARI DATABASE LOKAL BUKAN INPUT USER
    acc_data = await get_account_by_access_code(email, access_code)
    if not acc_data:
        await message.answer(
            "❌ **Verifikasi Gagal:** Email atau Kode Akses tidak ditemukan/salah!",
            parse_mode="Markdown"
        )
        return

    # Ambil Password Lama dari DB Lokal
    current_password = acc_data["current_password"]

    # Target Password Baru
    password_target = (
        parts[2].strip()
        if (len(parts) >= 3 and parts[2].strip())
        else generate_random_password()
    )

    chat_id = message.chat.id
    start_process(chat_id)

    executed_steps = []
    status_msg = await message.answer(
        "<pre>⏳ Memulai proses Change Password…</pre>",
        reply_markup=get_stop_keyboard(chat_id),
        parse_mode="HTML",
    )

    async def update_status(step_text: str):
        # Pengecekan aktifnya proses setiap kali callback dipanggil
        if not is_process_active(chat_id):
            raise Exception("Proses dihentikan oleh pengguna.")
        executed_steps.append(step_text)
        report_text = f"<pre>{'\n'.join(executed_steps)}</pre>"
        try:
            await status_msg.edit_text(
                text=report_text,
                reply_markup=get_stop_keyboard(chat_id),
                parse_mode="HTML",
            )
        except Exception:
            pass

    try:
        # 2. PROSES OTOMASI PLAYWRIGHT
        res = await change_disney_password(
            email=email,
            current_password=current_password,
            new_password=password_target,
            progress_cb=update_status
        )

        if not is_process_active(chat_id):
            raise Exception("Proses dihentikan oleh pengguna.")

        if res["status"] == "success":
            await update_account_password(email, password_target)
            await log_activity(message.from_user.id, "CHANGE_PASSWORD", email, "SUCCESS")

            success_text = (
                f"🎉 <b>Berhasil (Change Password)</b>\n"
                f"Email: <code>{email}</code>\n"
                f"Password Baru: <code>{password_target}</code>"
            )
            await status_msg.edit_text(
                text=success_text,
                reply_markup=get_main_menu_button(),
                parse_mode="HTML",
            )
        else:
            await log_activity(message.from_user.id, "CHANGE_PASSWORD", email, "FAILED", res.get("message"))
            fail_text = (
                f"❌ <b>Gagal (Change Password)</b>\n"
                f"Email: <code>{email}</code>\n"
                f"Error: <code>{res.get('message', 'Terjadi kesalahan')}</code>"
            )
            await status_msg.edit_text(
                text=fail_text,
                reply_markup=get_main_menu_button(),
                parse_mode="HTML",
            )

    except Exception as err:
        error_reason = str(err)
        await log_activity(message.from_user.id, "CHANGE_PASSWORD", email, "CANCELLED/FAILED", error_reason)
        
        fail_text = (
            f"❌ <b>Proses Terhenti / Gagal</b>\n"
            f"Email: <code>{email}</code>\n"
            f"Keterangan: <code>{error_reason}</code>"
        )
        try:
            await status_msg.edit_text(
                text=fail_text,
                reply_markup=get_main_menu_button(),
                parse_mode="HTML",
            )
        except Exception:
            pass

    finally:
        clear_process(chat_id)