import re
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from core.database import async_session
from database.models import ScheduledMessage
from bot.keyboards.inline import cancel_kb, main_menu_kb
from bot.handlers.settings import is_userbot_connected, not_connected_kb
from userbot.tasks.scheduled_sender import scheduled_sender

logger = logging.getLogger(__name__)
router = Router()

class ScheduleStates(StatesGroup):
    waiting_for_chat = State()
    waiting_for_time = State()
    waiting_for_mode = State()
    waiting_for_text = State()

def schedule_menu_kb(tasks: list):
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Yangi rejali xabar qo'shish", callback_data="add_schedule")

    for t in tasks:
        mode = "🔄" if t.is_daily else "1️⃣"
        builder.button(
            text=f"🗑 O'chirish: {mode} {t.target_chat} ({t.send_time})",
            callback_data=f"del_sched_{t.id}"
        )

    builder.button(text="⬅️ Asosiy menyu", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

def mode_choice_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Har kuni takrorlansin", callback_data="sched_mode_daily")
    builder.button(text="1️⃣ Faqat 1 marta yuborilsin", callback_data="sched_mode_once")
    builder.button(text="❌ Bekor qilish", callback_data="cancel_action")
    builder.adjust(1, 1, 1)
    return builder.as_markup()

@router.callback_query(F.data == "schedule_menu")
async def show_schedule_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with async_session() as session:
        if not await is_userbot_connected(session, user_id):
            text = (
                "⚠️ <b>Userbot hali ulanmagan!</b>\n\n"
                "Rejali xabarlar funksiyasidan foydalanish uchun avval "
                "shaxsiy hisobingizga userbotni ulashingiz kerak 👇"
            )
            await callback.message.edit_text(text, reply_markup=not_connected_kb(), parse_mode="HTML")
            await callback.answer()
            return

        stmt = select(ScheduledMessage).where(
            ScheduledMessage.user_id == user_id,
            ScheduledMessage.is_active == True
        )
        tasks = (await session.execute(stmt)).scalars().all()

    if not tasks:
        tasks_text = "<i>Hozircha faol rejali xabarlar yo'q.</i>"
    else:
        tasks_text = ""
        for idx, t in enumerate(tasks, 1):
            mode = "🔄 Har kuni" if t.is_daily else "1️⃣ Bir martalik"
            tasks_text += (
                f"<b>{idx}.</b> 🎯 <code>{t.target_chat}</code> | ⏰ <code>{t.send_time}</code> ({mode})\n"
                f"    💬 <i>{t.message_text[:45]}</i>\n\n"
            )

    text = (
        "⏰ <b>Aniq vaqtli Rejali Xabarlar (Auto-Send)</b>\n\n"
        "Xabarlar Toshkent soati bilan <b>bir soniya ham kechikmasdan (0.00s)</b> yuboriladi.\n\n"
        f"{tasks_text}"
        "Kerakli amalni tanlang 👇"
    )
    await callback.message.edit_text(text, reply_markup=schedule_menu_kb(tasks), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "add_schedule")
async def start_add_schedule(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    async with async_session() as session:
        if not await is_userbot_connected(session, user_id):
            await callback.answer("⚠️ Avval userbotni ulang!", show_alert=True)
            return

    await state.set_state(ScheduleStates.waiting_for_chat)
    await callback.message.edit_text(
        "🎯 <b>1-qadam:</b> Xabar qaysi kanal, guruh yoki foydalanuvchiga yuborilsin?\n\n"
        "Username yoki chat manzilini yuboring:\n"
        "<i>Masalan: <code>@kanal_nomi</code> yoki o'zingizga saqlash uchun <code>me</code></i>",
        reply_markup=cancel_kb(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(ScheduleStates.waiting_for_chat)
async def process_sched_chat(message: Message, state: FSMContext):
    target_chat = message.text.strip().replace("https://t.me/", "@")
    if not target_chat.startswith("@") and not target_chat.lstrip("-").isdigit() and target_chat.lower() != "me":
        target_chat = f"@{target_chat}"

    await state.update_data(target_chat=target_chat)
    await state.set_state(ScheduleStates.waiting_for_time)

    await message.answer(
        "⏰ <b>2-qadam:</b> Xabar Toshkent vaqti bilan soat nechada yuborilsin?\n\n"
        "Aniq vaqtni yozing:\n"
        "• Masalan: <code>22:55</code> (soat 22:55:00 da)\n"
        "• Yoki soniyasi bilan: <code>22:55:30</code>",
        reply_markup=cancel_kb(),
        parse_mode="HTML"
    )

@router.message(ScheduleStates.waiting_for_time)
async def process_sched_time(message: Message, state: FSMContext):
    raw_time = message.text.strip()
    time_match = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", raw_time)

    if not time_match:
        await message.answer("❌ Vaqt formati noto'g'ri! Iltimos, <code>22:55</code> yoki <code>22:55:00</code> shaklida kiriting:", reply_markup=cancel_kb(), parse_mode="HTML")
        return

    hh = int(time_match.group(1))
    mm = int(time_match.group(2))
    ss = int(time_match.group(3) or 0)

    if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
        await message.answer("❌ Soat 00-23, daqiqa va soniya 00-59 oralig'ida bo'lishi shart!", reply_markup=cancel_kb())
        return

    formatted_time = f"{hh:02d}:{mm:02d}:{ss:02d}"
    await state.update_data(send_time=formatted_time)
    await state.set_state(ScheduleStates.waiting_for_mode)

    await message.answer(
        f"🔄 <b>3-qadam:</b> Vaqt belgilandi: <code>{formatted_time}</code>\n\n"
        "Bu xabar har kuni shu vaqtda yuborilsinmi yoki faqat bir martami?",
        reply_markup=mode_choice_kb(),
        parse_mode="HTML"
    )

@router.callback_query(ScheduleStates.waiting_for_mode, F.data.in_(["sched_mode_daily", "sched_mode_once"]))
async def process_sched_mode(callback: CallbackQuery, state: FSMContext):
    is_daily = callback.data == "sched_mode_daily"
    await state.update_data(is_daily=is_daily)
    await state.set_state(ScheduleStates.waiting_for_text)

    await callback.message.edit_text(
        "💬 <b>4-qadam:</b> Endi belgilangan vaqtda yuboriladigan <b>xabar matnini</b> yozib yuboring:",
        reply_markup=cancel_kb(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(ScheduleStates.waiting_for_text)
async def process_sched_text(message: Message, state: FSMContext):
    user_id = message.from_user.id
    msg_text = message.text.strip()
    data = await state.get_data()

    async with async_session() as session:
        new_task = ScheduledMessage(
            user_id=user_id,
            target_chat=data["target_chat"],
            message_text=msg_text,
            send_time=data["send_time"],
            is_daily=data["is_daily"],
            is_active=True
        )
        session.add(new_task)
        await session.commit()
        await session.refresh(new_task)

    await scheduled_sender.add_or_reload_task(new_task.id)
    await state.clear()

    mode_str = "🔄 Har kuni" if data["is_daily"] else "1️⃣ Bir martalik"
    await message.answer(
        "✅ <b>Rejali xabar muvaffaqiyatli saqlandi!</b>\n\n"
        f"🎯 <b>Nishon:</b> <code>{data['target_chat']}</code>\n"
        f"⏰ <b>Vaqt:</b> <code>{data['send_time']}</code> (Toshkent)\n"
        f"📌 <b>Rejim:</b> {mode_str}\n"
        f"💬 <b>Matn:</b> <i>{msg_text}</i>\n\n"
        "<i>Belgilangan soniyada kechikishsiz yuboriladi!</i>",
        reply_markup=main_menu_kb(True, True),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("del_sched_"))
async def delete_schedule_handler(callback: CallbackQuery):
    task_id = int(callback.data.replace("del_sched_", ""))
    user_id = callback.from_user.id

    async with async_session() as session:
        stmt = select(ScheduledMessage).where(
            ScheduledMessage.id == task_id,
            ScheduledMessage.user_id == user_id
        )
        task = (await session.execute(stmt)).scalar_one_or_none()
        if task:
            await session.delete(task)
            await session.commit()

    scheduled_sender.remove_from_cache(task_id)
    await callback.answer("🗑 Rejali xabar o'chirildi!", show_alert=True)
    await show_schedule_menu(callback)
