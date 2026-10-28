import logging
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
from database.models import User, UserbotSession, Subscription, SubscriptionStatus
from bot.states.auth import AuthStates
from bot.keyboards.inline import cancel_kb, main_menu_kb

logger = logging.getLogger(__name__)
router = Router()

# Vaqtinchalik xotiradagi mijozlar (Login jarayoni uchun)
auth_clients: dict[int, Client] = {}

async def cleanup_client(user_id: int):
    """Vaqtincha ochilgan ulanishni xotiradan tozalash."""
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

    # Obuna yoki Trial mavjudligini tekshirish
    async with async_session() as session:
        stmt = select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.status == SubscriptionStatus.ACTIVE
        )
        active_sub = (await session.execute(stmt)).scalars().first()

        if not active_sub:
            await callback.answer(
                "⚠️ Userbotni ulash uchun avval 'Bepul Trial' oling yoki VIP obunani faollashtiring!",
                show_alert=True
            )
            return

    await cleanup_client(user_id)
    await state.set_state(AuthStates.waiting_for_phone)

    text = (
        "📱 <b>Telegram akkauntingizni ulash</b>\n\n"
        "Iltimos, Telegram akkauntingiz telefon raqamini xalqaro formatda kiriting:\n"
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

        await msg.edit_text(
            f"📩 <b>{phone}</b> raqamiga Telegram orqali 5 xonali tasdiqlash kodi yuborildi.\n\n"
            "Iltimos, kelgan kodni kiriting:\n"
            "<i>(Maslahat: Raqamlar orasiga bo'sh joy qoldirib yozsangiz ham bo'ladi, masalan: 1 2 3 4 5)</i>",
            reply_markup=cancel_kb(),
            parse_mode="HTML"
        )
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
    code = message.text.strip().replace(" ", "")
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
        await message.answer("❌ Tasdiqlash kodi noto'g'ri yoki muddati o'tgan. Qaytadan kiriting:", reply_markup=cancel_kb())
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
    """Muvaffaqiyatli kirilgach, sessiyani shifrlab saqlash."""
    user_id = message.from_user.id
    try:
        session_str = await client.export_session_string()
        encrypted_session = encrypt_session(session_str)

        async with async_session() as session:
            stmt = select(UserbotSession).where(UserbotSession.user_id == user_id)
            user_session = (await session.execute(stmt)).scalar_one_or_none()

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

            await session.commit()

        await cleanup_client(user_id)
        await state.clear()

        # Userbotni ishga tushirish (Keyingi bosqichda menejer orqali ulaymiz)
        try:
            from userbot.client_manager import client_manager
            await client_manager.start_user(user_id, session_str)
        except Exception as err:
            logger.warning(f"ClientManager start warning: {err}")

        await message.answer(
            "🎉 <b>Tabriklaymiz! Userbot muvaffaqiyatli ulandi va faollashtirildi!</b>\n\n"
            "Endi siz shaxsiy akkauntingizdan buyruqlarni ishlatishingiz mumkin (Masalan: <code>.ping</code>)",
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
    """Userbotni boshqarish va to'xtatish menyusi."""
    user_id = callback.from_user.id
    async with async_session() as session:
        stmt = select(UserbotSession).where(UserbotSession.user_id == user_id)
        user_sess = (await session.execute(stmt)).scalar_one_or_none()

    phone = user_sess.phone_number if user_sess else "Noma'lum"
    text = (
        f"⚙️ <b>Userbot Holati</b>\n\n"
        f"• Ulangan raqam: <code>{phone}</code>\n"
        f"• Holat: 🟢 Faol (Ishlamoqda)\n\n"
        "Userbotni akkauntingizdan uzmoqchi bo'lsangiz, quyidagi tugmani bosing:"
    )
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="🛑 Userbotni o'chirish (Uzish)", callback_data="disconnect_userbot")
    builder.button(text="⬅️ Orqaga", callback_data="back_to_main")
    builder.adjust(1, 1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "disconnect_userbot")
async def disconnect_userbot_handler(callback: CallbackQuery):
    """Userbotni to'xtatish va bazadan o'chirish."""
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
        "✅ Userbot muvaffaqiyatli to'xtatildi va akkauntingizdan uzildi.",
        reply_markup=main_menu_kb(has_session=False, is_vip=False)
    )
    await callback.answer()
