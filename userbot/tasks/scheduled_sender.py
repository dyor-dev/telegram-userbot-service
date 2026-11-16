import time
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Set
from sqlalchemy import select

from core.database import async_session
from database.models import ScheduledMessage
from userbot.client_manager import client_manager

logger = logging.getLogger(__name__)

# O'zbekiston (Toshkent) vaqt mintaqasi: UTC+5
TASHKENT_TZ = timezone(timedelta(hours=5))

# Xotiradagi tezkor kesh: task_id -> vazifa ma'lumotlari
SCHEDULED_TASKS: Dict[int, dict] = {}

# Bugun yuborilib bo'lgan vazifalar va ayni paytda otishga tayyorlanayotganlar
SENT_TODAY: Dict[int, str] = {}
FIRING_IN_PROGRESS: Set[int] = set()

class ScheduledSender:
    def __init__(self):
        self._running = False

    async def load_all_from_db(self):
        """Server yonganda bazadagi barcha faol rejali xabarlarni xotiraga yuklash."""
        async with async_session() as session:
            stmt = select(ScheduledMessage).where(ScheduledMessage.is_active == True)
            tasks = (await session.execute(stmt)).scalars().all()

            SCHEDULED_TASKS.clear()
            for t in tasks:
                SCHEDULED_TASKS[t.id] = {
                    "id": t.id,
                    "user_id": t.user_id,
                    "target_chat": t.target_chat,
                    "message_text": t.message_text,
                    "send_time": t.send_time,
                    "is_daily": t.is_daily
                }
        logger.info(f"⏰ Jami {len(SCHEDULED_TASKS)} ta rejali xabar xotiraga yuklandi.")

    async def add_or_reload_task(self, task_id: int):
        """Yangi vazifa qo'shilganda darhol keshga kiritish."""
        async with async_session() as session:
            stmt = select(ScheduledMessage).where(ScheduledMessage.id == task_id, ScheduledMessage.is_active == True)
            t = (await session.execute(stmt)).scalar_one_or_none()
            if t:
                SCHEDULED_TASKS[t.id] = {
                    "id": t.id,
                    "user_id": t.user_id,
                    "target_chat": t.target_chat,
                    "message_text": t.message_text,
                    "send_time": t.send_time,
                    "is_daily": t.is_daily
                }
            else:
                SCHEDULED_TASKS.pop(task_id, None)

    def remove_from_cache(self, task_id: int):
        SCHEDULED_TASKS.pop(task_id, None)
        SENT_TODAY.pop(task_id, None)
        FIRING_IN_PROGRESS.discard(task_id)

    async def _deactivate_one_time_task(self, task_id: int):
        """1 martalik xabar yuborilgandan so'ng bazadan va keshdan o'chirish."""
        SCHEDULED_TASKS.pop(task_id, None)
        async with async_session() as session:
            stmt = select(ScheduledMessage).where(ScheduledMessage.id == task_id)
            t = (await session.execute(stmt)).scalar_one_or_none()
            if t:
                t.is_active = False
                await session.commit()

    async def _fire_at_exact_second(self, task: dict, target_dt: datetime, today_str: str):
        """Belgilangan soniyaga 3 sekund qolganda tayyorgarlik ko'rib, 0.000s aniqlikda otish."""
        task_id = task["id"]
        user_id = task["user_id"]
        target_chat = task["target_chat"]
        text = task["message_text"]
        is_daily = task["is_daily"]

        try:
            client = client_manager.clients.get(user_id)
            if not client or not client.is_connected:
                return

            # 1. Chatni oldindan tayyorlash (Pre-warm peer resolution)
            chat_id = target_chat
            try:
                if str(target_chat).lstrip("-").isdigit():
                    chat_id = int(target_chat)
                else:
                    # Username bo'lsa manzilini oldindan keshlaydi
                    await client.resolve_peer(str(target_chat).replace("@", ""))
            except Exception as err:
                logger.warning(f"Chatni tayyorlashda ogohlantirish ({target_chat}): {err}")

            # 2. Aniq unix timestampga o'tkazish
            target_ts = target_dt.timestamp()

            # 3. 50 millisekund qolgunicha kutish
            now_ts = time.time()
            coarse_wait = target_ts - now_ts - 0.05
            if coarse_wait > 0:
                await asyncio.sleep(coarse_wait)

            # 4. MIKRO-ANIQLIK (2 millisekundlik sikl orqali aynan .000 soniyani tutish)
            while time.time() < target_ts:
                await asyncio.sleep(0.002)

            # 5. ZARBA! Xabarni yuborish
            await client.send_message(chat_id=chat_id, text=text)
            logger.info(f"🎯 [ANQ VAQTDA YUBORILDI] User: {user_id} -> {target_chat} ({task['send_time']})")

            # 6. Takrorlanish holatini belgilash
            if is_daily:
                SENT_TODAY[task_id] = today_str
            else:
                await self._deactivate_one_time_task(task_id)

        except Exception as e:
            logger.error(f"Rejali xabar yuborishda xatolik (Task {task_id}): {e}")
            SENT_TODAY[task_id] = today_str  # Xato bo'lsa buguncha qayta urinib spam qilmasligi uchun
        finally:
            FIRING_IN_PROGRESS.discard(task_id)

    async def run_loop(self):
        """Asosiy nazorat aylanmasi."""
        if self._running:
            return
        self._running = True

        await self.load_all_from_db()
        logger.info("⏱ Aniq vaqtli xabar yuboruvchi (Zero-Delay Scheduler) ishga tushdi!")

        while self._running:
            try:
                now_tashkent = datetime.now(TASHKENT_TZ)
                today_str = now_tashkent.strftime("%Y-%m-%d")

                for task_id, task in list(SCHEDULED_TASKS.items()):
                    if task_id in FIRING_IN_PROGRESS:
                        continue
                    if SENT_TODAY.get(task_id) == today_str:
                        continue

                    # Foydalanuvchining userboti faolmi?
                    if task["user_id"] not in client_manager.clients:
                        continue

                    try:
                        # Vaqtni parse qilish ("22:55:00" yoki "22:55")
                        parts = task["send_time"].split(":")
                        hh = int(parts[0])
                        mm = int(parts[1])
                        ss = int(parts[2]) if len(parts) > 2 else 0

                        target_dt = now_tashkent.replace(hour=hh, minute=mm, second=ss, microsecond=0)
                        diff = (target_dt - now_tashkent).total_seconds()

                        # Agar belgilangan vaqtga 0 dan 4 soniyagacha qolgan bo'lsa — otishga tayyorlaymiz!
                        if 0 <= diff <= 4.0:
                            FIRING_IN_PROGRESS.add(task_id)
                            asyncio.create_task(self._fire_at_exact_second(task, target_dt, today_str))
                    except Exception:
                        continue

            except Exception as e:
                logger.error(f"Scheduler siklida xatolik: {e}")

            await asyncio.sleep(0.5)

scheduled_sender = ScheduledSender()
