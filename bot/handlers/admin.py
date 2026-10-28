import logging
from datetime import datetime, timedelta
from aiogram import Router, Bot
from aiogram.types import Message
from aiogram.filters import Command
from sqlalchemy import select, func

from core.config import settings
from core.database import async_session
from core.security import decrypt_session
from database.models import User, Subscription, SubscriptionStatus, PlanType, UserbotSession
from userbot.client_manager import client_manager

logger = logging.getLogger(__name__)
router = Router()

def is_admin(user_id: int) -> bool:
    """Foydalanuvchi admin ekanligini tekshirish."""
    return user_id in settings.ADMIN_IDS

@router.message(Command("vip"))
async def cmd_give_vip(message: Message, bot: Bot):
    """
    Foydalanuvchiga VIP berish buyrug'i:
    Foydalanish: /vip <user_id> <kunlar_soni>
    Masalan: /vip 123456789 7
    """
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 3:
        await message.answer("⚠️ <b>Foydalanish:</b> <code>/vip &lt;user_id&gt; &lt;kunlar&gt;</code>\nMasalan: <code>/vip 123456789 7</code>", parse_mode="HTML")
        return

    try:
        target_id = int(args[1])
        days = int(args[2])
    except ValueError:
        await message.answer("❌ ID va kunlar soni faqat raqam bo'lishi kerak!")
        return

    now = datetime.utcnow()
    expires = now + timedelta(days=days)

    async with async_session() as session:
        # Foydalanuvchini topish
        stmt = select(User).where(User.id == target_id)
        user = (await session.execute(stmt)).scalar_one_or_none()

        if not user:
            await message.answer(f"❌ <code>{target_id}</code> ID li foydalanuvchi avval botga kirmagan (bazada topilmadi).")
            return

        # Faol obunasi bo'lsa, muddatini uzaytirish, bo'lmasa yangi yaratish
        sub_stmt = select(Subscription).where(
            Subscription.user_id == target_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.expires_at > now
        )
        active_sub = (await session.execute(sub_stmt)).scalar_one_or_none()

        if active_sub:
            active_sub.expires_at = active_sub.expires_at + timedelta(days=days)
            expires = active_sub.expires_at
        else:
            plan = PlanType.VIP_1 if days == 1 else (PlanType.VIP_7 if days == 7 else PlanType.VIP_15)
            new_sub = Subscription(
                user_id=target_id,
                plan=plan,
                status=SubscriptionStatus.ACTIVE,
                starts_at=now,
                expires_at=expires
            )
            session.add(new_sub)

        # Agar foydalanuvchining ulangan userboti bo'lsa, uni darhol ishga tushirish
        sess_stmt = select(UserbotSession).where(
            UserbotSession.user_id == target_id,
            UserbotSession.is_active == True
        )
        ub_sess = (await session.execute(sess_stmt)).scalar_one_or_none()
        if ub_sess:
            try:
                decrypted = decrypt_session(ub_sess.encrypted_session)
                await client_manager.start_user(target_id, decrypted)
            except Exception as e:
                logger.error(f"Userbotni qayta yoqishda xato: {e}")

        await session.commit()

    # Adminga xabar
    await message.answer(
        f"✅ <b>Foydalanuvchi {target_id} ga {days} kunlik VIP berildi!</b>\n"
        f"📅 <b>Tugash vaqti:</b> <code>{expires.strftime('%Y-%m-%d %H:%M')}</code>",
        parse_mode="HTML"
    )

    # Foydalanuvchiga xushxabar yuborish
    try:
        await bot.send_message(
            chat_id=target_id,
            text=f"🎉 <b>Tabriklaymiz! Administrator tomonidan sizga {days} kunlik VIP obuna faollashtirildi!</b>\n\n"
                 f"📅 Tugash vaqti: <b>{expires.strftime('%Y-%m-%d %H:%M')}</b>\n"
                 "Userbotingiz xizmatlaridan to'liq foydalanishingiz mumkin!",
            parse_mode="HTML"
        )
    except Exception:
        pass

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Bot statistikasini ko'rish."""
    if not is_admin(message.from_user.id):
        return

    now = datetime.utcnow()
    async with async_session() as session:
        total_users = await session.scalar(select(func.count(User.id)))
        active_vips = await session.scalar(
            select(func.count(Subscription.id)).where(
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.expires_at > now
            )
        )
        active_userbots = len(client_manager.clients)

    text = (
        "📊 <b>Bot Statistikasi:</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{total_users} ta</b>\n"
        f"💎 Faol VIP obunachilar: <b>{active_vips} ta</b>\n"
        f"🟢 Hozir ishlayotgan Userbotlar: <b>{active_userbots} ta</b>"
    )
    await message.answer(text, parse_mode="HTML")
