from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

def main_menu_kb(has_session: bool, is_vip: bool) -> InlineKeyboardMarkup:
    """Asosiy menyu klaviaturasi."""
    builder = InlineKeyboardBuilder()

    # 1-qator: Userbot holati
    if not has_session:
        builder.button(text="🔌 Userbotni ulash", callback_data="connect_userbot")
    else:
        builder.button(text="🟢 Userbot boshqaruvi", callback_data="manage_userbot")

    # 2-qator: Obuna
    if not is_vip:
        builder.button(text="🎁 Bepul Trial olish (1 kun)", callback_data="claim_trial")
        builder.button(text="💎 VIP Obuna sotib olish", callback_data="buy_vip")
    else:
        builder.button(text="⭐ VIP Obunani uzaytirish", callback_data="buy_vip")

    # 3-qator: Sozlamalar va Qo'llanma
    builder.button(text="⚙️ Sozlamalar", callback_data="settings_menu")
    builder.button(text="📖 Buyruqlar qo'llanmasi", callback_data="commands_guide")

    # 4-qator: Taklif va shikoyatlar
    builder.button(text="📩 Taklif va shikoyatlar", callback_data="feedback_menu")

    builder.adjust(1, 1 if is_vip else 2, 2, 1)
    return builder.as_markup()

def feedback_kb() -> InlineKeyboardMarkup:
    """Dasturchiga to'g'ridan-to'g'ri bog'lanish tugmasi."""
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Dasturchiga yozish (@zsrov)", url="https://t.me/zsrov")
    builder.button(text="⬅️ Bosh menyu", callback_data="back_to_main")
    builder.adjust(1, 1)
    return builder.as_markup()

def subscription_plans_kb() -> InlineKeyboardMarkup:
    """VIP obuna tariflari."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⚡ 1 kunlik VIP — 5 000 so'm", callback_data="plan_pay_1")
    builder.button(text="⚡ 7 kunlik VIP — 15 000 so'm", callback_data="plan_pay_7")
    builder.button(text="⚡ 15 kunlik VIP — 25 000 so'm", callback_data="plan_pay_15")
    builder.button(text="⬅️ Orqaga", callback_data="back_to_main")
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()

def payment_action_kb() -> InlineKeyboardMarkup:
    """To'lov sahifasidagi tugmalar."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📤 Chekni @zsrov ga yuborish", url="https://t.me/zsrov")
    builder.button(text="⬅️ Boshqa tarif tanlash", callback_data="buy_vip")
    builder.adjust(1, 1)
    return builder.as_markup()

def cancel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Bekor qilish", callback_data="cancel_action")
    return builder.as_markup()
