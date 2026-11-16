import os
import re
import time
import random
import logging
from hydrogram import Client, filters
from hydrogram.types import Message
from hydrogram import types as high_types
from hydrogram.enums import ParseMode
from hydrogram.raw.functions import Ping
from hydrogram.raw import functions, types
from sqlalchemy import select

from core.database import async_session
from database.models import ScheduledMessage

logger = logging.getLogger(__name__)

def register_commands(client: Client, owner_id: int = None):
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

        # 3. .del BUYRUG'I (O'z xabarlarini tozalash)
        elif text.lower() == ".del":
            chat_id = m.chat.id
            try:
                me = await c.get_me()
                ids_to_delete = [m.id]

                async for message in c.get_chat_history(chat_id, limit=100):
                    if (message.from_user and message.from_user.id == me.id) or message.outgoing:
                        ids_to_delete.append(message.id)

                if ids_to_delete:
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

        # 4. .send BUYRUG'I (Aniq vaqtda xabar yuborish)
        elif text.lower().startswith(".send "):
            # Formatlar:
            # .send @chat 22:55:00 Matn...
            # .send daily @chat 22:55 Matn...
            parts = text.split(None, 4)
            is_daily = False
            
            if len(parts) >= 2 and parts[1].lower() == "daily":
                is_daily = True
                if len(parts) < 5:
                    await m.edit_text(
                        "⚠️ <b>Foydalanish tartibi:</b>\n"
                        "• 1 marta: <code>.send @chat 22:55:00 Salom</code>\n"
                        "• Har kuni: <code>.send daily @chat 09:00:00 Hayrli tong</code>",
                        parse_mode=ParseMode.HTML
                    )
                    return
                target_chat = parts[2]
                raw_time = parts[3]
                msg_text = parts[4]
            else:
                parts_once = text.split(None, 3)
                if len(parts_once) < 4:
                    await m.edit_text(
                        "⚠️ <b>Foydalanish tartibi:</b>\n"
                        "• 1 marta: <code>.send @chat 22:55:00 Salom</code>\n"
                        "• Har kuni: <code>.send daily @chat 09:00:00 Hayrli tong</code>",
                        parse_mode=ParseMode.HTML
                    )
                    return
                target_chat = parts_once[1]
                raw_time = parts_once[2]
                msg_text = parts_once[3]

            # Vaqtni tekshirish (HH:MM yoki HH:MM:SS)
            time_match = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", raw_time.strip())
            if not time_match:
                await m.edit_text("❌ Vaqt noto'g'ri! Format: <code>22:55</code> yoki <code>22:55:00</code>", parse_mode=ParseMode.HTML)
                return

            hh = int(time_match.group(1))
            mm = int(time_match.group(2))
            ss = int(time_match.group(3) or 0)

            if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
                await m.edit_text("❌ Soat 00-23, daqiqa/soniya 00-59 oralig'ida bo'lishi kerak!")
                return

            formatted_time = f"{hh:02d}:{mm:02d}:{ss:02d}"
            uid = owner_id or (await c.get_me()).id

            try:
                from userbot.tasks.scheduled_sender import scheduled_sender
                async with async_session() as session:
                    new_task = ScheduledMessage(
                        user_id=uid,
                        target_chat=target_chat,
                        message_text=msg_text,
                        send_time=formatted_time,
                        is_daily=is_daily,
                        is_active=True
                    )
                    session.add(new_task)
                    await session.commit()
                    await session.refresh(new_task)

                await scheduled_sender.add_or_reload_task(new_task.id)

                rejim = "🔄 Har kuni" if is_daily else "1️⃣ Bir martalik"
                await m.edit_text(
                    f"✅ <b>Rejali xabar saqlandi!</b> (ID: <code>{new_task.id}</code>)\n\n"
                    f"🎯 <b>Chat:</b> <code>{target_chat}</code>\n"
                    f"⏰ <b>Vaqt:</b> <code>{formatted_time}</code> (Toshkent)\n"
                    f"📌 <b>Rejim:</b> {rejim}\n"
                    f"💬 <b>Matn:</b> <i>{msg_text}</i>",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Schedule add error: {e}")
                await m.edit_text(f"❌ Saqlashda xatolik: {str(e)}")
            return

        # 5. .sends BUYRUG'I (Rejali xabarlar ro'yxati)
        elif text.lower() == ".sends":
            uid = owner_id or (await c.get_me()).id
            async with async_session() as session:
                stmt = select(ScheduledMessage).where(
                    ScheduledMessage.user_id == uid,
                    ScheduledMessage.is_active == True
                )
                tasks = (await session.execute(stmt)).scalars().all()

            if not tasks:
                await m.edit_text("ℹ️ Sizda faol rejali xabarlar yo'q.", parse_mode=ParseMode.HTML)
                return

            res = "⏰ <b>Rejalashtirilgan xabarlar ro'yxati:</b>\n\n"
            for t in tasks:
                mode = "🔄 Har kuni" if t.is_daily else "1️⃣ 1 marta"
                res += f"🔹 <b>ID:</b> <code>{t.id}</code> | <code>{t.send_time}</code> ({mode})\n"
                res += f"   🎯 Chat: <code>{t.target_chat}</code>\n"
                res += f"   💬 Matn: <i>{t.message_text[:40]}</i>\n\n"
            res += "<i>O'chirish uchun: <code>.delsend ID</code></i>"
            await m.edit_text(res, parse_mode=ParseMode.HTML)
            return

        # 6. .delsend <id> BUYRUG'I
        elif text.lower().startswith(".delsend "):
            args = text.split()
            if len(args) < 2 or not args[1].isdigit():
                await m.edit_text("⚠️ <b>Foydalanish:</b> <code>.delsend 5</code>", parse_mode=ParseMode.HTML)
                return

            task_id = int(args[1])
            uid = owner_id or (await c.get_me()).id

            from userbot.tasks.scheduled_sender import scheduled_sender
            async with async_session() as session:
                stmt = select(ScheduledMessage).where(
                    ScheduledMessage.id == task_id,
                    ScheduledMessage.user_id == uid
                )
                task = (await session.execute(stmt)).scalar_one_or_none()
                if not task:
                    await m.edit_text(f"❌ <code>{task_id}</code> ID li vazifa topilmadi!", parse_mode=ParseMode.HTML)
                    return
                await session.delete(task)
                await session.commit()

            scheduled_sender.remove_from_cache(task_id)
            await m.edit_text(f"🗑 <b>Rejali xabar (ID: {task_id}) o'chirildi!</b>", parse_mode=ParseMode.HTML)
            return

        # 7. .ok BUYRUG'I (Bir martalik mediani izsiz saqlash)
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

        # 8. .dw @username BUYRUG'I (Anonim hikoyalar)
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
