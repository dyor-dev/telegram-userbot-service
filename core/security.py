from cryptography.fernet import Fernet
from core.config import settings

def get_cipher() -> Fernet:
    key = settings.SECRET_KEY
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)

def encrypt_session(session_string: str) -> str:
    """Sessiya matnini shifrlab beradi."""
    cipher = get_cipher()
    return cipher.encrypt(session_string.encode()).decode()

def decrypt_session(encrypted_string: str) -> str:
    """Shifrlangan sessiyani qayta ochib beradi."""
    cipher = get_cipher()
    return cipher.decrypt(encrypted_string.encode()).decode()
