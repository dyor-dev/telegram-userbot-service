import os
import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.config import settings
from core.database import engine, Base
from database import models  # Modellar jadvallari yuklanishi uchun shart

# Handlerlar
from bot.handlers import start, auth, settings as user_settings, payment, admin
from userbot.client_manager import client_manager
from scheduler.checker import check_expired_subscriptions

# Loglarni sozlash
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("UserbotService")

async def init_db():
    """Ma'lumotlar bazasi jadvallarini avtomatik yaratish."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ PostgreSQL jadvallari muvaffaqiyatli tekshirildi va tayyorlandi!")

async def health_check(request):
    """Render.com uxlab qolmasligi uchun oddiy HTTP javob."""
    return web.Response(text="Bot va Userbot tizimi 100% faol holatda!", status=200)

async def start_web_server():
    """Render uchun kichik web-server (Health-check)."""
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
    logger.info("🚀 Tizim ishga tushirilmoqda...")

    # 1. Bazani sozlash
    await init_db()

    # 2. Aiogram 3 bot va Dispetcherni sozlash
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # Routerlarni ulash
    dp.include_router(admin.router)
    dp.include_router(start.router)
    dp.include_router(auth.router)
    dp.include_router(user_settings.router)
    dp.include_router(payment.router)

    # 3. Server qayta yonganda faol userbotlarni xotirada ishga tushirish
    asyncio.create_task(client_manager.start_all_active_users())

    # 4. Obunalarni har 60 soniyada tekshiruvchi Schedulerni yoqish
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_expired_subscriptions,
        trigger="interval",
        seconds=60,
        args=[bot]
    )
    scheduler.start()
    logger.info("⏰ Obuna nazoratchisi (Scheduler) faollashtirildi.")

    # 5. Render.com uxlab qolmasligi uchun veb-serverni orqa fonda yoqish
    await start_web_server()

    # 6. Botni ishga tushirish
    try:
        logger.info("🤖 Savdo boti xabarlarni qabul qilishga tayyor!")
        # Eskirgan kesh xabarlarni tozalab tashlash
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
