import asyncio
import logging
from typing import Dict, Any, Set
from hydrogram import Client, filters
from hydrogram.types import Message
from hydrogram.raw.types import UpdateNewChannelMessage, Message as RawMessage, PeerChannel
from hydrogram.raw.functions.channels import GetFullChannel
from hydrogram.errors import FloodWait, ChatWriteForbidden
from sqlalchemy import select

from core.database import async_session
from database.models import UserbotSettings

logger = logging.getLogger(__name__)

# user_id -> config
USER_COMMENT_CACHE: Dict[int, Dict[str, Any]] = {}

# Guruh ID -> Kanal ID (faqat raqamlar: 123456789)
GROUP_TO_CHANNEL: Dict[int, int] = {}
CHANNEL_TO_GROUP: Dict[int, int] = {}

# Takroriy postlar: {post_id, ...}
PROCESSED_POSTS: Set[int] = set()

def normalize_id(peer_id: int) -> int:
    """-100 bilan boshlanadigan ID lardan prefiksni olib tashlash."""
    s = str(peer_id)
    if s.startswith("-100"):
        return int(s[4:])
    if s.startswith("-"):
        return int(s[1:])
    return abs(peer_id)

async def pre_cache_channels(client: Client, targets: list):
    """Post chiqishini kutmasdan, kanallar va ularning muhokama guruhlarini oldindan xotiraga olish."""
    for target in targets:
        try:
            peer = await client.resolve_peer(target)
            full_chat = await client.invoke(GetFullChannel(channel=peer))
            
            c_id = normalize_id(peer.channel_id if hasattr(peer, "channel_id") else 0)
            linked_chat_id = getattr(full_chat.full_chat, "linked_chat_id", None)
            
            if linked_chat_id:
                g_id = normalize_id(linked_chat_id)
                GROUP_TO_CHANNEL[g_id] = c_id
                CHANNEL_TO_GROUP[c_id] = g_id
                logger.info(f"✅ [SNIPER PRE-CACHE] Kanal: {target} ({c_id}) ➡️ Muhokama guruhi: ({g_id}) bog'landi!")
            else:
                logger.warning(f"⚠️ [OGOHLANTIRISH] {target} kanaliga muhokama guruhi ulanmagan!")
        except Exception as e:
            logger.warning(f"Pre-cache xatosi ({target}): {e}")

async def load_user_settings(user_id: int, client: Client = None) -> Dict[str, Any]:
    async with async_session() as session:
        stmt = select(UserbotSettings).where(UserbotSettings.user_id == user_id)
        settings = (await session.execute(stmt)).scalar_one_or_none()

        if settings:
            targets = [ch.lower().replace("@", "").strip() for ch in (settings.target_channels or [])]
            config = {
                "enabled": settings.auto_comment_enabled,
                "text": settings.comment_text,
                "delay": settings.comment_delay,
                "targets": targets
            }
        else:
            config = {"enabled": False, "text": "Zo'r post! 👍", "delay": 0, "targets": []}

        USER_COMMENT_CACHE[user_id] = config

        if client and client.is_connected and config["enabled"]:
            await pre_cache_channels(client, config["targets"])

        return config

def register_auto_comment(client: Client, user_id: int):
    """Telethon skriptidagi kabi RAW UPDATE orqali to'g'ridan-to'g'ri guruh oqimini tutish."""

    # 1. ASOSIY QUVVAT: RAW MTPROTO UPDATE (Telethon skripti kabi 0 ms kechikish)
    @client.on_raw_update()
    async def raw_update_dispatcher(c: Client, update, users, chats):
        global PROCESSED_POSTS

        if not isinstance(update, UpdateNewChannelMessage):
            return

        raw_msg = update.message
        if not isinstance(raw_msg, RawMessage):
            return

        # Guruh ID sini olish
        peer_id = getattr(raw_msg.peer_id, "channel_id", None)
        if not peer_id:
            return

        g_id = normalize_id(peer_id)
        if g_id not in GROUP_TO_CHANNEL:
            return

        target_c_id = GROUP_TO_CHANNEL[g_id]

        # Xabar kanaldan forward bo'lib guruhga tushganini tekshirish
        fwd_from = getattr(raw_msg, "fwd_from", None)
        fwd_channel_id = None
        if fwd_from and getattr(fwd_from, "from_id", None):
            if isinstance(fwd_from.from_id, PeerChannel):
                fwd_channel_id = normalize_id(fwd_from.from_id.channel_id)

        from_id_channel = None
        if getattr(raw_msg, "from_id", None) and isinstance(raw_msg.from_id, PeerChannel):
            from_id_channel = normalize_id(raw_msg.from_id.channel_id)

        is_target_post = (fwd_channel_id == target_c_id) or (from_id_channel == target_c_id)
        if not is_target_post:
            return

        # Post ID
        post_id = getattr(fwd_from, "channel_post", raw_msg.id)
        if post_id in PROCESSED_POSTS:
            return
        PROCESSED_POSTS.add(post_id)

        config = USER_COMMENT_CACHE.get(user_id)
        if not config or not config.get("enabled"):
            return

        delay = config.get("delay", 0)
        if delay > 0:
            await asyncio.sleep(delay)

        comment_text = config.get("text", "Ajoyib!")

        try:
            # GURUH ICHIDA TO'G'RIDAN-TO'G'RI POSTGA NUQTA OTISH
            target_chat_full_id = int(f"-100{g_id}")
            dot_msg = await c.send_message(
                chat_id=target_chat_full_id,
                text=".",
                reply_to_message_id=raw_msg.id
            )
            logger.info(f"🔥 [RAW SNIPER G'OLIB] User: {user_id} -> Guruh ({g_id}) post #{post_id} ga nuqta urildi!")

            # Nuqtani haqiqiy matnga aylantirish
            if comment_text != ".":
                async def _edit_bg(msg_obj, text):
                    try:
                        await asyncio.sleep(0.3)
                        await msg_obj.edit_text(text)
                        logger.info(f"✏️ [EDIT] Matn muvaffaqiyatli tahrirlandi!")
                    except Exception:
                        pass
                asyncio.create_task(_edit_bg(dot_msg, comment_text))

        except FloodWait as e:
            logger.warning(f"FloodWait ({user_id}): {e.value}s")
        except ChatWriteForbidden:
            logger.warning(f"Guruhda yozish taqiqlangan ({g_id})")
        except Exception as e:
            logger.error(f"Raw zarba xatosi: {e}")

    # 2. ZAXIRA KANAL OQIMI
    @client.on_message(filters.channel)
    async def channel_post_fallback(c: Client, m: Message):
        global PROCESSED_POSTS
        config = USER_COMMENT_CACHE.get(user_id)
        if not config:
            config = await load_user_settings(user_id, c)

        if not config.get("enabled"):
            return

        c_name = (m.chat.username or "").lower()
        if c_name not in config.get("targets", []):
            return

        if m.id in PROCESSED_POSTS:
            return

        # Agar RAW ushlay olmagan bo'lsa, zaxira urinish
        await asyncio.sleep(0.15)
        if m.id in PROCESSED_POSTS:
            return

        try:
            disc = await c.get_discussion_message(m.chat.id, m.id)
            if disc and m.id not in PROCESSED_POSTS:
                PROCESSED_POSTS.add(m.id)
                dot = await disc.reply(".")
                if config.get("text") != ".":
                    async def _edit(msg_obj, t):
                        await asyncio.sleep(0.3)
                        await msg_obj.edit_text(t)
                    asyncio.create_task(_edit(dot, config.get("text")))
        except Exception:
            pass
