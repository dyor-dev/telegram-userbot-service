import asyncio
import logging
from typing import Dict, Any
from hydrogram import Client, filters
from hydrogram.types import Message
from hydrogram.errors import FloodWait, MsgIdInvalid, ChatWriteForbidden
from sqlalchemy import select

from core.database import async_session
from database.models import UserbotSettings

logger = logging.getLogger(__name__)

# Maksimal tezlik uchun xotiradagi tezkor kesh: user_id -> sozlamalar
USER_COMMENT_CACHE: Dict[int, Dict[str, Any]] = {}

async def load_user_settings(user_id: int) -> Dict[str, Any]:
    """Foydalanuvchi avto-komment sozlamalarini bazadan xotiraga yuklash."""
    async with async_session() as session:
        stmt = select(UserbotSettings).where(UserbotSettings.user_id == user_id)
        settings = (await session.execute(stmt)).scalar_one_or_none()

        if settings:
            config = {
                "enabled": settings.auto_comment_enabled,
                "text": settings.comment_text,
                "delay": settings.comment_delay,
                "targets": [ch.lower().replace("@", "").strip() for ch in (settings.target_channels or [])]
            }
        else:
            config = {
                "enabled": False,
                "text": "Zo'r post! 👍",
                "delay": 0,
                "targets": []
            }

        USER_COMMENT_CACHE[user_id] = config
        return config

def register_auto_comment(client: Client, user_id: int):
    """Userbot mijoziga kanal postlarini kuzatish va tezkor izoh yozish vazifasini biriktirish."""

    @client.on_message(filters.channel)
    async def channel_post_listener(c: Client, m: Message):
        # Tezkor keshdan sozlamalarni olish
        config = USER_COMMENT_CACHE.get(user_id)
        if not config:
            config = await load_user_settings(user_id)

        # Agar avto-komment o'chirilgan bo'lsa, hech narsa qilmaydi
        if not config.get("enabled"):
            return

        chat = m.chat
        chat_username = (chat.username or "").lower()
        chat_id_str = str(chat.id)

        target_channels = config.get("targets", [])

        # Post chiqqan kanal foydalanuvchi nishoniga kiritilganmi tekshirish
        is_target = False
        if chat_username and chat_username in target_channels:
            is_target = True
        elif chat_id_str in target_channels:
            is_target = True

        if not is_target:
            return

        # Belgilangan kechikish (agar foydalanuvchi 0 qo'ygan bo'lsa, zudlik bilan ishlaydi)
        delay = config.get("delay", 0)
        if delay > 0:
            await asyncio.sleep(delay)

        comment_text = config.get("text", "Ajoyib!")

        # Muhokama guruhiga post bo'yicha chaqmoqdek tez javob yuborish
        try:
            discussion_msg = await c.get_discussion_message(chat.id, m.id)
            await discussion_msg.reply(comment_text)
            logger.info(f"⚡ [Tezkor Komment] Akkaunt: {user_id} -> Kanal: {chat.title} ({m.id}) ga izoh yozildi!")
        except FloodWait as e:
            logger.warning(f"FloodWait cheklovi ({user_id}): {e.value} soniya kutish kerak.")
        except MsgIdInvalid:
            # Kanal postida muhokama (izohlar) ochilmagan bo'lishi mumkin
            pass
        except ChatWriteForbidden:
            logger.warning(f"Kanal muhokama guruhida yozish taqiqlangan: {chat.title}")
        except Exception as e:
            logger.error(f"Avto-komment yozishda xatolik ({user_id}): {e}")
