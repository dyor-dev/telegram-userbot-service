from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from sqlalchemy import select

from core.database import async_session
from database.models import User, UserbotSession, Subscription, PlanType, SubscriptionStatus, UserbotSettings
from bot.keyboards.inline import main_menu_kb, subscription_plans_kb

router = Router()

def format_plan_title(plan: PlanType) -> str:
    if plan == PlanType.VIP_1:
        return "💎 VIP (1 kunlik)"
    elif plan == PlanType.VIP_7:
        return "💎 VIP (7 kunlik)"
    elif plan == PlanType.VIP_15:
        return "💎 VIP (15 kunlik)"
    elif plan == PlanType.CUSTOM:
        return "💎 VIP Obuna"
    elif plan == PlanType.TRIAL:
        return "🎁 Bepul Trial"
    return "VIP Obuna"

@router.message(CommandStart())
async def cmd_start(message: Message):
    tg_user = message.from_user
    now = datetime.utcnow()

    # Baza bilan bitta yagona optimallashgan tranzaksiyada ishlash
    async with async_session() as session:
        # Foydalanuvchini tekshirish
        user_stmt = select(User).where(User.id == tg_user.id)
        user = (await session.execute(user_stmt)).scalar_one_or_none()

        if not user:
            # Yangi foydalanuvchini tezkor saqlash
            user = User(
                id=tg_user.id,
                username=tg_user.username,
                full_name=tg_user.full_name or "Foydalanuvchi"
            )
            session.add(user)
            session.add(UserbotSettings(user_id=tg_user.id))
            await session.commit()
            
            # Yangi foydalanuvchida hali sessiya va obuna yo'qligi aniq (ortiqcha so'rov shart emas!)
            has_session = False
            is_vip = False
            sub_info = "Obuna yo'q"
        else:
            # Mavjud foydalanuvchi uchun sessiya va faol obunani tezkor tekshirish
            sess_stmt = select(UserbotSession.is_active).where(UserbotSession.user_id == tg_user.id)
            has_session = bool((await session.execute(sess_stmt)).scalar_one_or_none())

            sub_stmt = select(Subscription).where(
                Subscription.user_id == tg_user.id,
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.expires_at > now
            ).order_by(Subscription.expires_at.desc())
            active_sub = (await session.execute(sub_stmt)).scalars().first()

            if active_sub:
                is_vip = True
                delta = active_sub.expires_at - now
                qolgan_kun = delta.days
                qolgan_soat = delta.seconds // 3600
                plan_name = format_plan_title(active_sub.plan)
                sub_info = f"Faol ({plan_name}) — {qolgan_kun} kun {qolgan_soat} soat qoldi"
            else:
                is_vip = False
                sub_info = "Obuna yo'q"

    text = (
        f"👋 <b>Assalomu alaykum, {tg_user.full_name}!</b>\n\n"
        f"🤖 <b>Telegram Userbot boshqaruv xizmatiga xush kelibsiz.</b>\n\n"
        f"📊 <b>Sizning holatingiz:</b>\n"
        f"• Akkaunt: <code>{tg_user.id}</code>\n"
        f"• Userbot: {'🟢 Ulangan' if has_session else '🔴 Ulanmagan'}\n"
        f"• Obuna: <b>{sub_info}</b>\n\n"
        f"Kerakli bo'limni tanlang 👇"
    )
    await message.answer(text, reply_markup=main_menu_kb(has_session, is_vip), parse_mode="HTML")

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    user_id = callback.from_user.id
    now = datetime.utcnow()

    async with async_session() as session:
        sess_stmt = select(UserbotSession.is_active).where(UserbotSession.user_id == user_id)
        has_session = bool((await session.execute(sess_stmt)).scalar_one_or_none())

        sub_stmt = select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.expires_at > now
        ).order_by(Subscription.expires_at.desc())
        active_sub = (await session.execute(sub_stmt)).scalars().first()

        if active_sub:
            is_vip = True
            delta = active_sub.expires_at - now
            sub_info = f"Faol ({format_plan_title(active_sub.plan)}) — {delta.days} kun {delta.seconds // 3600} soat qoldi"
        else:
            is_vip = False
            sub_info = "Obuna yo'q"

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
    user_id = callback.from_user.id
    async with async_session() as session:
        stmt = select(User).where(User.id == user_id)
        user = (await session.execute(stmt)).scalar_one_or_none()

        if user and user.has_used_trial:
            await callback.answer("⚠️ Siz avval bepul sinov (Trial) imkoniyatidan foydalangansiz!", show_alert=True)
            return

    # Userbot ulanishi bilan 24 soat avtomatik yoqilishi haqida tushuntirish
    text = (
        "🎁 <b>1 kunlik Bepul Sinov (Trial)</b>\n\n"
        "Sinov muddati zoe ketmasligi uchun, 24 soatlik bepul vaqt "
        "<b>akkauntingizga userbot muvaffaqiyatli ulangan lahzadan boshlab</b> hisoblanadi!\n\n"
        "Userbotingizni hoziroq ulash uchun pastdagi tugmani bosing 👇"
    )
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="🔌 Userbotni ulash", callback_data="connect_userbot")
    b.button(text="⬅️ Orqaga", callback_data="back_to_main")
    b.adjust(1, 1)

    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "commands_guide")
async def commands_guide_handler(callback: CallbackQuery):
    text = (
        "📖 <b>Userbot Maxsus Buyruqlari Qo'llanmasi:</b>\n\n"
        "Userbotingiz ulangandan so'ng, istalgan chatda quyidagi buyruqlarni yuborishingiz mumkin:\n\n"
        "🔹 <code>.ping</code> — Botning javob berish tezligi va server kechikishini tekshirish.\n"
        "🔹 <code>.ok</code> — Bir martalik (o‘z-o‘zidan o‘chuvchi) rasm yoki videoga reply qilib yozsangiz, uni «Saqlangan xabarlar»ingizga o‘chmas qilib saqlab beradi.\n"
        "🔹 <code>.dw @username</code> — Belgilangan foydalanuvchining barcha faol hikoyalarini (Stories) <b>anonim tarzda</b> yuklab «Saqlangan xabarlar»ingizga tashlab beradi.\n"
        "🔹 <code>.info</code> — Telegram hisobingiz va faol userbot statistikasi.\n\n"
        "<i>Eslatma: Buyruqlar oldida nuqta (.) bo'lishi shart!</i>"
    )
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ Bosh menyu", callback_data="back_to_main")

    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "buy_vip")
async def buy_vip_handler(callback: CallbackQuery):
    text = (
        "💎 <b>VIP Obuna Tariflari</b>\n\n"
        "VIP maqomiga ega bo'lish orqali quyidagi imkoniyatlarni qo'lga kiritasiz:\n"
        "• 24/7 uzluksiz userbot ishlashi\n"
        "• O'z-o'zidan o'chuvchi mediani avto-saqlash (<code>.ok</code>)\n"
        "• Ochiq hikoyalarni anonim yuklab olish (<code>.dw @username</code>)\n"
        "• Guruh va kanallarda chaqmoqdek tez avto-komment qoldirish\n\n"
        "O'zingizga ma'qul tarifni tanlang 👇"
    )
    await callback.message.edit_text(text
