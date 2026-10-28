from aiogram import Router, F
from aiogram.types import CallbackQuery
from bot.keyboards.inline import payment_action_kb

router = Router()

PLANS_INFO = {
    "plan_pay_1": {"name": "1 kunlik VIP", "price": "5 000"},
    "plan_pay_7": {"name": "7 kunlik VIP", "price": "15 000"},
    "plan_pay_15": {"name": "15 kunlik VIP", "price": "25 000"},
}

@router.callback_query(F.data.startswith("plan_pay_"))
async def process_plan_selection(callback: CallbackQuery):
    plan_key = callback.data
    plan = PLANS_INFO.get(plan_key, {"name": "VIP", "price": "0"})

    text = (
        f"💎 <b>Tanlangan tarif: {plan['name']}</b>\n"
        f"💰 <b>To'lov summasi:</b> <code>{plan['price']}</code> so'm\n\n"
        "💳 <b>To'lov uchun karta raqami:</b>\n"
        "👉 <code>9860356650154046</code>\n"
        "👤 <b>Karta egasi:</b> <b>I.D</b>\n"
        "<i>(Karta raqami ustiga bir marta bossangiz, avtomatik nusxalanadi)</i>\n\n"
        "⚠️ <b>DIQQAT! TO'LOV CHEKI MAJBURIY!</b>\n\n"
        "To'lovni amalga oshirgach, chekning skrinshotini va o'zingizning Telegram ID raqamingizni "
        "quyidagi tugma orqali <b>@zsrov</b> ga yuboring.\n\n"
        f"🆔 <b>Sizning Telegram ID raqamingiz:</b> <code>{callback.from_user.id}</code>\n\n"
        "<i>Chek tasdiqlangach, VIP obunangiz darhol faollashtiriladi!</i>"
    )

    await callback.message.edit_text(text, reply_markup=payment_action_kb(), parse_mode="HTML")
    await callback.answer()
