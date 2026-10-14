import html
import logging
from aiogram import Router, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from bot.states import MenuState
from bot.keyboards import get_main_menu_keyboard, get_cancel_keyboard
from bot.templates import TEXT_START, TEXT_CHPASS_ONLY, TEXT_CHPASS_SIGNOUT, TEXT_LOOKUP_KICK
from utils.process_manager import stop_process
from database.db import upsert_user

router = Router()
logger = logging.getLogger(__name__)


@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    
    user_id = message.from_user.id
    username = message.from_user.username or ""
    full_name = message.from_user.full_name or ""
    
    try:
        # PANGGIL UPSERT TANPA MEMAKSA ROLE JADI CUSTOMER (Agar role admin tidak tertimpa)
        await upsert_user(
            telegram_id=user_id,
            username=username,
            full_name=full_name,
            role=None  # Biarkan None agar DB mempertahankan role lama jika user sudah ada
        )
        logger.info(f"👤 User checked/updated: {user_id} (@{username})")
    except Exception as e:
        logger.error(f"❌ Gagal mencatat user {user_id}: {e}")
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
    full_name = html.escape(message.from_user.full_name or "")
    
    await message.answer(
        f"🆔 <b>Informasi Telegram Anda:</b>\n\n"
        f"• <b>Telegram ID:</b> <code>{user_id}</code>\n"
        f"• <b>Username:</b> @{html.escape(username)}\n"
        f"• <b>Nama:</b> {full_name}",
        parse_mode="HTML"
    )


@router.callback_query(F.data == "btn_chpass_only")
async def process_chpass_only(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(MenuState.chpass_only)
    try:
        await callback.message.edit_text(
            text=TEXT_CHPASS_ONLY,
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "btn_chpass_signout")
async def process_chpass_signout(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(MenuState.chpass_signout)
    try:
        await callback.message.edit_text(
            text=TEXT_CHPASS_SIGNOUT,
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "btn_lookup_kick")
async def process_lookup_kick(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(MenuState.lookup_kick)
    try:
        await callback.message.edit_text(
            text=TEXT_LOOKUP_KICK,
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "btn_cancel")
async def process_cancel(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    try:
        await callback.message.edit_text(
            text=TEXT_START,
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("btn_stop_"))
async def process_stop(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    stop_process(chat_id)
    await callback.answer("🚫 Menghentikan proses...", show_alert=False)