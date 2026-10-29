import os
import time
import random
import logging
from hydrogram import Client, filters
from hydrogram.types import Message
from hydrogram import types as high_types
from hydrogram.enums import ParseMode
from hydrogram.raw.functions import Ping
from hydrogram.raw import functions, types

logger = logging.getLogger(__name__)

def register_commands(client: Client):
    """Mijoz akkauntiga maxsus buyruqlarni biriktirish."""

    @client.on_message((filters.me | filters.outgoing) & filters.text)
    async def handle_userbot_commands(c: Client, m: Message):
        text = (m.text or "").strip()

        # 1. QISQA .ping BUYRUG'I
        if text.lower() == ".ping":
            start = time.perf_counter()
            try:
                await c.invoke(Ping(ping_id=random.randint(1, 2147483647)))
            except Exception:
                pass
            end = time.perf_counter()
            delta_ms = round((end - start) * 1000, 1)

            await m.edit_text(
                f"🏓 <b>Pong!</b> <code>{delta_ms} ms</code>\n"
                f"🤖 <b>Userbot:</b> 🟢 <i>Faol</i>",
                parse_mode=ParseMode.HTML
            )
            return

        # 2. .info BUYRUG'I
        elif text.lower() == ".info":
            me = await c.get_me()
            info_text = (
                f"👤 <b>Userbot Ma'lumotlari:</b>\n\n"
                f"• Ism: <b>{me.first_name}</b>\n"
                f"• ID: <code>{me.id}</code>\n"
                f"• Username: @{me.username or 'mavjud emas'}\n"
                f"• Premium: {'⭐ Ha' if me.is_premium else 'Oddiy'}\n"
                f"• Tizim: <b>SaaS Userbot Service (v2.0 Turbo)</b>"
            )
            await m.edit_text(info_text, parse_mode=ParseMode.HTML)
            return

        # 3. .del BUYRUG'I (Barcha o'z xabarlarini va buyruqning o'zini tozalash)
        elif text.lower() == ".del":
            chat_id = m.chat.id
            try:
                me = await c.get_me()
                ids_to_delete = [m.id]

                # Oxirgi 100 ta xabar ichidan akkaunt egasining xabarlarini yig'ish
                async for message in c.get_chat_history(chat_id, limit=100):
                    if (message.from_user and message.from_user.id == me.id) or message.outgoing:
                        ids_to_delete.append(message.id)

                # Xabarlarni bittada o'chirish (Telegram limitiga mos 100 talik paketlarda)
                if ids_to_delete:
                    # Takrorlanmas ID larni ajratish
                    unique_ids = list(set(ids_to_delete))
                    for i in range(0, len(unique_ids), 100):
                        chunk = unique_ids[i:i + 100]
                        await c.delete_messages(chat_id=chat_id, message_ids=chunk)
            except Exception as e:
                logger.error(f"Error in .del command: {e}")
                try:
                    await m.delete()
                except Exception:
                    pass
            return

        # 4. .ok BUYRUG'I (Bir martalik mediani izsiz saqlash)
        elif text.lower().startswith(".ok"):
            target = m.reply_to_message
            if not target:
                await m.delete()
                return

            has_media = bool(target.photo or target.video or target.voice or target.video_note or target.document)
            if not has_media:
                await m.delete()
                return

            try:
                file_path = await target.download()
                if file_path:
                    caption = (
                        "🔒 <b>Maxfiy (o'z-o'zidan o'chuvchi) media saqlandi!</b>\n\n"
                        f"👤 <b>Yuboruvchi:</b> {target.from_user.mention if target.from_user else 'Nomaʼlum'}\n"
                        f"📅 <b>Vaqt:</b> <code>{target.date.strftime('%Y-%m-%d %H:%M:%S')}</code>"
                    )

                    if target.photo:
                        await c.send_photo("me", file_path, caption=caption, parse_mode=ParseMode.HTML)
                    elif target.video:
                        await c.send_video("me", file_path, caption=caption, parse_mode=ParseMode.HTML)
                    elif target.voice:
                        await c.send_voice("me", file_path, caption=caption, parse_mode=ParseMode.HTML)
                    elif target.video_note:
                        await c.send_video_note("me", file_path)
                    elif target.document:
                        await c.send_document("me", file_path, caption=caption, parse_mode=ParseMode.HTML)

                    if os.path.exists(file_path):
                        os.remove(file_path)

            except Exception as e:
                logger.error(f"Error downloading media: {e}")
            finally:
                try:
                    await m.delete()
                except Exception:
                    pass
            return

        # 5. .dw @username BUYRUG'I (Anonim hikoyalar)
        elif text.lower().startswith(".dw"):
            args = text.split()
            if len(args) < 2:
                await m.edit_text("⚠️ <b>Foydalanish:</b> <code>.dw @username</code>\nMasalan: <code>.dw @durov</code>", parse_mode=ParseMode.HTML)
                return

            target_username = args[1].replace("@", "").strip()
            msg = await m.edit_text(f"🔍 <b>@{target_username}</b> hikoyalari anonim yuklanmoqda...", parse_mode=ParseMode.HTML)

            try:
                peer = await c.resolve_peer(target_username)

                peer_stories = await c.invoke(functions.stories.GetPeerStories(peer=peer))

                story_ids = []
                if hasattr(peer_stories, "stories") and hasattr(peer_stories.stories, "stories"):
                    story_ids = [s.id for s in peer_stories.stories.stories if hasattr(s, "id")]

                if not story_ids:
                    await msg.edit_text(f"ℹ️ <b>@{target_username}</b> hisobida faol hikoyalar (Stories) topilmadi yoki hisob yopiq.", parse_mode=ParseMode.HTML)
                    return

                stories_res = await c.invoke(functions.stories.GetStoriesByID(peer=peer, id=story_ids))
                raw_stories = getattr(stories_res, "stories", [])

                count = 0
                for item in raw_stories:
                    if not hasattr(item, "media") or not item.media:
                        continue

                    media_obj = item.media
                    parsed_file = None
                    is_video = False
                    target_ext = "jpg"

                    if isinstance(media_obj, types.MessageMediaDocument) and media_obj.document:
                        doc = media_obj.document
                        parsed_file = high_types.Document._parse(c, doc, "story.mp4")
                        is_video = True
                        target_ext = "mp4"
                    elif isinstance(media_obj, types.MessageMediaPhoto) and media_obj.photo:
                        parsed_file = high_types.Photo._parse(c, media_obj.photo)
                        is_video = False
                        target_ext = "jpg"

                    if not parsed_file or not getattr(parsed_file, "file_id", None):
                        continue

                    try:
                        custom_filename = f"downloads/story_{item.id}_{int(time.time())}.{target_ext}"
                        file_path = await c.download_media(parsed_file.file_id, file_name=custom_filename)

                        if file_path and os.path.exists(file_path):
                            caption = (
                                f"👁‍🗨 <b>Anonim ko'rilgan hikoya (Story)</b>\n\n"
                                f"👤 <b>Egasi:</b> @{target_username}\n"
                                f"🆔 <b>Story ID:</b> <code>{getattr(item, 'id', '')}</code>\n"
                                "<i>(Egasiga siz ko'rganingiz mutlaqo ko'rinmaydi)</i>"
                            )

                            if is_video:
                                await c.send_video("me", file_path, caption=caption, parse_mode=ParseMode.HTML)
                            else:
                                await c.send_photo("me", file_path, caption=caption, parse_mode=ParseMode.HTML)

                            if os.path.exists(file_path):
                                os.remove(file_path)
                            count += 1
                    except Exception as download_err:
                        logger.warning(f"Bitta hikoyani yuklashda xatolik: {download_err}")

                if count > 0:
                    await msg.edit_text(f"✅ <b>@{target_username}</b>ning {count} ta hikoyasi «Saqlangan xabarlar»ingizga tashlandi!", parse_mode=ParseMode.HTML)
                else:
                    await msg.edit_text(f"ℹ️ <b>@{target_username}</b> hisobidagi hikoyalarni yuklab bo'lmadi.", parse_mode=ParseMode.HTML)

            except Exception as e:
                logger.error(f"Story error: {e}")
                await msg.edit_text(f"❌ Xatolik yuz berdi: {str(e)}", parse_mode=ParseMode.HTML)
            return
