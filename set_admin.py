import asyncio
from database.db import upsert_user, init_db

async def make_me_admin():
    # Pastikan struktur database & tabel terbuat terlebih dahulu
    await init_db()

    # MY_TELEGRAM_ID = 1201571822
    MY_TELEGRAM_ID = 6338529400
    MY_USERNAME = "@zeinniko"
    MY_NAME = "Niko"

    await upsert_user(
        telegram_id=MY_TELEGRAM_ID,
        username=MY_USERNAME,
        full_name=MY_NAME,
        role="admin"
    )
    print(f"✅ ID {MY_TELEGRAM_ID} ({MY_NAME}) Berhasil Didaftarkan sebagai ADMIN!")

if __name__ == "__main__":
    asyncio.run(make_me_admin())