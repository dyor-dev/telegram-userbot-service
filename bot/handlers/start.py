from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from core.database import async_session
from database.models import User, UserbotSession, Subscription, PlanType, SubscriptionStatus, UserbotSettings
from bot.keyboards.inline import main_menu_kb, subscription_plans_kb, feedback_kb

router = Router()

PRIVACY_POLICY_TEXT = (
    "📄 <b>Foydalanish shartlari va Maxfiylik siyosati</b>\n\n"
    "🔐 <b>Xush kelibsiz! Xizmatimizdan foydalanishdan oldin quyidagi shartlar bilan tanishib chiqing:</b>\n\n"
    "<b>1. Ma’lumotlar xavfsizligi va shifrlash:</b>\n"
    "• Bot foydalanuvchining shaxsiy yozishmalarini o‘qimaydi va begonalarga uzatmaydi.\n"
    "• Akkauntingizni ulashda hosil bo‘ladigan sessiya ma’lumotlar bazasida <b>AES (Fernet)</b> xalqaro shifrlash standarti orqali kuchli shifrlangan holatda saqlanadi.\n"
    "• Telefon raqami va tasdiqlash kodlari faqatgina Telegram rasmiy MTProto API orqali akkauntni ulash uchun ishlatiladi.\n\n"
    "<b>2. Foydalanuvchi javobgarligi:</b>\n"
    "• Userbot sizning shaxsiy Telegram hisobingiz nomidan buyruqlarni (avto-komment, media saqlash, stories ko‘rish) bajaradi.\n"
    "• Userbot orqali yoziladigan izohlar (avto-kommentlar matni), qilinadigan harakatlar va Telegram qoidalariga rioya qilish uchun <b>to‘liq javobgarlik foydalanuvchining o‘z zimmasidadir</b>.\n"
    "• Xizmatdan spam tarqatish, firibgarlik, haqorat yoki qonunga zid maqsadlarda foydalanish qat’iyan taqiqlanadi.\n\n"
    "<b>3. Bepul Trial va VIP obuna shartlari:</b>\n"
    "• Bepul sinov muddati (Trial) har bir foydalanuvchiga faqat 1 marta beriladi va uni qayta suiiste’mol qilish taqiqlanadi.\n"
    "• Obuna muddati tugagach, barcha avtomatik funksiyalar to‘xtatiladi. Foydalanuvchi istalgan vaqtda o‘z userbotini bot orqali uzib tashlash huquqiga ega.\n\n"
    "<b>4. Rozilik bildirish:</b>\n"
    "Quyidagi <b>«✅ Roziman va qabul qilaman»</b> tugmasini bosish orqali siz yuqoridagi barcha shartlarga, ma’lumotlaringiz xavfsiz saqlanishiga va xizmatdan faqat o‘z javobgarligingiz ostida foydalanishga to‘liq rozilik bildirasiz."
)

def privacy_policy_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Roziman va qabul qilaman", callback_data="accept_privacy_policy")
    builder.button(text="❌ Rad etish", callback_data="decline_privacy_policy")
    builder.adjust(1, 1)
    return builder.as_markup()

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

async def render_main_menu(bot_message_or_callback, tg_user, edit: bool = False):
    now = datetime.utcnow()
    async with async_session() as session:
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
            sub_info = f"Faol ({format_plan_title(active_sub.plan)}) — {delta.days} kun {delta.seconds // 3600} soat qoldi"
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

    if edit:
        await bot_message_or_callback.message.edit_text(text, reply_markup=main_menu_kb(has_session, is_vip), parse_mode="HTML")
    else:
        await bot_message_or_callback.answer(text, reply_markup=main_menu_kb(has_session, is_vip), parse_mode="HTML")

@router.message(CommandStart())
async def cmd_start(message: Message):
    tg_user = message.from_user

    async with async_session() as session:
        user_stmt = select(User).where(User.id == tg_user.id)
        user = (await session.execute(user_stmt)).scalar_one_or_none()

        if not user:
            user = User(
                id=tg_user.id,
                username=tg_user.username,
                full_name=tg_user.full_name or "Foydalanuvchi",
                agreed_terms=False
            )
            session.add(user)
            session.add(UserbotSettings(user_id=tg_user.id))
            await session.commit()
            agreed = False
        else:
            agreed = user.agreed_terms

    if not agreed:
        await message.answer(PRIVACY_POLICY_TEXT, reply_markup=privacy_policy_kb(), parse_mode="HTML")
        return

    await render_main_menu(message, tg_user, edit=False)

@router.callback_query(F.data == "accept_privacy_policy")
async def accept_policy_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with async_session() as session:
        stmt = select(User).where(User.id == user_id)
        user = (await session.execute(stmt)).scalar_one_or_none()
        if user:
            user.agreed_terms = True
            await session.commit()

    await callback.answer("✅ Shartlar qabul qilindi!", show_alert=False)
    await render_main_menu(callback, callback.from_user, edit=True)

@router.callback_query(F.data == "decline_privacy_policy")
async def decline_policy_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "❌ <b>Siz foydalanish shartlarini rad etdingiz.</b>\n\n"
        "Xizmatdan foydalanish uchun shartlarni qabul qilishingiz zarur.\n"
        "Qayta urinish uchun /start buyrug'ini yuboring.",
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await render_main_menu(callback, callback.from_user, edit=True)
    await callback.answer()

# MANA SHU HANDLER ISHLAYDI:
@router.callback_query(F.data == "feedback_menu")
async def feedback_menu_handler(callback: CallbackQuery):
    """Taklif va shikoyatlar menyusi."""
    text = (
        "📩 <b>Taklif va shikoyatlar</b>\n\n"
        "Xizmatimiz sifatini yaxshilash bo'yicha takliflaringiz, savollaringiz yoki biror "
        "muammo yuzaga kelgan bo'lsa, bevosita bosh dasturchiga murojaat qilishingiz mumkin:\n\n"
        "👨‍💻 <b>Dasturchi:</b> <b>@zsrov</b>\n\n"
        "<i>Quyidagi tugma orqali to'g'ridan-to'g'ri bog'lanishingiz mumkin 👇</i>"
    )
    await callback.message.edit_text(text, reply_markup=feedback_kb(), parse_mode="HTML")
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
        "🔹 <code>.ok</code> — Bir martalik (o‘z-o‘zidan o‘chuvchi) rasm yoki videoga reply qilib yozsangiz, uni chatda hech qanday iz qoldirmasdan «Saqlangan xabarlar»ingizga saqlaydi va buyruqning o‘zini o‘chirib tashlaydi.\n"
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
        "• O'z-o'zidan o'chuvchi mediani izsiz avto-saqlash (<code>.ok</code>)\n"
        "• Ochiq hikoyalarni anonim yuklab olish (<code>.dw @username</code>)\n"
        "• Guruh va kanallarda chaqmoqdek tez avto-komment qoldirish\n\n"
        "O'zingizga ma'qul tarifni tanlang 👇"
    )
    await callback.message.edit_text(text, reply_markup=subscription_plans_kb(), parse_mode="HTML")
    await callback.answer()
