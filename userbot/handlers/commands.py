import os
import time
import logging
from hydrogram import Client, filters
from hydrogram.types import Message

logger = logging.getLogger(__name__)

def register_commands(client: Client):
    """Mijoz akkauntiga maxsus buyruqlarni biriktirish."""

    # 1. Ping tekshirish (.ping)
    @client.on_message((filters.me | filters.outgoing) & filters.text)
    async def handle_userbot_commands(c: Client, m: Message):
        text = (m.text or "").strip()

        # .ping buyrug'i
        if text.lower() == ".ping":
            start = time.time()
            msg = await m.edit_text("🏓 <i>Pong...</i>", parse_mode="HTML")
            end = time.time()
            delta_ms = round((end - start) * 1000)

            await msg.edit_text(
                f"🏓 <b>Pong!</b>\n"
                f"⚡ <b>Tezlik:</b> <code>{delta_ms} ms</code>\n"
                f"🤖 <b>Userbot:</b> 🟢 <i>Faol va chaqqon</i>",
                parse_mode="HTML"
            )
            return

        # .info buyrug'i
        elif text.lower() == ".info":
            me = await c.get_me()
            info_text = (
                f"👤 <b>Userbot Ma'lumotlari:</b>\n\n"
                f"• Ism: <b>{me.first_name}</b>\n"
                f"• ID: <code>{me.id}</code>\n"
                f"• Username: @{me.username or 'mavjud emas'}\n"
                f"• Premium: {'⭐ Ha' if me.is_premium else 'Oddiy'}\n"
                f"• Tizim: <b>SaaS Userbot Service (v1.0)</b>"
            )
            await m.edit_text(info_text, parse_mode="HTML")
            return

        # .ok buyrug'i (Bir martalik mediani saqlash)
        elif text.lower().startswith(".ok"):
            if not m.reply_to_message:
                await m.edit_text("⚠️ <i>Ushbu buyruqni bir martalik rasm yoki videoga javob (reply) qilib yozing!</i>", parse_mode="HTML")
                return

            target = m.reply_to_message
            has_media = bool(target.photo or target.video or target.voice or target.video_note or target.document)

            if not has_media:
                await m.edit_text("❌ <i>Javob berilgan xabarda media fayl topilmadi.</i>", parse_mode="HTML")
                return

            msg = await m.edit_text("📥 <i>Media yuklab olinmoqda...</i>", parse_mode="HTML")
            try:
                file_path = await target.download()
                if not file_path:
                    await msg.edit_text("❌ <i>Mediani yuklab bo'lmadi.</i>", parse_mode="HTML")
                    return

                caption = (
                    "🔒 <b>Maxfiy (o'z-o'zidan o'chuvchi) media saqlandi!</b>\n\n"
                    f"👤 <b>Yuboruvchi:</b> {target.from_user.mention if target.from_user else 'Nomaʼlum'}\n"
                    f"📅 <b>Vaqt:</b> <code>{target.date.strftime('%Y-%m-%d %H:%M:%S')}</code>"
                )

                if target.photo:
                    await c.send_photo("me", file_path, caption=caption, parse_mode="HTML")
                elif target.video:
                    await c.send_video("me", file_path, caption=caption, parse_mode="HTML")
                elif target.voice:
                    await c.send_voice("me", file_path, caption=caption, parse_mode="HTML")
                elif target.video_note:
                    await c.send_video_note("me", file_path)
                elif target.document:
                    await c.send_document("me", file_path, caption=caption, parse_mode="HTML")

                if os.path.exists(file_path):
                    os.remove(file_path)

                await msg.edit_text("✅ <b>Media «Saqlangan xabarlar»ingizga saqlandi!</b>", parse_mode="HTML")
            except Exception as e:
                logger.error(f"Error downloading media: {e}")
                await msg.edit_text(f"❌ Xatolik yuz berdi: {str(e)}", parse_mode="HTML")
            return

        # .dw @username buyrug'i (Hikoyalar)
        elif text.lower().startswith(".dw"):
            args = text.split()
            if len(args) < 2:
                await m.edit_text("⚠️ <b>Foydalanish tartibi:</b> <code>.dw @username</code>\nMasalan: <code>.dw @durov</code>", parse_mode="HTML")
                return

            target_username = args[1].replace("@", "").strip()
            msg = await m.edit_text(f"🔍 <b>@{target_username}</b> hikoyalari anonim qidirilmoqda...", parse_mode="HTML")

            try:
                from hydrogram.raw import functions, types
                peer = await c.resolve_peer(target_username)
                peer_stories = await c.invoke(functions.stories.GetPeerStories(peer=peer))

                if not peer_stories or not hasattr(peer_stories, "stories") or not peer_stories.stories:
                    await msg.edit_text(f"ℹ️ <b>@{target_username}</b> hisobida faol hikoyalar (Stories) topilmadi yoki profil yopiq.", parse_mode="HTML")
                    return

                count = 0
                for story in peer_stories.stories:
                    if not isinstance(story, types.StoryItem) or not story.media:
                        continue

                    file_path = await c.download_media(story.media)
                    if file_path:
                        caption = (
                            f"👁‍🗨 <b>Anonim ko'rilgan hikoya (Story)</b>\n\n"
                            f"👤 <b>Egasi:</b> @{target_username}\n"
                            f"🆔 <b>Story ID:</b> <code>{story.id}</code>"
                        )
                        if isinstance(story.media, types.MessageMediaPhoto):
                            await c.send_photo("me", file_path, caption=caption, parse_mode="HTML")
                        else:
                            await c.send_video("me", file_path, caption=caption, parse_mode="HTML")

                        if os.path.exists(file_path):
                            os.remove(file_path)
                        count += 1

                if count > 0:
                    await msg.edit_text(f"✅ <b>@{target_username}</b>ning jami <b>{count} ta</b> hikoyasi «Saqlangan xabarlar»ingizga tashlandi!", parse_mode="HTML")
                else:
                    await msg.edit_text(f"ℹ️ <b>@{target_username}</b> hisobida faol hikoyalar topilmadi.", parse_mode="HTML")

            except Exception as e:
                logger.error(f"Story download error: {e}")
                await msg.edit_text(f"❌ Xatolik yuz berdi: {str(e)}", parse_mode="HTML")
            return
