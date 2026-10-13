import asyncio
import logging
import uvicorn
from contextlib import asynccontextmanager

from app.bot.setup import bot, dp
from app.config import settings
from app.core.logger import setup_logger, logger
from app.db.models import init_db
from app.db.session import engine, async_session_factory
from app.services.store import store_service
from app.web.server import app

setup_logger()


async def background_stock_releaser():
    """Tugas latar belakang untuk me-release stok order yang tidak dibayar setiap 2 menit."""
    while True:
        try:
            await asyncio.sleep(120)
            async with async_session_factory() as session:
                await store_service.release_expired_orders(session)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error pada background stock releaser: {e}")


async def run_bot_polling():
    """Menjalankan Telegram bot long-polling."""
    logger.info("Memulai Telegram Bot polling...")
    try:
        # Hapus webhook telegram lama jika ada untuk menghindari konflik polling
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logger.info("Bot polling dihentikan.")
    except Exception as e:
        logger.error(f"Error fatal pada bot polling: {e}")


async def main():
    logger.info("=== DIGITAL STORE TELEGRAM BOT ===")
    logger.info(f"Port Webhook: {settings.PORT}")
    logger.info(f"Database: {'PostgreSQL Supabase/Railway' if 'postgres' in settings.DATABASE_URL else 'Local SQLite'}")

    # 1. Inisialisasi Database (Auto-create tables jika belum ada)
    try:
        await init_db(engine)
        logger.info("Inisialisasi tabel database berhasil.")
    except Exception as e:
        logger.critical(f"Gagal menghubungkan ke database: {e}")
        return

    # 2. Jalankan background tasks (Bot Polling & Expiry Releaser)
    bot_task = asyncio.create_task(run_bot_polling())
    releaser_task = asyncio.create_task(background_stock_releaser())

    # 3. Jalankan Webhook Server (Uvicorn) untuk menerima callback Mayar.id & Railway Health Check
    uvicorn_config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=settings.PORT,
        log_level="info",
        access_log=False
    )
    server = uvicorn.Server(uvicorn_config)

    try:
        await server.serve()
    finally:
        logger.info("Menghentikan service dan membersihkan resource...")
        bot_task.cancel()
        releaser_task.cancel()
        await asyncio.gather(bot_task, releaser_task, return_exceptions=True)
        await bot.session.close()
        await engine.dispose()
        logger.info("Service selesai dimatikan dengan aman.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Aplikasi dihentikan oleh user.")
