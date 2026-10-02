import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config.settings import BOT_TOKEN
from bot.handlers import common, chpass, lookup_kick, admin
from database.db import init_db

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    # 1. Inisialisasi Database SQLite
    logger.info("🗄️ Menginisialisasi Database SQLite...")
    await init_db()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # 2. Registrasi Router Handlers
    dp.include_router(common.router)
    dp.include_router(admin.router)       # Router Admin Ditambahkan
    dp.include_router(chpass.router)
    dp.include_router(lookup_kick.router)

    logger.info("🤖 Bot Disney+ Management System Siap Dijalankan...")
    print("\n" + "=" * 50)
    print("🚀 BOT DISNEY+ BERHASIL BERJALAN & SIAP DIGUNAKAN")
    print("=" * 50 + "\n")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())