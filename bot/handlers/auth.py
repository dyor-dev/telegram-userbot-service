import logging
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from hydrogram import Client
from hydrogram.errors import (
    SessionPasswordNeeded,
    PhoneCodeInvalid,
    PhoneCodeExpired,
    PasswordHashInvalid,
    PhoneNumberInvalid,
    FloodWait
)
from sqlalchemy import select

from core.config import settings
from core.database import async_session
from core.security import encrypt_session
from database.models import User, UserbotSession, Subscription, SubscriptionStatus, PlanType
from bot.states.auth import AuthStates
from bot.keyboards.inline import cancel_kb, main_menu_kb

logger = logging.getLogger(__name__)
router = Router()

auth_clients: dict[int, Client] = {}

async def cleanup_client(user_id: int):
    client = auth_clients.pop(user_id, None)
    if client:
        try:
            if client.is_connected:
                await client.disconnect()
        except Exception:
            pass

@router.callback_query(F.data == "connect_userbot")
async def start_auth_process(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id

    async with async_session() as session:
        stmt = select(User).where(User.id == user_id)
        user = (await session.execute(stmt)).scalar_one_or_none()

        sub_stmt = select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.expires_at > datetime.utcnow()
        )
        active_sub = (await session.execute(sub_stmt)).scalars().first()

        if not active_sub and user and user.has_used_trial:
            await callback.answer(
                "⚠️ Sizning bepul sinov vaqtingiz tugagan. Davom etish uchun VIP obuna xarid qiling!",
                show_alert=True
            )
            return

    await cleanup_client(user_id)
    await state.set_state(AuthStates.waiting_for_phone)

    text = (
        "📱 <b>Telegram akkauntingizni ulash</b>\n\n"
        "Iltimos, akkauntingiz telefon raqamini xalqaro formatda kiriting:\n"
        "Masalan: <code>+998901234567</code>"
    )
    await callback.message.edit_text(text, reply_markup=cancel_kb(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "cancel_action")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    await cleanup_client(callback.from_user.id)
    await state.clear()
    await callback.message.edit_text(
        "❌ Amaliyot bekor qilindi.",
        reply_markup=main_menu_kb(has_session=False, is_vip=False)
    )
    await callback.answer()

@router.message(AuthStates.waiting_for_phone)
async def process_phone_number(message: Message, state: FSMContext):
    user_id = message.from_user.id
    phone = message.text.strip().replace(" ", "").replace("-", "")

    msg = await message.answer("⏳ Telegram serveriga so'rov yuborilmoqda...")

    client = Client(
        name=f"auth_{user_id}",
        api_id=settings.TELEGRAM_API_ID,
        api_hash=settings.TELEGRAM_API_HASH,
        in_memory=True
    )

    try:
        await client.connect()
        sent_code = await client.send_code(phone)
        auth_clients[user_id] = client

        await state.update_data(
            phone=phone,
            phone_code_hash=sent_code.phone_code_hash
        )
        await state.set_state(AuthStates.waiting_for_code)

        # Qat'iy xavfsizlik talabi bilan kod so'rash
        text = (
            f"📩 <b>{phone}</b> raqamiga Telegram orqali tasdiqlash kodi yuborildi.\n\n"
            "⚠️ <b>DIQQAT! TELEGRAM BLOKLASHIDAN HIMOYA:</b>\n"
            "Telegram hisobingiz xavfsizligi va kod bekor bo'lmasligi uchun, kod raqamlari orasiga "
            "<b>ALBATTA BO'SH JOY (PROBEL) QO'YIB YOZING!</b>\n\n"
            "To'g'ri shakl: <code>1 2 3 4 5</code>\n\n"
            "🚫 <i>Raqamlarni biriktirib yozmang, aks holda Telegram so'rovni bloklaydi!</i>"
        )

        await msg.edit_text(text, reply_markup=cancel_kb(), parse_mode="HTML")

    except PhoneNumberInvalid:
        await cleanup_client(user_id)
        await msg.edit_text("❌ Telefon raqami noto'g'ri kiritildi. Qaytadan tekshirib yuboring:", reply_markup=cancel_kb())
    except FloodWait as e:
        await cleanup_client(user_id)
        await msg.edit_text(f"⚠️ Telegram cheklovi: Iltimos, {e.value} soniya kuting va qayta urinib ko'ring.")
        await state.clear()
    except Exception as e:
        await cleanup_client(user_id)
        logger.error(f"Send code error: {e}")
        await msg.edit_text(f"❌ Xatolik yuz berdi: {str(e)}", reply_markup=cancel_kb())

@router.message(AuthStates.waiting_for_code)
async def process_auth_code(message: Message, state: FSMContext):
    user_id = message.from_user.id
    raw_text = message.text.strip()

    # 1. FOYDALANUVCHI PROBEL QO'YGANLIGINI QAT'IY TEKSHIRISH
    # Agar raqamlarni biriktirib yozgan bo'lsa (probel yo'q bo'lsa), bloklanishdan asrash uchun to'xtatamiz!
    if " " not in raw_text and "-" not in raw_text and len(raw_text) >= 4:
        warning_msg = (
            "⚠️ <b>XATOLIK! PROBEL QO'YISH MAJBURIY!</b>\n\n"
            "Telegram hisobingiz bloklanib qolmasligi uchun, har bir raqam orasiga <b>bo'sh joy (probel)</b> qoldirib yozishingiz shart!\n\n"
            "Masalan: <code>1 2 3 4 5</code>\n\n"
            "Iltimos, kodni probel bilan qaytadan yuboring:"
        )
        await message.answer(warning_msg, reply_markup=cancel_kb(), parse_mode="HTML")
        return

    # Probellarni olib tashlab toza kodni ajratib olish
    code = raw_text.replace(" ", "").replace("-", "")

    if not code.isdigit():
        await message.answer("❌ Kod faqat raqamlardan iborat bo'lishi kerak. Masalan: <code>1 2 3 4 5</code>", reply_markup=cancel_kb())
        return

    data = await state.get_data()
    phone = data.get("phone")
    phone_code_hash = data.get("phone_code_hash")

    client = auth_clients.get(user_id)
    if not client:
        await message.answer("⚠️ Sessiya eskirgan. Iltimos, boshidan boshlang.", reply_markup=main_menu_kb(False, False))
        await state.clear()
        return

    try:
        await client.sign_in(phone, phone_code_hash, code)
        await finish_authorization(message, state, client, phone)
    except SessionPasswordNeeded:
        await state.set_state(AuthStates.waiting_for_password)
        await message.answer(
            "🔐 Akkauntingizda <b>Ikki bosqichli autentifikatsiya (2FA parol)</b> yoqilgan.\n\n"
            "Iltimos, hisobingiz parolini kiriting:",
            reply_markup=cancel_kb(),
            parse_mode="HTML"
        )
    except (PhoneCodeInvalid, PhoneCodeExpired):
        await message.answer("❌ Tasdiqlash kodi noto'g'ri yoki muddati o'tgan. Qaytadan probel bilan kiriting (1 2 3 4 5):", reply_markup=cancel_kb())
    except Exception as e:
        logger.error(f"Sign in error: {e}")
        await message.answer(f"❌ Xatolik yuz berdi: {str(e)}", reply_markup=cancel_kb())

@router.message(AuthStates.waiting_for_password)
async def process_2fa_password(message: Message, state: FSMContext):
    user_id = message.from_user.id
    password = message.text.strip()
    data = await state.get_data()
    phone = data.get("phone")

    client = auth_clients.get(user_id)
    if not client:
        await message.answer("⚠️ Sessiya eskirgan. Iltimos, boshidan boshlang.", reply_markup=main_menu_kb(False, False))
        await state.clear()
        return

    try:
        await client.check_password(password)
        await finish_authorization(message, state, client, phone)
    except PasswordHashInvalid:
        await message.answer("❌ Ikki bosqichli parol noto'g'ri. Qaytadan urinib ko'ring:", reply_markup=cancel_kb())
    except Exception as e:
        logger.error(f"2FA error: {e}")
        await message.answer(f"❌ Xatolik yuz berdi: {str(e)}", reply_markup=cancel_kb())

async def finish_authorization(message: Message, state: FSMContext, client: Client, phone: str):
    user_id = message.from_user.id
    try:
        session_str = await client.export_session_string()
        encrypted_session = encrypt_session(session_str)

        async with async_session() as session:
            stmt = select(User).where(User.id == user_id)
            user = (await session.execute(stmt)).scalar_one_or_none()

            sess_stmt = select(UserbotSession).where(UserbotSession.user_id == user_id)
            user_session = (await session.execute(sess_stmt)).scalar_one_or_none()

            if user_session:
                user_session.encrypted_session = encrypted_session
                user_session.phone_number = phone
                user_session.is_active = True
            else:
                user_session = UserbotSession(
                    user_id=user_id,
                    phone_number=phone,
                    encrypted_session=encrypted_session,
                    is_active=True
                )
                session.add(user_session)

            sub_stmt = select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.expires_at > datetime.utcnow()
            )
            active_sub = (await session.execute(sub_stmt)).scalars().first()

            trial_applied = False
            if not active_sub and user and not user.has_used_trial:
                now = datetime.utcnow()
                expires = now + timedelta(days=1)
                user.has_used_trial = True
                user.trial_started_at = now

                trial_sub = Subscription(
                    user_id=user_id,
                    plan=PlanType.TRIAL,
                    status=SubscriptionStatus.ACTIVE,
                    starts_at=now,
                    expires_at=expires
                )
                session.add(trial_sub)
                trial_applied = True

            await session.commit()

        await cleanup_client(user_id)
        await state.clear()

        try:
            from userbot.client_manager import client_manager
            await client_manager.start_user(user_id, session_str)
        except Exception as err:
            logger.warning(f"ClientManager start warning: {err}")

        extra_msg = "\n\n🎁 <b>Sizga 1 kunlik bepul sinov vaqti aynan hozirdan boshlab berildi!</b>" if trial_applied else ""

        await message.answer(
            f"🎉 <b>Tabriklaymiz! Userbotingiz muvaffaqiyatli ulandi va ishga tushirildi!</b>{extra_msg}\n\n"
            "Endi siz shaxsiy hisobingizdan maxsus buyruqlarni (<code>.ping</code>, <code>.ok</code>, <code>.dw @username</code>) ishlatishingiz mumkin!",
            reply_markup=main_menu_kb(has_session=True, is_vip=True),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Finish auth error: {e}")
        await message.answer(f"❌ Sessiyani saqlashda xatolik: {str(e)}")
        await cleanup_client(user_id)
        await state.clear()

@router.callback_query(F.data == "manage_userbot")
async def manage_userbot_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with async_session() as session:
        stmt = select(UserbotSession).where(UserbotSession.user_id == user_id)
        user_sess = (await session.execute(stmt)).scalar_one_or_none()

    if not user_sess or not user_sess.is_active:
        from bot.handlers.settings import not_connected_kb
        await callback.message.edit_text(
            "⚠️ <b>Userbotingiz ulanmagan!</b>\n\nQuyidagi tugma orqali hisobingizni ulashingiz mumkin:",
            reply_markup=not_connected_kb(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    phone = user_sess.phone_number or "Noma'lum"
    text = (
        f"⚙️ <b>Userbot Holati</b>\n\n"
        f"• Ulangan raqam: <code>{phone}</code>\n"
        f"• Holat: 🟢 <b>Faol (24/7 ishlamoqda)</b>\n\n"
        "Userbotni akkauntingizdan uzmoqchi bo'lsangiz, quyidagi tugmani bosing:"
    )
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="🛑 Userbotni o'chirish (Uzish)", callback_data="disconnect_userbot")
    builder.button(text="⬅️ Asosiy menyu", callback_data="back_to_main")
    builder.adjust(1, 1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "disconnect_userbot")
async def disconnect_userbot_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    try:
        from userbot.client_manager import client_manager
        await client_manager.stop_user(user_id)
    except Exception:
        pass

    async with async_session() as session:
        stmt = select(UserbotSession).where(UserbotSession.user_id == user_id)
        user_sess = (await session.execute(stmt)).scalar_one_or_none()
        if user_sess:
            await session.delete(user_sess)
            await session.commit()

    await callback.message.edit_text(
        "✅ Userbot to'xtatildi va hisobingizdan uzildi.",
        reply_markup=main_menu_kb(has_session=False, is_vip=False)
    )
    await callback.answer()
