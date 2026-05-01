import os
from cryptography.fernet import Fernet

_ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")
_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        if not _ENCRYPTION_KEY:
            raise RuntimeError("ENCRYPTION_KEY env var is not set")
        _fernet = Fernet(_ENCRYPTION_KEY.encode())
    return _fernet


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
