"""backend/services/crypto.py — encrypt DB credentials at rest (Fernet)."""
from __future__ import annotations

import json
from typing import Optional

from backend.config import get_settings


def _fernet():
    key = get_settings().credential_encryption_key
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        return None


def encrypt_credentials(data: dict) -> Optional[bytes]:
    f = _fernet()
    if f is None:
        return None
    return f.encrypt(json.dumps(data).encode())


def decrypt_credentials(blob: Optional[bytes]) -> Optional[dict]:
    if not blob:
        return None
    f = _fernet()
    if f is None:
        return None
    try:
        return json.loads(f.decrypt(blob).decode())
    except Exception:
        return None
