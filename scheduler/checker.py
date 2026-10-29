import logging
from datetime import datetime
from aiogram import Bot
from sqlalchemy import select

from core.database import async_session
from database.models import Subscription, SubscriptionStatus
from userbot.client_manager import client_manager
from bot.keyboards.inline import subscription_plans_kb

logger = logging.getLogger(__name__)

async def check_expired_subscriptions(bot: Bot):
    """Muddati tugagan obunalarni va 12h/1h qolganlarni tekshirish."""
    now = datetime.utcnow()

    # 1. Chiqarib yuborilgan faol seanslarni tekshirish
    try:
        await client_manager.verify_active_sessions(bot)
    except Exception as e:
        logger.error(f"Seanslarni tekshirishda xatolik: {e}")

    # 2. Obunalar holatini tekshirish
    async with async_session() as session:
        # Barcha faol obunalarni olish
        stmt = select(Subscription).where(Subscription.status == SubscriptionStatus.ACTIVE)
        active_subs = (await session.execute(stmt)).scalars().all()

        for sub in active_subs:
            user_id = sub.user_id

            # A) MUDDATI TO'LIQ TUGAGAN BO'LSA
            if sub.expires_at <= now:
                sub.status = SubscriptionStatus.EXPIRED
                await client_manager.stop_user(user_id)
                logger.info(f"⌛ Obuna muddati tugadi: User {user_id}. Userbot to'xtatildi.")

                try:
                    text = (
                        "⚠️ <b>VIP obuna muddatingiz tugadi!</b>\n\n"
                        "Userbotingiz xavfsiz to'xtatildi. Avto-komment va maxsus buyruqlarni qayta "
                        "tiklash uchun VIP obunangizni uzaytirishingiz mumkin:"
                    )
                    await bot.send_message(
                        chat_id=user_id,
                        text=text,
                        reply_markup=subscription_plans_kb(),
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
                continue

            # B) TUGASHIGA QOLGAN VAQTNI HISOBLASH
            delta = sub.expires_at - now
            rem_seconds = delta.total_seconds()
            rem_hours = int(rem_seconds // 3600)
            rem_mins = int((rem_seconds % 3600) // 60)

            # C) 1 SOAT OLDIN OGOHLANTIRISH (<= 1 soat va hali ogohlantirilmagan bo'lsa)
            if rem_seconds <= 3600 and not sub.warned_1h:
                sub.warned_1h = True
                sub.warned_12h = True  # 12 soatlikni ham yopamiz
                try:
                    text = (
                        f"🚨 <b>DIQQAT! VIP obunangiz tugashiga {rem_mins} daqiqa qoldi!</b>\n\n"
                        "Tez orada userbotingiz to'xtatiladi. Kanallarda birinchi bo'lib izoh yozish "
                        "va maxfiy funksiyalar uzilib qolmasligi uchun hoziroq obunangizni uzaytirib oling 👇"
                    )
                    await bot.send_message(
                        chat_id=user_id,
                        text=text,
                        reply_markup=subscription_plans_kb(),
                        parse_mode="HTML"
                    )
                    logger.info(f"1-soatlik ogohlantirish yuborildi: User {user_id}")
                except Exception:
                    pass

            # D) 12 SOAT OLDIN OGOHLANTIRISH (<= 12 soat va hali ogohlantirilmagan bo'lsa)
            elif rem_seconds <= 43200 and not sub.warned_12h:
                sub.warned_12h = True
                try:
                    text = (
                        f"⏳ <b>VIP obuna muddatingiz tugamoqda!</b>\n\n"
                        f"Obunangiz tugashiga taxminan <b>{rem_hours} soat {rem_mins} daqiqa</b> qoldi.\n"
                        f"📅 Tugash vaqti: <code>{sub.expires_at.strftime('%Y-%m-%d %H:%M')}</code>\n\n"
                        "Userbotingiz to'xtab qolmasligi uchun obunani oldindan uzaytirib olishingiz mumkin 👇"
                    )
                    await bot.send_message(
                        chat_id=user_id,
                        text=text,
                        reply_markup=subscription_plans_kb(),
                        parse_mode="HTML"
                    )
                    logger.info(f"12-soatlik ogohlantirish yuborildi: User {user_id}")
                except Exception:
                    pass

        await session.commit()
