from aiogram.fsm.state import State, StatesGroup

class AuthStates(StatesGroup):
    waiting_for_phone = State()     # Telefon raqam kiritilishini kutish
    waiting_for_code = State()      # Telegram yuborgan tasdiqlash kodini kutish
    waiting_for_password = State()  # 2FA (ikki bosqichli parol) kiritilishini kutish

class SettingsStates(StatesGroup):
    waiting_for_comment_text = State()   # Avto-komment matnini kiritish
    waiting_for_comment_delay = State()  # Izohlar orasidagi vaqt (soniya)
