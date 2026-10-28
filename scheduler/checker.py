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
    """Muddati tugagan obunalarni tekshirish va userbotni to'xtatish."""
    now = datetime.utcnow()

    async with async_session() as session:
        # Muddati o'tgan, lekin statusi hali ACTIVE bo'lganlarni qidirish
        stmt = select(Subscription).where(
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.expires_at <= now
        )
        expired_subs = (await session.execute(stmt)).scalars().all()

        for sub in expired_subs:
            sub.status = SubscriptionStatus.EXPIRED
            user_id = sub.user_id

            # 1. Userbotni to'xtatish
            await client_manager.stop_user(user_id)
            logger.info(f"⌛ Obuna muddati tugadi: User {user_id}. Userbot to'xtatildi.")

            # 2. Foydalanuvchiga ogohlantirish xabari yuborish
            try:
                text = (
                    "⚠️ <b>VIP obuna muddatingiz tugadi!</b>\n\n"
                    "Userbotingiz xavfsiz to'xtatildi. Funksiyalarni qayta tiklash uchun "
                    "VIP obunangizni uzaytirishingiz mumkin:"
                )
                await bot.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=subscription_plans_kb(),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Ogohlantirish xabarini yuborib bo'lmadi ({user_id}): {e}")

        if expired_subs:
            await session.commit()
