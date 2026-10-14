import html
from aiogram import Router, types
from aiogram.filters import Command
from database.db import (
    is_admin, add_account, regenerate_token, register_member, get_accounts_list, get_members_list
)

router = Router()

# Middleware Admin Check
# @router.message.outer_middleware()
# async def admin_guard_middleware(handler, event, data):
#     user_id = event.from_user.id
#     if not await is_admin(user_id):
#         return await event.answer("⛔ Anda tidak memiliki akses ke fitur Admin Panel.")
#     return await handler(event, data)

@router.message(Command("admin"))
async def show_admin_panel(message: types.Message):
    menu = (
        "👑 **PANEL ADMINISTRATOR**\n\n"
        "Perintah Admin:\n"
        "1. Tambah Akun Produk:\n`/add_acc <email>|[password]`\n"
        "2. Registrasi Member/Langganan:\n`/reg_member <nama_customer>|<email_akun>|<YYYY-MM-DD>`\n"
        "3. Regenerate Token:\n`/regen_token <email_akun>|[YYYY-MM-DD]`\n"
        "4. Cek List Akun Produk:\n`/list_acc [halaman]`\n"
        "5. Cek List Member/Langganan:\n`/list_member [halaman]`\n"
    )
    await message.answer(menu, parse_mode="Markdown")
    
@router.message(Command("add_acc"))
async def handle_add_acc(message: types.Message):
    # Format: /add_acc email@example.com OR /add_acc email@example.com|Pass123
    try:
        raw_data = message.text.split(maxsplit=1)[1]
        parts = raw_data.split("|")
        email = parts[0].strip()
        password = parts[1].strip() if len(parts) > 1 else None
        
        account_id = await add_account(email, password)
        await message.answer(
            f"✅ **Akun Produk Berhasil Ditambahkan!**\n\n"
            f"ID: `{account_id}`\n"
            f"Email: `{email}`\n"
            f"Password: `{password or 'N/A (Null)'}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer(f"Format salah atau Gagal. Gunakan: `/add_acc email` atau `/add_acc email|password`\nError: {e}")

@router.message(Command("reg_member"))
async def handle_reg_member(message: types.Message):
    # Format: /reg_member Budi Santoso|dhshsh@gmail.com|2026-10-12
    try:
        raw_data = message.text.split(maxsplit=1)[1]
        parts = raw_data.split("|")
        
        if len(parts) < 3:
            await message.answer("Format salah. Gunakan:\n`/reg_member <nama_customer>|<email_akun>|<YYYY-MM-DD>`\n\nContoh:\n`/reg_member Budi|dhshsh@gmail.com|2026-10-12`")
            return
            
        customer_name = parts[0].strip()
        email = parts[1].strip()
        target_date = parts[2].strip()
        
        token, err = await register_member(customer_name, email, target_date)
        if err:
            await message.answer(f"❌ Gagal: {err}")
            return
            
        await message.answer(
            f"✅ **Member Berhasil Didaftarkan!**\n\n"
            f"Nama: `{customer_name}`\n"
            f"Akun: `{email}`\n"
            f"Valid Sampai: `{target_date}`\n"
            f"Token Akses: `{token}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer(f"Format salah. Gunakan:\n`/reg_member <nama_customer>|<email_akun>|<YYYY-MM-DD>`\nError: {e}")

@router.message(Command("regen_token"))
async def handle_regen_token(message: types.Message):
    # Format: /regen_token email@example.com atau /regen_token email@example.com|2026-10-12
    try:
        raw_data = message.text.split(maxsplit=1)[1]
        parts = raw_data.split("|")
        
        email = parts[0].strip()
        target_date = parts[1].strip() if len(parts) > 1 else None

        new_token = await regenerate_token(email, target_date)
        if new_token:
            resp_text = f"🔑 **Token Akses Baru** untuk `{email}`:\n`{new_token}`"
            if target_date:
                resp_text += f"\n\nTanggal Kadaluwarsa Diperbarui: `{target_date}`"
            await message.answer(resp_text, parse_mode="Markdown")
        else:
            await message.answer("❌ Email akun tidak ditemukan di database.")
    except Exception:
        await message.answer("Format salah. Gunakan:\n`/regen_token email@example.com` atau\n`/regen_token email@example.com|2026-10-12`")

@router.message(Command("list_acc"))
async def handle_list_acc(message: types.Message):
    """Menampilkan daftar akun produk yang terdaftar di database."""
    try:
        args = message.text.split()
        page = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
        limit = 15
        offset = (page - 1) * limit

        accounts = await get_accounts_list(limit=limit, offset=offset)

        if not accounts:
            await message.answer(f"📁 Belum ada akun produk di halaman {page}.")
            return

        text = f"📋 <b>DAFTAR AKUN PRODUK (Halaman {page}):</b>\n\n"
        for acc in accounts:
            acc_id = acc["id"]
            email = html.escape(acc["email"])
            pwd = html.escape(acc["current_password"]) if acc["current_password"] else "<i>(Null)</i>"
            token = f"<code>{acc['access_code']}</code>" if acc["access_code"] else "<i>Tanpa Token</i>"
            status = acc["status"].upper()

            text += (
                f"• <b>ID {acc_id}</b> | <code>{email}</code>\n"
                f"  └ Pass: <code>{pwd}</code> | Status: <b>{status}</b>\n"
                f"  └ Token: {token}\n\n"
            )

        text += f"<i>Petunjuk: Gunakan <code>/list_acc {page + 1}</code> untuk melihat halaman berikutnya.</i>"
        await message.answer(text, parse_mode="HTML")

    except Exception as e:
        await message.answer(f"❌ Gagal mengambil daftar akun: {e}")

@router.message(Command("list_member"))
async def handle_list_member(message: types.Message):
    """Menampilkan daftar member/langganan aktif."""
    try:
        args = message.text.split()
        page = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
        limit = 15
        offset = (page - 1) * limit

        members = await get_members_list(limit=limit, offset=offset)

        if not members:
            await message.answer(f"👥 Belum ada member terdaftar di halaman {page}.")
            return

        text = f"👥 <b>DAFTAR MEMBER / LANGGANAN (Halaman {page}):</b>\n\n"
        for m in members:
            name = html.escape(m["customer_name"])
            email = html.escape(m["email"])
            code = f"<code>{m['access_code']}</code>" if m["access_code"] else "<i>N/A</i>"
            exp = m["expired_at"] or "N/A"

            text += (
                f"• <b>{name}</b>\n"
                f"  └ Akun: <code>{email}</code>\n"
                f"  └ Token: {code}\n"
                f"  └ Expired: <code>{exp}</code>\n\n"
            )

        text += f"<i>Petunjuk: Gunakan <code>/list_member {page + 1}</code> untuk melihat halaman berikutnya.</i>"
        await message.answer(text, parse_mode="HTML")

    except Exception as e:
        await message.answer(f"❌ Gagal mengambil daftar member: {e}")