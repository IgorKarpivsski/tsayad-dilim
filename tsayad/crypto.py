"""AES-256-GCM helpers.
* Data-at-rest: the SQLite DB is encrypted with DATA_KEY before it is pushed to the public repo.
* Dashboard: HTML is encrypted with a key derived from DASHBOARD_PASSWORD (PBKDF2-SHA256),
  decrypted in the browser with WebCrypto – a free 'password-protected' static page."""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

MAGIC = b"DLN1"
PBKDF2_ITER = 250_000


def new_key() -> str:
    return base64.b64encode(AESGCM.generate_key(bit_length=256)).decode()


def _key(b64: str) -> bytes:
    k = base64.b64decode(b64)
    if len(k) != 32:
        raise ValueError("DATA_KEY must be base64 of 32 bytes (run: python -m tsayad keygen)")
    return k


def encrypt_bytes(data: bytes, key_b64: str) -> bytes:
    iv = os.urandom(12)
    return MAGIC + iv + AESGCM(_key(key_b64)).encrypt(iv, data, MAGIC)


def decrypt_bytes(blob: bytes, key_b64: str) -> bytes:
    if not blob.startswith(MAGIC):
        raise ValueError("not a Tsayad HaDilim encrypted blob")
    iv, ct = blob[4:16], blob[16:]
    return AESGCM(_key(key_b64)).decrypt(iv, ct, MAGIC)


def password_encrypt(plaintext: str, password: str) -> dict:
    salt, iv = os.urandom(16), os.urandom(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITER)
    key = kdf.derive(password.encode())
    ct = AESGCM(key).encrypt(iv, plaintext.encode(), None)
    b = lambda x: base64.b64encode(x).decode()  # noqa: E731
    return {"salt": b(salt), "iv": b(iv), "ct": b(ct), "iter": PBKDF2_ITER}


def password_decrypt(bundle: dict, password: str) -> str:
    d = lambda x: base64.b64decode(x)  # noqa: E731
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=d(bundle["salt"]), iterations=bundle["iter"])
    return AESGCM(kdf.derive(password.encode())).decrypt(d(bundle["iv"]), d(bundle["ct"]), None).decode()
