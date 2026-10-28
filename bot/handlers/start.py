from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.database import async_session
from database.models import User, UserbotSession, Subscription, PlanType, SubscriptionStatus, UserbotSettings
from bot.keyboards.inline import main_menu_kb, subscription_plans_kb

router = Router()

async def get_or_create_user(session, tg_user):
    """Foydalanuvchini bazadan olish yoki yangi ochish."""
    stmt = select(User).options(
        selectinload(User.session),
        selectinload(User.subscriptions),
        selectinload(User.settings)
    ).where(User.id == tg_user.id)
    
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name or "Foydalanuvchi"
        )
        # Birlamchi sozlamalarni biriktirish
        user_settings = UserbotSettings(user_id=tg_user.id)
        session.add(user)
        session.add(user_settings)
        await session.commit()
        await session.refresh(user)

    return user

def check_user_status(user: User):
    """Foydalanuvchining sessiya va obuna holatini aniqlash."""
    has_session = bool(user.session and user.session.is_active)
    is_vip = False
    sub_info = "Obuna yo'q"

    # Faol obunani tekshirish
    now = datetime.utcnow()
    for sub in (user.subscriptions or []):
        if sub.status == SubscriptionStatus.ACTIVE and sub.expires_at > now:
            is_vip = True
            qolgan_kun = (sub.expires_at - now).days
            qolgan_soat = ((sub.expires_at - now).seconds) // 3600
            sub_info = f"Faol ({sub.plan.value.upper()}) — {qolgan_kun} kun {qolgan_soat} soat qoldi"
            break

    return has_session, is_vip, sub_info

@router.message(CommandStart())
async def cmd_start(message: Message):
    async with async_session() as session:
        user = await get_or_create_user(session, message.from_user)
        has_session, is_vip, sub_info = check_user_status(user)

    text = (
        f"👋 <b>Assalomu alaykum, {message.from_user.full_name}!</b>\n\n"
        f"🤖 <b>Telegram Userbot boshqaruv xizmatiga xush kelibsiz.</b>\n\n"
        f"📊 <b>Sizning holatingiz:</b>\n"
        f"• Akkaunt: <code>{message.from_user.id}</code>\n"
        f"• Userbot: {'🟢 Ulangan' if has_session else '🔴 Ulanmagan'}\n"
        f"• Obuna: <b>{sub_info}</b>\n\n"
        f"Kerakli bo'limni tanlang 👇"
    )
    await message.answer(text, reply_markup=main_menu_kb(has_session, is_vip), parse_mode="HTML")

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    async with async_session() as session:
        user = await get_or_create_user(session, callback.from_user)
        has_session, is_vip, sub_info = check_user_status(user)

    text = (
        f"🏠 <b>Bosh menyu</b>\n\n"
        f"• Userbot: {'🟢 Ulangan' if has_session else '🔴 Ulanmagan'}\n"
        f"• Obuna: <b>{sub_info}</b>\n\n"
        f"Quyidagi menyulardan birini tanlang:"
    )
    await callback.message.edit_text(text, reply_markup=main_menu_kb(has_session, is_vip), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "claim_trial")
async def claim_trial_handler(callback: CallbackQuery):
    """Bepul trial (1 kun) berish mexanizmi."""
    async with async_session() as session:
        user = await get_or_create_user(session, callback.from_user)

        if user.has_used_trial:
            await callback.answer("⚠️ Siz avval bepul sinov (Trial) imkoniyatidan foydalangansiz!", show_alert=True)
            return

        # 1 kunlik trial faollashtirish
        now = datetime.utcnow()
        expires = now + timedelta(days=1)

        user.has_used_trial = True
        user.trial_started_at = now

        trial_sub = Subscription(
            user_id=user.id,
            plan=PlanType.TRIAL,
            status=SubscriptionStatus.ACTIVE,
            starts_at=now,
            expires_at=expires
        )
        session.add(trial_sub)
        await session.commit()

    await callback.message.answer(
        "🎉 <b>Tabriklaymiz! 1 kunlik bepul VIP sinov muddati faollashtirildi.</b>\n\n"
        "Endi o'z hisobingizga userbotni ulashingiz mumkin!",
        parse_mode="HTML"
    )
    await back_to_main(callback)

@router.callback_query(F.data == "commands_guide")
async def commands_guide_handler(callback: CallbackQuery):
    text = (
        "📖 <b>Userbot Maxsus Buyruqlari Qo'llanmasi:</b>\n\n"
        "Userbotingiz ulangandan so'ng, istalgan chatda quyidagi buyruqlarni yuborishingiz mumkin:\n\n"
        "🔹 <code>.ping</code> — Botning javob berish tezligi va server kechikishini tekshirish.\n"
        "🔹 <code>.ok</code> — O'z-o‘zidan yo‘qoladigan (1 martalik ko‘rish uchun yuborilgan) rasm yoki videolarga reply (javob) qilib yozsangiz, bot uni shaxsiy «Saqlangan xabarlar»ingizga o‘chmas qilib saqlab beradi.\n"
        "🔹 <code>.info</code> — Telegram hisobingiz va faol userbot statistikasi.\n\n"
        "<i>Eslatma: Buyruqlar oldida nuqta (.) bo'lishi shart!</i>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=main_menu_kb(True, True),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "buy_vip")
async def buy_vip_handler(callback: CallbackQuery):
    text = (
        "💎 <b>VIP Obuna Tariflari</b>\n\n"
        "VIP maqomiga ega bo'lish orqali quyidagi imkoniyatlarni qo'lga kiritasiz:\n"
        "• 24/7 uzluksiz userbot ishlashi\n"
        "• O'z-o'zidan o'chuvchi mediani avto-saqlash\n"
        "• Guruh va kanallarda avto-komment qoldirish\n"
        "• Anonim Stories ko'rish va yuklash\n\n"
        "O'zingizga ma'qul tarifni tanlang (To'lov Telegram Stars orqali amalga oshiriladi):"
    )
    await callback.message.edit_text(text, reply_markup=subscription_plans_kb(), parse_mode="HTML")
    await callback.answer()
