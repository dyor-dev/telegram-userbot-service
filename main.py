import os
import asyncio
import logging

# Ultra-tezkor C-dvigatelini faollashtirish
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text

from core.config import settings
from core.database import engine, Base
from database import models

from bot.handlers import start, auth, settings as user_settings, payment, admin
from userbot.client_manager import client_manager
from scheduler.checker import check_expired_subscriptions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("UserbotService")

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS agreed_terms BOOLEAN DEFAULT FALSE;"))
        except Exception:
            pass
    logger.info("✅ PostgreSQL jadvallari muvaffaqiyatli tekshirildi va tayyorlandi!")

async def health_check(request):
    return web.Response(text="Bot va Userbot tizimi 100% faol holatda!", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    
    port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌐 Health-check serveri {port}-portda ishga tushirildi.")

async def main():
    logger.info("🚀 Tizim ishga tushirilmoqda (uvloop C-dvigateli bilan)...")

    await init_db()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    dp.include_router(admin.router)
    dp.include_router(start.router)
    dp.include_router(auth.router)
    dp.include_router(user_settings.router)
    dp.include_router(payment.router)

    asyncio.create_task(client_manager.start_all_active_users())

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_expired_subscriptions,
        trigger="interval",
        seconds=60,
        args=[bot]
    )
    scheduler.start()
    logger.info("⏰ Obuna nazoratchisi (Scheduler) faollashtirildi.")

    await start_web_server()

    try:
        logger.info("🤖 Savdo boti xabarlarni qabul qilishga tayyor!")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        logger.info("🛑 Tizim to'xtatilmoqda...")
        await client_manager.stop_all()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Tizim to'liq to'xtatildi.")
