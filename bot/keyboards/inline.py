from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

def main_menu_kb(has_session: bool, is_vip: bool) -> InlineKeyboardMarkup:
    """Asosiy menyu klaviaturasi."""
    builder = InlineKeyboardBuilder()

    # Userbot holatiga qarab tugma
    if not has_session:
        builder.button(text="🔌 Userbotni ulash", callback_data="connect_userbot")
    else:
        builder.button(text="🟢 Userbot boshqaruvi", callback_data="manage_userbot")

    # Obuna holatiga qarab tugma
    if not is_vip:
        builder.button(text="🎁 Bepul Trial olish", callback_data="claim_trial")
        builder.button(text="💎 VIP Obuna sotib olish", callback_data="buy_vip")
    else:
        builder.button(text="⭐ VIP Obunani uzaytirish", callback_data="buy_vip")

    builder.button(text="⚙️ Sozlamalar", callback_data="settings_menu")
    builder.button(text="📖 Buyruqlar qo'llanmasi", callback_data="commands_guide")

    # Qatorlarga bo'lish
    builder.adjust(1, 1 if is_vip else 2, 2)
    return builder.as_markup()

def subscription_plans_kb() -> InlineKeyboardMarkup:
    """VIP obuna tariflari klaviaturasi (Telegram Stars)."""
    builder = InlineKeyboardBuilder()

    # 1 kun, 7 kun, 15 kunlik tariflar
    builder.button(text="⭐ 1 kunlik VIP — 50 Stars", callback_data="plan_vip_1")
    builder.button(text="⭐ 7 kunlik VIP — 250 Stars", callback_data="plan_vip_7")
    builder.button(text="⭐ 15 kunlik VIP — 450 Stars", callback_data="plan_vip_15")
    builder.button(text="⬅️ Orqaga", callback_data="back_to_main")

    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()

def settings_kb(auto_comment: bool, destruct_media: bool) -> InlineKeyboardMarkup:
    """Sozlamalar klaviaturasi."""
    builder = InlineKeyboardBuilder()

    ac_icon = "✅ Yoqilgan" if auto_comment else "❌ O'chirilgan"
    dm_icon = "✅ Yoqilgan" if destruct_media else "❌ O'chirilgan"

    builder.button(text=f"💬 Avto-komment: {ac_icon}", callback_data="toggle_auto_comment")
    builder.button(text="✏️ Komment matnini o'zgartirish", callback_data="edit_comment_text")
    builder.button(text=f"🔥 Maxfiy mediani saqlash (.ok): {dm_icon}", callback_data="toggle_destruct_media")
    builder.button(text="⬅️ Asosiy menyu", callback_data="back_to_main")

    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()

def cancel_kb() -> InlineKeyboardMarkup:
    """Bekor qilish tugmasi."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Bekor qilish", callback_data="cancel_action")
    return builder.as_markup()
