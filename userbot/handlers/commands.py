import os
import time
import random
import logging
from hydrogram import Client, filters
from hydrogram.types import Message
from hydrogram.enums import ParseMode
from hydrogram.raw.functions import Ping
from hydrogram.raw import functions

logger = logging.getLogger(__name__)

def register_commands(client: Client):
    """Mijoz akkauntiga maxsus buyruqlarni biriktirish."""

    @client.on_message((filters.me | filters.outgoing) & filters.text)
    async def handle_userbot_commands(c: Client, m: Message):
        text = (m.text or "").strip()

        # 1. QISQA VA TOZA .ping BUYRUG'I
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

        # 2. .info buyrug'i
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

        # 3. .ok buyrug'i (Bir martalik mediani IZZSIZ saqlash)
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

        # 4. .dw @username buyrug'i (100% ISHLAYDIGAN HIKOYALAR YUKLOVCHI)
        elif text.lower().startswith(".dw"):
            args = text.split()
            if len(args) < 2:
                await m.edit_text("⚠️ <b>Foydalanish:</b> <code>.dw @username</code>\nMasalan: <code>.dw @durov</code>", parse_mode=ParseMode.HTML)
                return

            target_username = args[1].replace("@", "").strip()
            msg = await m.edit_text(f"🔍 <b>@{target_username}</b> hikoyalari anonim yuklanmoqda...", parse_mode=ParseMode.HTML)

            try:
                # Foydalanuvchini aniqlash
                chat = await c.get_chat(target_username)
                peer = await c.resolve_peer(chat.id)

                # MTProto orqali barcha faol hikoya ID larini olish
                peer_stories = await c.invoke(functions.stories.GetPeerStories(peer=peer))

                story_ids = []
                if hasattr(peer_stories, "stories") and hasattr(peer_stories.stories, "stories"):
                    story_ids = [s.id for s in peer_stories.stories.stories if hasattr(s, "id")]

                if not story_ids:
                    await msg.edit_text(f"ℹ️ <b>@{target_username}</b> hisobida faol hikoyalar (Stories) topilmadi yoki hisob yopiq.", parse_mode=ParseMode.HTML)
                    return

                # Hikoyalarni rasmiy yuqori darajadagi API orqali olish (File_ID va DC xatolarisiz)
                stories = await c.get_stories(chat_id=chat.id, story_ids=story_ids)
                if not isinstance(stories, list):
                    stories = [stories]

                count = 0
                for story in stories:
                    if not story or not (story.photo or story.video):
                        continue

                    try:
                        file_path = await c.download_media(story)
                        if file_path:
                            caption = (
                                f"👁‍🗨 <b>Anonim ko'rilgan hikoya (Story)</b>\n\n"
                                f"👤 <b>Egasi:</b> @{target_username}\n"
                                f"🆔 <b>Story ID:</b> <code>{story.id}</code>\n"
                                "<i>(Egasiga siz ko'rganingiz mutlaqo ko'rinmaydi)</i>"
                            )

                            if story.photo:
                                await c.send_photo("me", file_path, caption=caption, parse_mode=ParseMode.HTML)
                            elif story.video:
                                await c.send_video("me", file_path, caption=caption, parse_mode=ParseMode.HTML)

                            if os.path.exists(file_path):
                                os.remove(file_path)
                            count += 1
                    except Exception as single_err:
                        logger.warning(f"Hikoyani yuklashda xatolik: {single_err}")

                if count > 0:
                    await msg.edit_text(f"✅ <b>@{target_username}</b>ning {count} ta hikoyasi «Saqlangan xabarlar»ingizga tashlandi!", parse_mode=ParseMode.HTML)
                else:
                    await msg.edit_text(f"ℹ️ <b>@{target_username}</b> hisobidagi hikoyalarni yuklab bo'lmadi.", parse_mode=ParseMode.HTML)

            except Exception as e:
                logger.error(f"Story download error: {e}")
                await msg.edit_text(f"❌ Xatolik yuz berdi: {str(e)}", parse_mode=ParseMode.HTML)
            return
