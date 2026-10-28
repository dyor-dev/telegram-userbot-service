import logging
from datetime import datetime
from typing import Dict, Optional
from hydrogram import Client
from hydrogram.errors import AuthKeyUnregistered, UserDeactivated, SessionRevoked
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.config import settings
from core.database import async_session
from core.security import decrypt_session
from database.models import UserbotSession, Subscription, SubscriptionStatus

logger = logging.getLogger(__name__)

class ClientManager:
    def __init__(self):
        # user_id -> Client obyektlarini saqlash
        self.clients: Dict[int, Client] = {}

    def _attach_handlers(self, client: Client):
        """Userbot mijoziga buyruqlar va vazifalarni ulash."""
        try:
            from userbot.handlers.commands import register_commands
            register_commands(client)
        except ImportError:
            logger.warning("Commands moduli hali ulanmagan.")

    async def start_user(self, user_id: int, session_string: str) -> bool:
        """Bitta foydalanuvchining userbotini ishga tushirish."""
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

            # Buyruqlarni (.ping, .ok) ulash
            self._attach_handlers(client)

            await client.start()
            self.clients[user_id] = client
            logger.info(f"✅ Userbot ishga tushdi: User ID {user_id}")
            return True

        except (AuthKeyUnregistered, UserDeactivated, SessionRevoked) as e:
            logger.warning(f"Akkaunt sessiyasi yaroqsiz: {user_id} - {e}")
            await self.mark_session_inactive(user_id)
            return False
        except Exception as e:
            logger.error(f"Userbotni ishga tushirishda xatolik ({user_id}): {e}")
            return False

    async def stop_user(self, user_id: int):
        """Bitta foydalanuvchining userbotini to'xtatish."""
        client = self.clients.pop(user_id, None)
        if client:
            try:
                if client.is_connected:
                    await client.stop()
                logger.info(f"🛑 Userbot to'xtatildi: User ID {user_id}")
            except Exception as e:
                logger.error(f"To'xtatishda xatolik ({user_id}): {e}")

    async def mark_session_inactive(self, user_id: int):
        """Yaroqsiz bo'lib qolgan sessiyani bazada nofaol qilish."""
        async with async_session() as session:
            stmt = select(UserbotSession).where(UserbotSession.user_id == user_id)
            user_sess = (await session.execute(stmt)).scalar_one_or_none()
            if user_sess:
                user_sess.is_active = False
                await session.commit()

    async def start_all_active_users(self):
        """Server qayta yoqilganda barcha faol obunasi bor userbotlarni ishga tushirish."""
        logger.info("🔄 Faol userbot sessiyalari bazadan tekshirilmoqda...")
        now = datetime.utcnow()

        async with async_session() as session:
            stmt = select(UserbotSession).where(
                UserbotSession.is_active == True
            )
            sessions = (await session.execute(stmt)).scalars().all()

            for s in sessions:
                # Obunasi bormi yoki yo'qligini tekshiramiz
                sub_stmt = select(Subscription).where(
                    Subscription.user_id == s.user_id,
                    Subscription.status == SubscriptionStatus.ACTIVE,
                    Subscription.expires_at > now
                )
                active_sub = (await session.execute(sub_stmt)).scalars().first()

                if not active_sub:
                    # Obunasi tugagan bo'lsa yoqmaymiz
                    continue

                try:
                    decrypted_session = decrypt_session(s.encrypted_session)
                    await self.start_user(s.user_id, decrypted_session)
                except Exception as e:
                    logger.error(f"Sessiyani tiklashda xatolik ({s.user_id}): {e}")

        logger.info(f"🚀 Jami {len(self.clients)} ta faol userbot muvaffaqiyatli ishga tushirildi!")

    async def stop_all(self):
        """Server to'xtaganda barcha mijozlarni xavfsiz to'xtatish."""
        logger.info("🛑 Barcha userbotlar to'xtatilmoqda...")
        for user_id in list(self.clients.keys()):
            await self.stop_user(user_id)

client_manager = ClientManager()
