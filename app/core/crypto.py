import base64
import logging
from cryptography.fernet import Fernet
from app.config import settings

logger = logging.getLogger(__name__)

# Fallback in-memory key for local development when not configured yet
_dev_fallback_key = None


def get_cipher() -> Fernet:
    global _dev_fallback_key
    key = settings.ENCRYPTION_KEY.strip()
    if not key:
        if _dev_fallback_key is None:
            _dev_fallback_key = Fernet.generate_key().decode()
            logger.warning(
                "ENCRYPTION_KEY belum diset di .env! Menggunakan temporary in-memory key untuk dev. "
                "JANGAN gunakan ini di production/Supabase!"
            )
        key = _dev_fallback_key
    try:
        return Fernet(key.encode())
    except Exception as e:
        logger.error(f"Format ENCRYPTION_KEY tidak valid: {e}")
        raise ValueError(
            "ENCRYPTION_KEY harus berupa 32-byte url-safe base64 string. "
            "Generate via: python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )


def encrypt_credential(plain_text: str) -> str:
    """Enkripsi teks kredensial (akun/password/token) sebelum disimpan ke database."""
    cipher = get_cipher()
    encrypted_bytes = cipher.encrypt(plain_text.encode("utf-8"))
    return encrypted_bytes.decode("utf-8")


def decrypt_credential(cipher_text: str) -> str:
    """Dekripsi teks kredensial saat akan dikirim ke pembeli."""
    cipher = get_cipher()
    decrypted_bytes = cipher.decrypt(cipher_text.encode("utf-8"))
    return decrypted_bytes.decode("utf-8")


def generate_new_key() -> str:
    """Helper untuk generate encryption key baru."""
    return Fernet.generate_key().decode()
