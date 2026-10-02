import logging
from aiogram import Router, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext

from bot.states import MenuState
from bot.keyboards import get_main_menu_keyboard, get_cancel_keyboard
from bot.templates import TEXT_START, TEXT_CHPASS_ONLY, TEXT_CHPASS_SIGNOUT, TEXT_LOOKUP_KICK
from utils.process_manager import stop_process
from database.db import register_customer

router = Router()
logger = logging.getLogger(__name__)


@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    
    # Simpan/update data user ke SQLite secara otomatis
    user_id = message.from_user.id
    username = message.from_user.username or ""
    full_name = message.from_user.full_name or ""
    
    try:
        await register_customer(
            telegram_id=user_id,
            username=username,
            full_name=full_name,
            role="customer"  # Default role
        )
        logger.info(f"👤 User registered/updated: {user_id} (@{username})")
    except Exception as e:
        logger.error(f"❌ Gagal mendaftarkan user {user_id}: {e}")

    await message.answer(
        text=TEXT_START,
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.message(Command("myid"))
async def cmd_my_id(message: types.Message):
    """Menampilkan Telegram ID pengguna untuk keperluan registrasi Admin."""
    user_id = message.from_user.id
    username = message.from_user.username or "Tidak ada username"
    
    await message.answer(
        f"🆔 <b>Informasi Telegram Anda:</b>\n\n"
        f"• <b>Telegram ID:</b> <code>{user_id}</code>\n"
        f"• <b>Username:</b> @{username}\n"
        f"• <b>Nama:</b> {message.from_user.full_name}",
        parse_mode="HTML"
    )


@router.callback_query(F.data == "btn_chpass_only")
async def process_chpass_only(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(MenuState.chpass_only)
    await callback.message.edit_text(
        text=TEXT_CHPASS_ONLY,
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "btn_chpass_signout")
async def process_chpass_signout(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(MenuState.chpass_signout)
    await callback.message.edit_text(
        text=TEXT_CHPASS_SIGNOUT,
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "btn_lookup_kick")
async def process_lookup_kick(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(MenuState.lookup_kick)
    await callback.message.edit_text(
        text=TEXT_LOOKUP_KICK,
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "btn_cancel")
async def process_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        text=TEXT_START,
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("btn_stop_"))
async def process_stop(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    stop_process(chat_id)
    await callback.answer("🚫 Menghentikan proses...")