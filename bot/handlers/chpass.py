import secrets
import string
from aiogram import Router, types
from aiogram.fsm.context import FSMContext

from bot.keyboards import get_main_menu_button, get_stop_keyboard
from bot.states import MenuState
from services.disney_service import change_password_mydisney, change_password_and_kick_all_mydisney
from database.db import get_account_by_access_code, update_account_password, log_activity
from utils.process_manager import clear_process, is_process_active, start_process

router = Router()


def generate_random_password(length: int = 12) -> str:
    chars = string.ascii_letters + string.digits
    random_str = "".join(secrets.choice(chars) for _ in range(length - 4))
    return f"Ds#{random_str}9"


async def execute_password_change_process(
    message: types.Message,
    state: FSMContext,
    is_signout_all: bool = False
):
    """Fungsi helper utama untuk menangani chpass_only dan chpass_signout."""
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

    # 1. Cek Database Lokal
    acc_data = await get_account_by_access_code(email, access_code)
    if not acc_data:
        await message.answer(
            "❌ <b>Verifikasi Gagal:</b> Email atau Kode Akses tidak ditemukan/salah!",
            parse_mode="HTML"
        )
        return

    current_password = acc_data["current_password"]
    password_target = (
        parts[2].strip()
        if (len(parts) >= 3 and parts[2].strip())
        else generate_random_password()
    )

    chat_id = message.chat.id
    start_process(chat_id)

    executed_steps = []
    action_title = "Change Password & Signout All" if is_signout_all else "Change Password"
    
    status_msg = await message.answer(
        f"<pre>⏳ Memulai proses {action_title}…</pre>",
        reply_markup=get_stop_keyboard(chat_id),
        parse_mode="HTML",
    )

    async def update_status(step_text: str):
        if not is_process_active(chat_id):
            raise Exception("Proses dihentikan oleh pengguna.")
        executed_steps.append(step_text)
        steps_joined = "\n".join(executed_steps)
        report_text = f"<pre>{steps_joined}</pre>"        
        try:
            await status_msg.edit_text(
                text=report_text,
                reply_markup=get_stop_keyboard(chat_id),
                parse_mode="HTML",
            )
        except Exception:
            pass

    try:
        # 2. Eksekusi Service Playwright berdasarkan mode
        if is_signout_all:
            res = await change_password_and_kick_all_mydisney(
                email=email,
                new_password=password_target,
                progress_cb=update_status
            )
            action_log = "CHPASS_SIGNOUT"
        else:
            tg_user_info = {
                "id": message.from_user.id,
                "username": message.from_user.username,
                "full_name": message.from_user.full_name
            }
            res = await change_password_mydisney(
                email=email,
                new_password=password_target,
                progress_cb=update_status,
                telegram_user=tg_user_info,
                keep_open = False
            )
            action_log = "CHANGE_PASSWORD"

        if not is_process_active(chat_id):
            raise Exception("Proses dihentikan oleh pengguna.")

        if res["status"] == "success":
            await update_account_password(email, password_target)
            await log_activity(message.from_user.id, action_log, email, "SUCCESS", "Password berhasil diperbarui")

            success_text = (
                f"🎉 <b>Berhasil ({action_title})</b>\n"
                f"Email: <code>{email}</code>\n"
                f"Password Baru: <code>{password_target}</code>"
            )
            await status_msg.edit_text(
                text=success_text,
                reply_markup=get_main_menu_button(),
                parse_mode="HTML",
            )
        else:
            await log_activity(message.from_user.id, action_log, email, "FAILED", res.get("message"))
            fail_text = (
                f"❌ <b>Gagal ({action_title})</b>\n"
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
        action_log = "CHPASS_SIGNOUT" if is_signout_all else "CHANGE_PASSWORD"
        await log_activity(message.from_user.id, action_log, email, "CANCELLED/FAILED", error_reason)
        
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


# Handler untuk State Change Password Only
@router.message(MenuState.chpass_only)
async def handle_input_chpass_only(message: types.Message, state: FSMContext):
    await execute_password_change_process(message, state, is_signout_all=False)


# Handler untuk State Change Password + Signout All
@router.message(MenuState.chpass_signout)
async def handle_input_chpass_signout(message: types.Message, state: FSMContext):
    await execute_password_change_process(message, state, is_signout_all=True)