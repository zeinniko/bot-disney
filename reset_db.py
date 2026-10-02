import asyncio
import aiosqlite

DB_PATH = "bot_data.db"

async def check_and_reset_password(email: str, password_lama: str):
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Cek Data Saat Ini
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id, email, current_password FROM accounts WHERE LOWER(email) = LOWER(?)", (email.strip(),)) as cursor:
            row = await cursor.fetchone()
            if not row:
                print(f"❌ Email {email} tidak ditemukan di database.")
                return
            print(f"🔍 Data Saat Ini -> Email: {row['email']} | Password: {row['current_password']}")

        # 2. Kembalikan Password ke Password Lama
        await db.execute(
            "UPDATE accounts SET current_password = ?, updated_at = CURRENT_TIMESTAMP WHERE LOWER(email) = LOWER(?)",
            (password_lama, email.strip())
        )
        await db.commit()
        print(f"✅ Password untuk {email} berhasil dikembalikan ke: {password_lama}")

# Jalankan script (Ganti email & password sesuai akun tes kamu)
asyncio.run(check_and_reset_password("dizney196@pidercat.site", "it-supportX123"))