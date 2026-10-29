import random
import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional
from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder
from hydrogram import Client
from hydrogram.errors import AuthKeyUnregistered, UserDeactivated, SessionRevoked, SessionExpired
from hydrogram.raw.functions import Ping
from sqlalchemy import select

from core.config import settings
from core.database import async_session
from core.security import decrypt_session
from database.models import UserbotSession, Subscription, SubscriptionStatus

logger = logging.getLogger(__name__)

class ClientManager:
    def __init__(self):
        self.clients: Dict[int, Client] = {}
        self._keepalive_task: Optional[asyncio.Task] = None

    def _attach_handlers(self, client: Client, user_id: int):
        try:
            from userbot.handlers.commands import register_commands
            register_commands(client)
        except Exception as e:
            logger.warning(f"Buyruqlarni ulashda xatolik ({user_id}): {e}")

        try:
            from userbot.tasks.auto_comment import register_auto_comment
            register_auto_comment(client, user_id)
        except Exception as e:
            logger.warning(f"Avto-kommentni ulashda xatolik ({user_id}): {e}")

    async def _start_keepalive_if_needed(self):
        """5 soniyalik giper-tezkor anti-sleep siklini ishga tushirish."""
        if self._keepalive_task is None or self._keepalive_task.done():
            self._keepalive_task = asyncio.create_task(self._keep_alive_loop())
            logger.info("⚡ Giper-tezkor 5s Keep-Alive tizimi ishga tushirildi.")

    async def _ping_single_client(self, client: Client):
        """Bitta mijozga yengil tasodifiy MTProto ping yuborish."""
        try:
            if client.is_connected:
                await client.invoke(Ping(ping_id=random.randint(1, 2147483647)))
        except (AuthKeyUnregistered, UserDeactivated, SessionRevoked, SessionExpired):
            pass
        except Exception:
            pass

    async def _keep_alive_loop(self):
        """Barcha userbotlarni har 5 soniyada PARALLEL ravishda olovdek shay ushlab turish."""
        while True:
            await asyncio.sleep(5)
            if not self.clients:
                continue

            # Barcha mijozlarni navbat kutmasdan bir zumda parallel pinglash
            tasks = [
                self._ping_single_client(client)
                for client in list(self.clients.values())
                if client.is_connected
            ]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def start_user(self, user_id: int, session_string: str) -> bool:
        if user_id in self.clients:
            await self.stop_user(user_id)

        try:
            client = Client(
                name=f"ub_{user_id}",
                api_id=settings.TELEGRAM_API_ID,
                api_hash=settings.TELEGRAM_API_HASH,
                session_string=session_string,
                in_memory=True
            )

            self._attach_handlers(client, user_id)
            await client.start()
            self.clients[user_id] = client
            logger.info(f"✅ Userbot ishga tushdi: User ID {user_id}")

            await self._start_keepalive_if_needed()
            return True

        except (AuthKeyUnregistered, UserDeactivated, SessionRevoked, SessionExpired) as e:
            logger.warning(f"Akkaunt sessiyasi yaroqsiz: {user_id} - {e}")
            await self.mark_session_inactive(user_id)
            return False
        except Exception as e:
            logger.error(f"Userbotni ishga tushirishda xatolik ({user_id}): {e}")
            return False

    async def stop_user(self, user_id: int):
        client = self.clients.pop(user_id, None)
        if client:
            try:
                if client.is_connected:
                    await client.stop()
                logger.info(f"🛑 Userbot to'xtatildi: User ID {user_id}")
            except Exception as e:
                logger.error(f"To'xtatishda xatolik ({user_id}): {e}")

    async def mark_session_inactive(self, user_id: int):
        async with async_session() as session:
            stmt = select(UserbotSession).where(UserbotSession.user_id == user_id)
            user_sess = (await session.execute(stmt)).scalar_one_or_none()
            if user_sess:
                user_sess.is_active = False
                await session.commit()

    async def handle_revoked_session(self, user_id: int, bot: Bot):
        await self.stop_user(user_id)
        await self.mark_session_inactive(user_id)

        try:
            builder = InlineKeyboardBuilder()
            builder.button(text="🔌 Userbotni qayta ulash", callback_data="connect_userbot")
            builder.button(text="⬅️ Bosh menyu", callback_data="back_to_main")
            builder.adjust(1, 1)

            text = (
                "⚠️ <b>Diqqat! Userbot faoliyati to'xtatildi!</b>\n\n"
                "Siz Telegram hisobingizdagi <b>«Qurilmalar» (Faol seanslar)</b> bo'limidan "
                "userbot sessiyasini chiqarib yubordingiz.\n\n"
                "🔒 <i>Iltimos, userbotni hisobingizdan chiqarib yubormang! "
                "Xizmatimiz to'liq shifrlangan va mutlaqo xavfsiz.</i>\n\n"
                "Userbotni qayta faollashtirish uchun quyidagi tugmani bosing 👇"
            )
            await bot.send_message(chat_id=user_id, text=text, reply_markup=builder.as_markup(), parse_mode="HTML")
            logger.info(f"Seans o'chirilganligi haqida foydalanuvchiga xabar yuborildi: {user_id}")
        except Exception as e:
            logger.warning(f"Ogohlantirish yuborishda xatolik ({user_id}): {e}")

    async def verify_active_sessions(self, bot: Bot):
        for user_id, client in list(self.clients.items()):
            try:
                if not client.is_connected:
                    continue
                await client.get_me()
            except (AuthKeyUnregistered, UserDeactivated, SessionRevoked, SessionExpired):
                logger.warning(f"Foydalanuvchi seansni o'chirib yuborgan: {user_id}")
                await self.handle_revoked_session(user_id, bot)
            except Exception:
                pass

    async def start_all_active_users(self):
        logger.info("🔄 Faol userbot sessiyalari bazadan tekshirilmoqda...")
        now = datetime.utcnow()

        async with async_session() as session:
            stmt = select(UserbotSession).where(UserbotSession.is_active == True)
            sessions = (await session.execute(stmt)).scalars().all()

            for s in sessions:
                sub_stmt = select(Subscription).where(
                    Subscription.user_id == s.user_id,
                    Subscription.status == SubscriptionStatus.ACTIVE,
                    Subscription.expires_at > now
                )
                active_sub = (await session.execute(sub_stmt)).scalars().first()

                if not active_sub:
                    continue

                try:
                    decrypted_session = decrypt_session(s.encrypted_session)
                    await self.start_user(s.user_id, decrypted_session)
                except Exception as e:
                    logger.error(f"Sessiyani tiklashda xatolik ({s.user_id}): {e}")

        logger.info(f"🚀 Jami {len(self.clients)} ta userbot muvaffaqiyatli ishga tushirildi!")
        await self._start_keepalive_if_needed()

    async def stop_all(self):
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()

        for user_id in list(self.clients.keys()):
            await self.stop_user(user_id)

client_manager = ClientManager()
