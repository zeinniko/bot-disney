import asyncio
from database.db import register_customer

async def make_me_admin():
    # GANTI DENGAN TELEGRAM ID, USERNAME, DAN NAMA ANDA
    MY_TELEGRAM_ID = 1201571822  # <--- Ubah dengan ID Anda dari perintah /myid
    MY_USERNAME = "@zeinniko"
    MY_NAME = "Niko"

    await register_customer(
        telegram_id=MY_TELEGRAM_ID,
        username=MY_USERNAME,
        full_name=MY_NAME,
        role="admin"  # Set Role sebagai Admin
    )
    print(f"✅ ID {MY_TELEGRAM_ID} ({MY_NAME}) Berhasil Didaftarkan sebagai ADMIN!")

if __name__ == "__main__":
    asyncio.run(make_me_admin())