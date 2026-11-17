import asyncio
import logging
import os
import socket
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import GetUpdates, TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import ErrorEvent
from aiohttp import ClientSession, ClientTimeout, TCPConnector

from bot.handlers import admin, auto_login_tv, chpass, common, lookup_kick
from config.settings import BOT_TOKEN
from database.db import close_db, init_db


# 1. Setup Production Logging (Hanya tampilkan ERROR di console & simpan ke file)
def setup_logging() -> logging.Logger:
    os.makedirs("logs", exist_ok=True)
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    formatter = logging.Formatter(log_format)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.ERROR)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        "logs/bot_error.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.ERROR)
    file_handler.setFormatter(formatter)

    logging.basicConfig(
        level=logging.ERROR,
        handlers=[console_handler, file_handler],
        force=True,
    )

    logging.getLogger("aiogram").setLevel(logging.ERROR)
    logging.getLogger("aiohttp").setLevel(logging.ERROR)
    logging.getLogger("asyncio").setLevel(logging.ERROR)

    return logging.getLogger(__name__)


logger = setup_logging()


# 2. Custom AiohttpSession (Force Close Socket + Auto-Retry Outgoing Request)
class CustomAiohttpSession(AiohttpSession):
    async def create_session(self) -> ClientSession:
        if self._should_reset_connector:
            await self.close()

        if self._session is None or self._session.closed:
            connector = TCPConnector(
                family=socket.AF_INET,
                ssl=True,
                force_close=True,  # Cegah WinError 64 akibat NAT router memutus keep-alive
                ttl_dns_cache=300,
            )
            self._session = ClientSession(
                connector=connector,
                timeout=ClientTimeout(total=35.0, connect=15.0),
                json_serialize=self.json_dumps,
            )
            self._should_reset_connector = False

        return self._session

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,
    ) -> TelegramType:
        # Polling (GetUpdates) ditangani langsung oleh retry loop Dispatcher
        if isinstance(method, GetUpdates):
            try:
                return await super().make_request(bot, method, timeout=timeout)
            except TelegramNetworkError:
                self._should_reset_connector = True
                raise

        # Auto-retry hingga 3x saat mengirim pesan/balasan jika jaringan putus sesaat
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                return await super().make_request(bot, method, timeout=timeout)
            except TelegramNetworkError:
                self._should_reset_connector = True
                if attempt == max_retries:
                    raise
                await asyncio.sleep(1.0 * attempt)


async def main():
    # 3. Inisialisasi Database SQLite
    await init_db()

    # 4. Inisialisasi Session, Bot, dan Dispatcher
    session = CustomAiohttpSession()
    bot = Bot(token=BOT_TOKEN, session=session)
    dp = Dispatcher(storage=MemoryStorage())

    # 5. Global Error Handler
    @dp.errors()
    async def global_error_handler(event: ErrorEvent):
        exc = event.exception

        if isinstance(exc, TelegramBadRequest):
            ignored_messages = (
                "query is too old",
                "message is not modified",
                "message to delete not found",
                "message can't be deleted",
            )
            if any(msg in str(exc).lower() for msg in ignored_messages):
                return True

        if isinstance(exc, TelegramForbiddenError):
            return True

        # Cetak error jaringan dalam 1 baris ringkas tanpa spam traceback panjang
        if isinstance(exc, TelegramNetworkError):
            logger.error(f"Network error pada update {event.update.update_id}: {exc}")
            return True

        logger.error(
            f"Unhandled error pada update {event.update.update_id}: {exc}",
            exc_info=exc,
        )
        return True

    # 6. Hook Graceful Shutdown
    @dp.shutdown()
    async def on_shutdown():
        try:
            await close_db()
        except Exception as e:
            logger.error(f"Gagal menutup database SQLite: {e}")

        await bot.session.close()

    # 7. Registrasi Router Handlers
    dp.include_router(common.router)
    dp.include_router(admin.router)
    dp.include_router(chpass.router)
    dp.include_router(lookup_kick.router)
    dp.include_router(auto_login_tv.router)

    # 8. Bersihkan Webhook & Antrean Update Lama
    await bot.delete_webhook(drop_pending_updates=True)

    print("=" * 50)
    print("🚀 BOT DISNEY+ PRODUCTION MODE AKTIF")
    print("=" * 50)

    try:
        await dp.start_polling(
            bot,
            polling_timeout=15,
            allowed_updates=dp.resolve_used_update_types(),
        )
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Bot dihentikan dengan aman.")