from aiogram import Router, types, F
from aiogram.filters import Command
from database.db import (
    is_admin, add_account_with_key, regenerate_token, 
    register_customer
)

router = Router()

# Middleware Sederhana Admin Check
@router.message.outer_middleware()
async def admin_guard_middleware(handler, event, data):
    user_id = event.from_user.id
    if not await is_admin(user_id):
        return await event.answer("⛔ Anda tidak memiliki akses ke fitur Admin Panel.")
    return await handler(event, data)

@router.message(Command("admin"))
async def show_admin_panel(message: types.Message):
    menu = (
        "👑 **PANEL ADMINISTRATOR**\n\n"
        "Perintah Admin:\n"
        "1. Regist Customer:\n`/reg_user <telegram_id> <username> <nama_lengkap>`\n"
        "2. Tambah Akun:\n`/add_acc <email>|<password_lama>`\n"
        "3. Regenerate Token:\n`/regen_token <email>`\n"
    )
    await message.answer(menu, parse_mode="Markdown")

@router.message(Command("reg_user"))
async def handle_reg_user(message: types.Message):
    # Format: /reg_user 12345678 johndoe John Doe
    args = message.text.split(maxsplit=3)
    if len(args) < 4:
        await message.answer("Format salah. Gunakan:\n`/reg_user <telegram_id> <username> <nama_lengkap>`")
        return
    
    tg_id, username, full_name = int(args[1]), args[2], args[3]
    await register_customer(tg_id, username, full_name, role='customer')
    await message.answer(f"✅ Berhasil mendaftarkan Customer ID `{tg_id}` (`@{username}`)")

@router.message(Command("add_acc"))
async def handle_add_acc(message: types.Message):
    # Format: /add_acc email@example.com|Pass123
    try:
        raw_data = message.text.split(maxsplit=1)[1]
        email, password = raw_data.split("|")
        
        token = await add_account_with_key(email.strip(), password.strip())
        await message.answer(
            f"✅ **Akun Berhasil Ditambahkan!**\n\n"
            f"Email: `{email.strip()}`\n"
            f"Kode Akses: `{token}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer(f"Format salah atau Gagal. Gunakan: `/add_acc email|password`\nError: {e}")

@router.message(Command("regen_token"))
async def handle_regen_token(message: types.Message):
    # Format: /regen_token email@example.com
    try:
        email = message.text.split(maxsplit=1)[1].strip()
        new_token = await regenerate_token(email)
        if new_token:
            await message.answer(f"🔑 Kode Akses Baru untuk `{email}`:\n`{new_token}`", parse_mode="Markdown")
        else:
            await message.answer("❌ Email akun tidak ditemukan di database.")
    except Exception:
        await message.answer("Format salah. Gunakan: `/regen_token email@example.com`")