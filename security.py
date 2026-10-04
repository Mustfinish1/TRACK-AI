# security.py
import os, re, time
from cryptography.fernet import Fernet, InvalidToken
from config import log

_FERNET = None


def _get_fernet():
    global _FERNET
    if _FERNET is not None:
        return _FERNET
    key = os.getenv("ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY missing. Generate with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        _FERNET = Fernet(key.encode())
    except Exception as e:
        raise RuntimeError(f"ENCRYPTION_KEY invalid: {e}")
    return _FERNET


def encrypt(text: str) -> str:
    if not text:
        return ""
    return _get_fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        log.error("decrypt: invalid token")
        return ""
    except Exception as e:
        log.error(f"decrypt: {e}")
        return ""


_TG_USERNAME = re.compile(r"^[A-Za-z0-9_]{3,32}$")
_TX_HASH     = re.compile(r"^[0-9a-fA-F]{64}$")
_SYMBOL      = re.compile(r"^[A-Z0-9]{2,10}/[A-Z0-9]{2,10}$")


def clean_username(u: str) -> str:
    if not u:
        return ""
    u = u.strip()[:32]
    return u if _TG_USERNAME.match(u) else ""


def clean_symbol(s: str) -> str:
    if not s:
        return ""
    s = s.strip().upper()[:24]
    return s if _SYMBOL.match(s) else ""


def clean_tx_hash(h: str) -> str:
    if not h:
        return ""
    h = h.strip()
    return h if _TX_HASH.match(h) else ""


def mask_secret(s: str, show=4) -> str:
    if not s:
        return "***"
    if len(s) <= show * 2:
        return "*" * len(s)
    return s[:show] + "*" * (len(s) - show * 2) + s[-show:]


_rate: dict = {}


def rate_ok(key, limit=5, window=60) -> bool:
    now = time.monotonic()
    arr = [t for t in _rate.get(key, []) if now - t < window]
    if len(arr) >= limit:
        _rate[key] = arr
        return False
    arr.append(now)
    _rate[key] = arr
    return True
