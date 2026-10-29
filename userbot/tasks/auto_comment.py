import asyncio
import logging
from typing import Dict, Any, Set, Tuple
from hydrogram import Client, filters
from hydrogram.types import Message
from hydrogram.errors import FloodWait, MsgIdInvalid, ChatWriteForbidden
from sqlalchemy import select

from core.database import async_session
from database.models import UserbotSettings

logger = logging.getLogger(__name__)

# Maksimal tezlik uchun xotiradagi kesh: user_id -> sozlamalar
USER_COMMENT_CACHE: Dict[int, Dict[str, Any]] = {}

# Bitta postga ikki marta izoh yozmaslik uchun: {(user_id, chat_id, post_id), ...}
PROCESSED_POSTS: Set[Tuple[int, int, int]] = set()

async def load_user_settings(user_id: int) -> Dict[str, Any]:
    """Foydalanuvchi sozlamalarini xotiraga yuklash."""
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
    """Userbotga chaqmoqdek tezkor snayper izoh yozish qobiliyatini biriktirish."""

    @client.on_message(filters.channel)
    async def channel_post_listener(c: Client, m: Message):
        global PROCESSED_POSTS

        # 1. Tezkor keshdan sozlamalarni olish
        config = USER_COMMENT_CACHE.get(user_id)
        if not config:
            config = await load_user_settings(user_id)

        if not config.get("enabled"):
            return

        chat = m.chat
        chat_username = (chat.username or "").lower()
        chat_id_str = str(chat.id)

        target_channels = config.get("targets", [])

        # Post chiqqan kanal nishonda bormi tekshirish
        is_target = False
        if chat_username and chat_username in target_channels:
            is_target = True
        elif chat_id_str in target_channels:
            is_target = True

        if not is_target:
            return

        # 2. Takroriy zarbadan himoya
        post_key = (user_id, chat.id, m.id)
        if post_key in PROCESSED_POSTS:
            return
        PROCESSED_POSTS.add(post_key)

        # Xotirani tozalab turish (10 000 tadan oshib ketsa tozalaydi)
        if len(PROCESSED_POSTS) > 10000:
            PROCESSED_POSTS.clear()

        # Kechikish (agar 0 bo'lsa darhol otiladi)
        delay = config.get("delay", 0)
        if delay > 0:
            await asyncio.sleep(delay)

        comment_text = config.get("text", "Ajoyib!")

        try:
            # Muhokama xabarini olish
            discussion_msg = await c.get_discussion_message(chat.id, m.id)
            if not discussion_msg:
                return

            # ========================================================
            # ⚡ 1-ZARBA: 0.01 soniyada bor-yo'g'i bitta "." (nuqta) otiladi!
            # Bu Telegramda birinchi o'rinni darhol band qiladi!
            # ========================================================
            dot_msg = await discussion_msg.reply(".")
            logger.info(f"⚡ [SNIPER G'OLIB] User: {user_id} -> {chat.title} (#{m.id}) ga nuqta bilan 1-o'rin olindi!")

            # ========================================================
            # ✏️ 2-QADAM: Orqa fonda nuqtani haqiqiy matnga aylantirish
            # ========================================================
            async def _edit_in_background(target_msg, new_text):
                try:
                    await asyncio.sleep(0.3)  # Telegram API barqarorligi uchun 0.3s pauza
                    await target_msg.edit_text(new_text)
                    logger.info(f"✏️ [SNIPER EDIT] User: {user_id} -> Matn muvaffaqiyatli tahrirlandi!")
                except Exception as edit_err:
                    logger.warning(f"Nuqtani tahrirlashda xatolik ({user_id}): {edit_err}")

            if comment_text != ".":
                asyncio.create_task(_edit_in_background(dot_msg, comment_text))

        except FloodWait as e:
            logger.warning(f"FloodWait cheklovi ({user_id}): {e.value} soniya kutilmoqda.")
        except MsgIdInvalid:
            pass  # Kanaldagi postda kommentlar yoqilmagan
        except ChatWriteForbidden:
            logger.warning(f"Kanal muhokama guruhida yozish taqiqlangan: {chat.title}")
        except Exception as e:
            logger.error(f"Snayper izoh yozishda xatolik ({user_id}): {e}")
