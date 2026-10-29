import asyncio
import logging
from typing import Dict, Any, Set
from hydrogram import Client, filters
from hydrogram.types import Message
from hydrogram.errors import FloodWait, ChatWriteForbidden
from sqlalchemy import select

from core.database import async_session
from database.models import UserbotSettings

logger = logging.getLogger(__name__)

# Foydalanuvchi sozlamalari keshi: user_id -> config
USER_COMMENT_CACHE: Dict[int, Dict[str, Any]] = {}

# Kanal ID -> Guruh ID xaritasi (O'sha skriptdagi GROUPS_MAP kabi)
CHANNEL_TO_GROUP: Dict[int, int] = {}
GROUP_TO_CHANNEL: Dict[int, int] = {}

# Bitta postga qayta yozmaslik uchun: {post_id, ...}
PROCESSED_POSTS: Set[int] = set()

async def resolve_channel_and_group(client: Client, channel_username_or_id: str):
    """Kanal va uning muhokama guruhini oldindan bog'lab xotiraga olish."""
    try:
        chat = await client.get_chat(channel_username_or_id)
        c_id = chat.id

        # Agar bog'langan muhokama guruhi bo'lsa
        if chat.linked_chat:
            g_id = chat.linked_chat.id
            CHANNEL_TO_GROUP[c_id] = g_id
            GROUP_TO_CHANNEL[g_id] = c_id
            logger.info(f"🎯 [KESH BOG'LANDI] Kanal: {chat.title} ({c_id}) ➡️ Guruh: ({g_id})")
            return c_id, g_id
    except Exception as e:
        logger.warning(f"Kanal/guruhni bog'lashda xatolik ({channel_username_or_id}): {e}")
    return None, None

async def load_user_settings(user_id: int, client: Client = None) -> Dict[str, Any]:
    async with async_session() as session:
        stmt = select(UserbotSettings).where(UserbotSettings.user_id == user_id)
        settings = (await session.execute(stmt)).scalar_one_or_none()

        if settings:
            raw_targets = [ch.lower().replace("@", "").strip() for ch in (settings.target_channels or [])]
            config = {
                "enabled": settings.auto_comment_enabled,
                "text": settings.comment_text,
                "delay": settings.comment_delay,
                "targets": raw_targets
            }
        else:
            config = {
                "enabled": False,
                "text": "Zo'r post! 👍",
                "delay": 0,
                "targets": []
            }

        USER_COMMENT_CACHE[user_id] = config

        # Nishondagi barcha kanallarning guruhlarini oldindan keshga yuklash
        if client and client.is_connected and config.get("enabled"):
            for ch in config.get("targets", []):
                await resolve_channel_and_group(client, ch)

        return config

def register_auto_comment(client: Client, user_id: int):
    """Sizning 5 talik skriptingiz kabi to'g'ridan-to'g'ri GURUH oqimidan tutuvchi snayper."""

    # 1-OQIM: GURUH OQIMI (ASOSIY VA ENG TEZKOR ZARBA)
    @client.on_message(filters.group)
    async def group_post_listener(c: Client, m: Message):
        global PROCESSED_POSTS

        config = USER_COMMENT_CACHE.get(user_id)
        if not config or not config.get("enabled"):
            return

        # Ushbu guruh nishondagi kanallardan biriga tegishlimi?
        grp_id = m.chat.id
        if grp_id not in GROUP_TO_CHANNEL:
            return

        target_channel_id = GROUP_TO_CHANNEL[grp_id]

        # Bu xabar kanaldan guruhga tushgan post ekanligini tekshirish
        is_channel_post = False
        post_id = m.id

        if m.forward_from_chat and m.forward_from_chat.id == target_channel_id:
            is_channel_post = True
            post_id = m.forward_from_message_id or m.id
        elif m.sender_chat and m.sender_chat.id == target_channel_id:
            is_channel_post = True

        if not is_channel_post:
            return

        # Takroriy zarbani tekshirish
        if post_id in PROCESSED_POSTS:
            return
        PROCESSED_POSTS.add(post_id)

        delay = config.get("delay", 0)
        if delay > 0:
            await asyncio.sleep(delay)

        comment_text = config.get("text", "Ajoyib!")

        try:
            # GURUH ICHIDA TO'G'RIDAN-TO'G'RI POSTGA ZARBA! (0 ms kechikish, get_discussion_message YO'Q!)
            dot_msg = await m.reply(".")
            logger.info(f"🔥 [SNIPER GURUHDA URDILDI] User: {user_id} -> Guruh: {m.chat.title} (#{m.id}) ga nuqta urdi!")

            async def _edit_bg(target_msg, new_text):
                try:
                    await asyncio.sleep(0.3)
                    await target_msg.edit_text(new_text)
                    logger.info(f"✏️ [EDIT] Nuqta matnga tahrirlandi: '{new_text[:30]}...'")
                except Exception:
                    pass

            if comment_text != ".":
                asyncio.create_task(_edit_bg(dot_msg, comment_text))

        except FloodWait as e:
            logger.warning(f"FloodWait ({user_id}): {e.value}s")
        except ChatWriteForbidden:
            logger.warning(f"Guruhda yozish taqiqlangan: {m.chat.title}")
        except Exception as e:
            logger.error(f"Guruh snayper xatosi: {e}")

    # 2-OQIM: KANAL OQIMI (ZAXIRA QUVVATI)
    @client.on_message(filters.channel)
    async def channel_post_listener(c: Client, m: Message):
        global PROCESSED_POSTS

        config = USER_COMMENT_CACHE.get(user_id)
        if not config:
            config = await load_user_settings(user_id, c)

        if not config.get("enabled"):
            return

        chat = m.chat
        chat_username = (chat.username or "").lower()
        target_channels = config.get("targets", [])

        if chat_username not in target_channels and str(chat.id) not in target_channels:
            return

        # Agar guruh oqimi allaqachon urgan bo'lsa o'tkazib yuboradi
        if m.id in PROCESSED_POSTS:
            return

        # Muhokama guruhini keshda yangilash
        if chat.id not in CHANNEL_TO_GROUP:
            await resolve_channel_and_group(c, chat.id)

        grp_id = CHANNEL_TO_GROUP.get(chat.id)
        if not grp_id:
            return

        try:
            # Kanal orqali ham urinib ko'rish (zaxira)
            disc = await c.get_discussion_message(chat.id, m.id)
            if disc and m.id not in PROCESSED_POSTS:
                PROCESSED_POSTS.add(m.id)
                dot_msg = await disc.reply(".")
                if config.get("text") != ".":
                    async def _edit_bg(target_msg, new_text):
                        await asyncio.sleep(0.3)
                        await target_msg.edit_text(new_text)
                    asyncio.create_task(_edit_bg(dot_msg, config.get("text")))
        except Exception:
            pass
