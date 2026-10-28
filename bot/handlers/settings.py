import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from core.database import async_session
from database.models import UserbotSettings
from bot.keyboards.inline import cancel_kb, main_menu_kb
from userbot.tasks.auto_comment import USER_COMMENT_CACHE

logger = logging.getLogger(__name__)
router = Router()

class ManageSettingsStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_channel = State()
    waiting_for_delay = State()

def get_settings_keyboard(enabled: bool):
    builder = InlineKeyboardBuilder()
    status_text = "🟢 Yoqilgan (O'chirish)" if enabled else "🔴 O'chirilgan (Yoqish)"
    
    builder.button(text=f"Holat: {status_text}", callback_data="toggle_comment_status")
    builder.button(text="✏️ Izoh matnini o'zgartirish", callback_data="set_comment_text")
    builder.button(text="➕ Kanal qo'shish (@kanal)", callback_data="add_target_channel")
    builder.button(text="🗑 Kanallar ro'yxatini tozalash", callback_data="clear_target_channels")
    builder.button(text="⏱ Kechikish vaqti (Tezlik)", callback_data="set_comment_delay")
    builder.button(text="⬅️ Asosiy menyu", callback_data="back_to_main")
    builder.adjust(1, 1, 1, 1, 1, 1)
    return builder.as_markup()

async def get_user_settings(session, user_id: int) -> UserbotSettings:
    stmt = select(UserbotSettings).where(UserbotSettings.user_id == user_id)
    settings = (await session.execute(stmt)).scalar_one_or_none()
    if not settings:
        settings = UserbotSettings(user_id=user_id)
        session.add(settings)
        await session.commit()
        await session.refresh(settings)
    return settings

def sync_cache(user_id: int, settings: UserbotSettings):
    """Bazada o'zgargan ma'lumotni darhol RAM keshiga kiritish."""
    USER_COMMENT_CACHE[user_id] = {
        "enabled": settings.auto_comment_enabled,
        "text": settings.comment_text,
        "delay": settings.comment_delay,
        "targets": [ch.lower().replace("@", "").strip() for ch in (settings.target_channels or [])]
    }

@router.callback_query(F.data == "settings_menu")
async def show_settings(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with async_session() as session:
        st = await get_user_settings(session, user_id)
        sync_cache(user_id, st)

    channels = ", ".join([f"@{c}" for c in (st.target_channels or [])]) or "Hozircha kanallar yo'q"
    delay_info = "⚡ 0 soniya (Chaqmoqdek tez)" if st.comment_delay == 0 else f"{st.comment_delay} soniya"

    text = (
        "⚙️ <b>Avto-komment sozlamalari:</b>\n\n"
        f"• Holat: {'🟢 <b>Faol</b>' if st.auto_comment_enabled else '🔴 <b>O‘chirilgan</b>'}\n"
        f"• Joriy izoh: <i>«{st.comment_text}»</i>\n"
        f"• Tezlik/Kechikish: <b>{delay_info}</b>\n"
        f"• Nishondagi kanallar:\n   👉 <b>{channels}</b>\n\n"
        "O'zgartirish uchun kerakli tugmani bosing:"
    )
    await callback.message.edit_text(text, reply_markup=get_settings_keyboard(st.auto_comment_enabled), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "toggle_comment_status")
async def toggle_status(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with async_session() as session:
        st = await get_user_settings(session, user_id)
        st.auto_comment_enabled = not st.auto_comment_enabled
        await session.commit()
        sync_cache(user_id, st)

    await show_settings(callback)

@router.callback_query(F.data == "set_comment_text")
async def start_set_text(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ManageSettingsStates.waiting_for_text)
    await callback.message.edit_text(
        "✏️ Postlar tagiga qoldirmoqchi bo'lgan <b>yangi izoh matnini</b> yuboring:\n"
        "<i>Masalan: Birinchi! 🔥 yoki Zo'r post 👍</i>",
        reply_markup=cancel_kb(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(ManageSettingsStates.waiting_for_text)
async def save_new_text(message: Message, state: FSMContext):
    user_id = message.from_user.id
    new_text = message.text.strip()

    async with async_session() as session:
        st = await get_user_settings(session, user_id)
        st.comment_text = new_text
        await session.commit()
        sync_cache(user_id, st)

    await state.clear()
    await message.answer("✅ Izoh matni muvaffaqiyatli saqlandi!", reply_markup=main_menu_kb(True, True))

@router.callback_query(F.data == "add_target_channel")
async def start_add_channel(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ManageSettingsStates.waiting_for_channel)
    await callback.message.edit_text(
        "➕ Yangi postlariga avto-izoh yozilishi kerak bo'lgan <b>kanal usernamesini</b> yuboring:\n\n"
        "Masalan: <code>@daryo</code> yoki <code>@kunuz</code>\n"
        "<i>(Bir nechta bo'lsa, vergul bilan ajratib yuborishingiz mumkin: @kanal1, @kanal2)</i>",
        reply_markup=cancel_kb(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(ManageSettingsStates.waiting_for_channel)
async def save_new_channels(message: Message, state: FSMContext):
    user_id = message.from_user.id
    raw_channels = message.text.replace("https://t.me/", "").replace("@", "").split(",")

    new_list = [ch.strip().lower() for ch in raw_channels if ch.strip()]

    async with async_session() as session:
        st = await get_user_settings(session, user_id)
        current = list(st.target_channels or [])
        for ch in new_list:
            if ch not in current:
                current.append(ch)
        st.target_channels = current
        await session.commit()
        sync_cache(user_id, st)

    await state.clear()
    await message.answer(f"✅ Kanallar qo'shildi: {', '.join(['@' + c for c in new_list])}", reply_markup=main_menu_kb(True, True))

@router.callback_query(F.data == "clear_target_channels")
async def clear_channels(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with async_session() as session:
        st = await get_user_settings(session, user_id)
        st.target_channels = []
        await session.commit()
        sync_cache(user_id, st)

    await callback.answer("🗑 Barcha kanallar nishondan o'chirildi!", show_alert=True)
    await show_settings(callback)

@router.callback_query(F.data == "set_comment_delay")
async def start_set_delay(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ManageSettingsStates.waiting_for_delay)
    await callback.message.edit_text(
        "⏱ Yangi post chiqqandan keyin necha soniya kutib izoh yozilsin?\n\n"
        "• <b>0</b> — darhol, soniyaning ulushlarida yozish (Tavsiya etiladi!)\n"
        "• <b>3</b> yoki <b>5</b> — 3-5 soniya kutib yozish\n\n"
        "Faqat raqam yuboring:",
        reply_markup=cancel_kb(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(ManageSettingsStates.waiting_for_delay)
async def save_delay(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not message.text.isdigit():
        await message.answer("❌ Iltimos, faqat musbat raqam kiriting (masalan: 0):")
        return

    delay = int(message.text)
    async with async_session() as session:
        st = await get_user_settings(session, user_id)
        st.comment_delay = delay
        await session.commit()
        sync_cache(user_id, st)

    await state.clear()
    await message.answer(f"✅ Kechikish vaqti {delay} soniya qilib belgilandi!", reply_markup=main_menu_kb(True, True))
