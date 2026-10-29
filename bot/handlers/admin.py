import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Router, Bot, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy import select, func

from core.config import settings
from core.database import async_session
from core.security import decrypt_session
from database.models import User, Subscription, SubscriptionStatus, PlanType, UserbotSession
from userbot.client_manager import client_manager

logger = logging.getLogger(__name__)
router = Router()

def is_admin(user_id: int) -> bool:
    return user_id in settings.ADMIN_IDS

# 1. ADMIN BUYRUQLARI QO'LLANMASI
@router.message(Command("admin"))
async def cmd_admin_help(message: Message):
    if not is_admin(message.from_user.id):
        return

    text = (
        "👑 <b>Administrator Boshqaruv Paneli:</b>\n\n"
        "🔹 <code>/vip &lt;id&gt; &lt;kun&gt;</code> — Foydalanuvchiga VIP muddatini berish yoki uzaytirish.\n"
        "🔹 <code>/unvip &lt;id&gt;</code> — Foydalanuvchidan VIP obunani olib tashlash va userbotni to'xtatish.\n"
        "🔹 <code>/user &lt;id&gt;</code> — Foydalanuvchi ma'lumotlari (dosye)ni ko'rish.\n"
        "🔹 <code>/stats</code> — Bot statistikasi (foydalanuvchilar, faol userbotlar).\n"
        "🔹 <code>/broadcast &lt;matn&gt;</code> — Barcha foydalanuvchilarga ommaviy xabar/reklama yuborish (Xabarga reply qilib yuborsangiz ham bo'ladi).\n"
    )
    await message.answer(text, parse_mode="HTML")

# 2. FOYDALANUVCHIGA VIP BERISH
@router.message(Command("vip"))
async def cmd_give_vip(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 3:
        await message.answer("⚠️ <b>Foydalanish:</b> <code>/vip &lt;user_id&gt; &lt;kunlar&gt;</code>\nMasalan: <code>/vip 123456789 15</code>", parse_mode="HTML")
        return

    try:
        target_id = int(args[1])
        days = int(args[2])
    except ValueError:
        await message.answer("❌ ID va kunlar soni faqat raqam bo'lishi kerak!")
        return

    now = datetime.utcnow()
    expires = now + timedelta(days=days)

    if days == 1:
        target_plan = PlanType.VIP_1
        plan_title = "1 kunlik VIP"
    elif days == 7:
        target_plan = PlanType.VIP_7
        plan_title = "7 kunlik VIP"
    elif days == 15:
        target_plan = PlanType.VIP_15
        plan_title = "15 kunlik VIP"
    else:
        target_plan = PlanType.CUSTOM
        plan_title = f"{days} kunlik VIP"

    async with async_session() as session:
        stmt = select(User).where(User.id == target_id)
        user = (await session.execute(stmt)).scalar_one_or_none()

        if not user:
            await message.answer(f"❌ <code>{target_id}</code> ID li foydalanuvchi botda ro'yxatdan o'tmagan.")
            return

        sub_stmt = select(Subscription).where(
            Subscription.user_id == target_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.expires_at > now
        )
        active_sub = (await session.execute(sub_stmt)).scalar_one_or_none()

        if active_sub:
            active_sub.plan = target_plan
            active_sub.expires_at = active_sub.expires_at + timedelta(days=days)
            active_sub.warned_12h = False
            active_sub.warned_1h = False
            expires = active_sub.expires_at
        else:
            new_sub = Subscription(
                user_id=target_id,
                plan=target_plan,
                status=SubscriptionStatus.ACTIVE,
                starts_at=now,
                expires_at=expires
            )
            session.add(new_sub)

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
                logger.error(f"Userbotni yoqishda xatolik: {e}")

        await session.commit()

    await message.answer(
        f"✅ <b>Foydalanuvchi {target_id} ga {plan_title} berildi!</b>\n"
        f"📅 <b>Yangi tugash vaqti:</b> <code>{expires.strftime('%Y-%m-%d %H:%M')}</code>",
        parse_mode="HTML"
    )

    try:
        await bot.send_message(
            chat_id=target_id,
            text=f"🎉 <b>Tabriklaymiz! Administrator tomonidan sizga {plan_title} obunasi faollashtirildi!</b>\n\n"
                 f"📅 Tugash vaqti: <b>{expires.strftime('%Y-%m-%d %H:%M')}</b>\n"
                 "Userbot xizmatlaridan bemalol foydalanishingiz mumkin!",
            parse_mode="HTML"
        )
    except Exception:
        pass

# 3. VIP OBUNANI BEKOR QILISH (/unvip)
@router.message(Command("unvip"))
async def cmd_revoke_vip(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("⚠️ <b>Foydalanish:</b> <code>/unvip &lt;user_id&gt;</code>", parse_mode="HTML")
        return

    try:
        target_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID faqat raqam bo'lishi kerak!")
        return

    async with async_session() as session:
        sub_stmt = select(Subscription).where(
            Subscription.user_id == target_id,
            Subscription.status == SubscriptionStatus.ACTIVE
        )
        subs = (await session.execute(sub_stmt)).scalars().all()

        if not subs:
            await message.answer(f"ℹ️ <code>{target_id}</code> ID li foydalanuvchida faol VIP obuna topilmadi.")
            return

        for s in subs:
            s.status = SubscriptionStatus.CANCELLED

        await session.commit()

    # Userbotni to'xtatish
    await client_manager.stop_user(target_id)

    await message.answer(f"🛑 <b>Foydalanuvchi {target_id} ning VIP obunasi bekor qilindi va userboti to'xtatildi!</b>", parse_mode="HTML")

    try:
        await bot.send_message(
            chat_id=target_id,
            text="⚠️ <b>Sizning VIP obunangiz administrator tomonidan bekor qilindi.</b> Userbot to'xtatildi.",
            parse_mode="HTML"
        )
    except Exception:
        pass

# 4. FOYDALANUVCHI HAQIDA MA'LUMOT (/user)
@router.message(Command("user"))
async def cmd_user_info(message: Message):
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("⚠️ <b>Foydalanish:</b> <code>/user &lt;user_id&gt;</code>", parse_mode="HTML")
        return

    try:
        target_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID faqat raqam bo'lishi kerak!")
        return

    now = datetime.utcnow()
    async with async_session() as session:
        stmt = select(User).where(User.id == target_id)
        user = (await session.execute(stmt)).scalar_one_or_none()

        if not user:
            await message.answer("❌ Foydalanuvchi bazada topilmadi.")
            return

        sub_stmt = select(Subscription).where(
            Subscription.user_id == target_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.expires_at > now
        ).order_by(Subscription.expires_at.desc())
        active_sub = (await session.execute(sub_stmt)).scalars().first()

        sess_stmt = select(UserbotSession).where(UserbotSession.user_id == target_id)
        ub_sess = (await session.execute(sess_stmt)).scalar_one_or_none()

    sub_status = f"🟢 Faol ({active_sub.expires_at.strftime('%Y-%m-%d %H:%M')} gacha)" if active_sub else "🔴 Obuna yo'q"
    sess_status = f"🟢 Ulangan ({ub_sess.phone_number})" if (ub_sess and ub_sess.is_active) else "🔴 Ulanmagan"

    text = (
        f"👤 <b>Foydalanuvchi ma'lumotlari:</b>\n\n"
        f"• ID: <code>{user.id}</code>\n"
        f"• Ism: <b>{user.full_name}</b>\n"
        f"• Username: @{user.username or 'yo\'q'}\n"
        f"• Shartlarga rozilik: {'✅ Berilgan' if user.agreed_terms else '❌ Bermagan'}\n"
        f"• Trial ishlatganmi: {'Ha' if user.has_used_trial else 'Yo\'q'}\n"
        f"• Taklif qilgan do'stlari: <b>{user.referral_count or 0} ta</b>\n"
        f"• Userbot: <b>{sess_status}</b>\n"
        f"• Obuna: <b>{sub_status}</b>\n"
        f"• Ro'yxatdan o'tgan: <code>{user.created_at.strftime('%Y-%m-%d')}</code>"
    )
    await message.answer(text, parse_mode="HTML")

# 5. STATISTIKA (/stats)
@router.message(Command("stats"))
async def cmd_stats(message: Message):
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

# 6. OMMAVIY XABAR YUBORISH (/broadcast)
@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return

    # Reply qilingan xabar yoki buyruqdan keyingi matnni aniqlash
    broadcast_msg = message.reply_to_message
    text_to_send = message.text.replace("/broadcast", "").strip()

    if not broadcast_msg and not text_to_send:
        await message.answer(
            "⚠️ <b>Foydalanish:</b>\n"
            "1. <code>/broadcast &lt;xabar matni&gt;</code>\n"
            "2. Yoki biror xabar/rasmga <b>reply (javob)</b> qilib <code>/broadcast</code> deb yozing.",
            parse_mode="HTML"
        )
        return

    async with async_session() as session:
        stmt = select(User.id)
        user_ids = (await session.execute(stmt)).scalars().all()

    total = len(user_ids)
    if total == 0:
        await message.answer("Bazada birorta ham foydalanuvchi yo'q.")
        return

    status_msg = await message.answer(f"⏳ Xabar {total} ta foydalanuvchiga yuborilmoqda...")

    success = 0
    blocked = 0

    for uid in user_ids:
        try:
            if broadcast_msg:
                await broadcast_msg.copy_to(chat_id=uid)
            else:
                await bot.send_message(chat_id=uid, text=text_to_send, parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.04)  # Telegram limitiga tushmaslik uchun (25 xabar/sek)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                if broadcast_msg:
                    await broadcast_msg.copy_to(chat_id=uid)
                else:
                    await bot.send_message(chat_id=uid, text=text_to_send, parse_mode="HTML")
                success += 1
            except Exception:
                blocked += 1
        except TelegramForbiddenError:
            blocked += 1
        except Exception:
            blocked += 1

    report_text = (
        "📢 <b>Xabar tarqatish yakunlandi!</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{total} ta</b>\n"
        f"✅ Muvaffaqiyatli yetkazildi: <b>{success} ta</b>\n"
        f"🚫 Yetkazilmadi (Botni bloklagan): <b>{blocked} ta</b>"
    )
    await status_msg.edit_text(report_text, parse_mode="HTML")
