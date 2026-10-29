from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from core.database import async_session
from database.models import User, UserbotSession, Subscription, PlanType, SubscriptionStatus, UserbotSettings
from bot.keyboards.inline import main_menu_kb, subscription_plans_kb, feedback_kb, referral_kb

router = Router()

PRIVACY_POLICY_TEXT = (
    "📄 <b>Foydalanish shartlari va Maxfiylik siyosati</b>\n\n"
    "🔐 <b>Xush kelibsiz! Xizmatimizdan foydalanishdan oldin quyidagi shartlar bilan tanishib chiqing:</b>\n\n"
    "<b>1. Ma’lumotlar xavfsizligi va shifrlash:</b>\n"
    "• Bot foydalanuvchining shaxsiy yozishmalarini o‘qimaydi va begonalarga uzatmaydi.\n"
    "• Akkauntingizni ulashda hosil bo‘ladigan sessiya ma’lumotlar bazasida <b>AES (Fernet)</b> xalqaro shifrlash standarti orqali kuchli shifrlangan holatda saqlanadi.\n"
    "• Telefon raqami va tasdiqlash kodlari faqatgina Telegram rasmiy MTProto API orqali akkauntni ulash uchun ishlatiladi.\n\n"
    "<b>2. Foydalanuvchi javobgarligi:</b>\n"
    "• Userbot sizning shaxsiy Telegram hisobingiz nomidan buyruqlarni bajaradi.\n"
    "• Userbot orqali yoziladigan izohlar va qilinadigan harakatlar uchun <b>to‘liq javobgarlik foydalanuvchining o‘z zimmasidadir</b>.\n\n"
    "<b>3. Bepul Trial va VIP obuna shartlari:</b>\n"
    "• Bepul sinov muddati har bir foydalanuvchiga faqat 1 marta beriladi.\n"
    "• Obuna muddati tugagach, barcha avtomatik funksiyalar to‘xtatiladi.\n\n"
    "<b>4. Rozilik bildirish:</b>\n"
    "Quyidagi <b>«✅ Roziman va qabul qilaman»</b> tugmasini bosish orqali siz barcha shartlarga to‘liq rozilik bildirasiz."
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
async def cmd_start(message: Message, command: CommandObject):
    tg_user = message.from_user

    # Taklif qiluvchi ID sini aniqlash (?start=ref_12345678)
    inviter_id = None
    if command.args and command.args.startswith("ref_"):
        try:
            potential_inviter = int(command.args.replace("ref_", ""))
            if potential_inviter != tg_user.id:
                inviter_id = potential_inviter
        except ValueError:
            pass

    async with async_session() as session:
        user_stmt = select(User).where(User.id == tg_user.id)
        user = (await session.execute(user_stmt)).scalar_one_or_none()

        if not user:
            user = User(
                id=tg_user.id,
                username=tg_user.username,
                full_name=tg_user.full_name or "Foydalanuvchi",
                agreed_terms=False,
                referred_by=inviter_id
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
async def accept_policy_handler(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    inviter_to_reward = None
    new_referral_total = 0

    async with async_session() as session:
        stmt = select(User).where(User.id == user_id)
        user = (await session.execute(stmt)).scalar_one_or_none()
        if user:
            user.agreed_terms = True

            # Agar yangi foydalanuvchi referal orqali kelgan bo'lsa:
            if user.referred_by:
                inviter_stmt = select(User).where(User.id == user.referred_by)
                inviter = (await session.execute(inviter_stmt)).scalar_one_or_none()
                if inviter:
                    inviter.referral_count = (inviter.referral_count or 0) + 1
                    new_referral_total = inviter.referral_count
                    inviter_to_reward = inviter.id

                    # HAR 3 TA REFERAL UCHUN +3 KUN VIP BONUS
                    if new_referral_total % 3 == 0:
                        now = datetime.utcnow()
                        sub_stmt = select(Subscription).where(
                            Subscription.user_id == inviter.id,
                            Subscription.status == SubscriptionStatus.ACTIVE,
                            Subscription.expires_at > now
                        )
                        active_sub = (await session.execute(sub_stmt)).scalar_one_or_none()
                        if active_sub:
                            active_sub.expires_at += timedelta(days=3)
                        else:
                            new_sub = Subscription(
                                user_id=inviter.id,
                                plan=PlanType.CUSTOM,
                                status=SubscriptionStatus.ACTIVE,
                                starts_at=now,
                                expires_at=now + timedelta(days=3)
                            )
                            session.add(new_sub)

            await session.commit()

    # Taklif qiluvchini xabardor qilish
    if inviter_to_reward:
        try:
            bonus_msg = ""
            if new_referral_total % 3 == 0:
                bonus_msg = "\n\n🥳 <b>Tabriklaymiz! Siz 3 ta do'stingizni taklif qildingiz va sizga +3 kun bepul VIP taqdim etildi!</b>"
            await bot.send_message(
                chat_id=inviter_to_reward,
                text=f"🎉 <b>Yangi do'stingiz taklif havolangiz orqali qo'shildi!</b>\n"
                     f"👥 Jami takliflaringiz: <b>{new_referral_total} ta</b>{bonus_msg}",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await callback.answer("✅ Shartlar qabul qilindi!", show_alert=False)
    await render_main_menu(callback, callback.from_user, edit=True)

@router.callback_query(F.data == "decline_privacy_policy")
async def decline_policy_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "❌ <b>Siz foydalanish shartlarini rad etdingiz.</b>\n\n"
        "Qayta urinish uchun /start buyrug'ini yuboring.",
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await render_main_menu(callback, callback.from_user, edit=True)
    await callback.answer()

@router.callback_query(F.data == "referral_menu")
async def referral_menu_handler(callback: CallbackQuery, bot: Bot):
    """Referal menyusi."""
    user_id = callback.from_user.id
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"

    async with async_session() as session:
        stmt = select(User.referral_count).where(User.id == user_id)
        count = (await session.execute(stmt)).scalar_one_or_none() or 0

    text = (
        "👥 <b>Do'stlarni taklif qiling va bepul VIP oling!</b>\n\n"
        "O'z shaxsiy havolangiz orqali do'stlaringizni taklif qiling. "
        "<b>Har 3 ta taklif qilingan do'stingiz uchun sizga +3 kunlik VIP obuna avtomatik sovg'a qilinadi!</b>\n\n"
        f"📊 <b>Siz taklif qilgan do'stlar:</b> <code>{count}</code> ta\n"
        f"🔗 <b>Sizning shaxsiy havolangiz:</b>\n<code>{ref_link}</code>\n\n"
        "<i>Quyidagi tugma orqali havolani darhol do'stlaringizga yoki guruhlarga ulashishingiz mumkin 👇</i>"
    )
    await callback.message.edit_text(text, reply_markup=referral_kb(ref_link), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "feedback_menu")
async def feedback_menu_handler(callback: CallbackQuery):
    text = (
        "📩 <b>Taklif va shikoyatlar</b>\n\n"
        "Xizmatimiz sifatini yaxshilash bo'yicha takliflaringiz yoki savollaringiz bo'lsa, "
        "bevosita bosh dasturchiga murojaat qilishingiz mumkin:\n\n"
        "👨‍💻 <b>Dasturchi:</b> <b>@zsrov</b>"
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
        "🔹 <code>.del</code> — Chatdagi barcha o‘z xabarlaringizni va buyruqning o‘zini bir zumda tozalash.\n"
        "🔹 <code>.ok</code> — Bir martalik (o‘z-o‘zidan o‘chuvchi) rasm yoki videoga reply qilib yozsangiz, uni chatda hech qanday iz qoldirmasdan «Saqlangan xabarlar»ingizga saqlaydi.\n"
        "🔹 <code>.dw @username</code> — Belgilangan foydalanuvchining hikoyalarini (Stories) <b>anonim tarzda</b> yuklab «Saqlangan xabarlar»ingizga tashlab beradi.\n"
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
        "• Barcha o'z xabarlaringizni tozalash (<code>.del</code>)\n"
        "• O'z-o'zidan o'chuvchi mediani izsiz avto-saqlash (<code>.ok</code>)\n"
        "• Ochiq hikoyalarni anonim yuklab olish (<code>.dw @username</code>)\n"
        "• Guruh va kanallarda chaqmoqdek tez avto-komment qoldirish\n\n"
        "O'zingizga ma'qul tarifni tanlang 👇"
    )
    await callback.message.edit_text(text, reply_markup=subscription_plans_kb(), parse_mode="HTML")
    await callback.answer()
