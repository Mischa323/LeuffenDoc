"""Storing a password so it can be read back, and only on purpose.

Encryption here is **server-side**, chosen deliberately over end-to-end: a
password nobody can recover when the one person who knew it has left is not
documentation, and searching, sharing and backup all stop working the moment
the server cannot read anything. The trade is stated plainly rather than
hidden: whoever holds the master key can read the vault.

Two layers, so the master key can be replaced without re-encrypting everything:

  * each secret gets its **own random key**, which encrypts the text; and
  * that key is stored **wrapped** with the master key.

Re-keying then means unwrapping and rewrapping small keys, not rewriting every
secret. AES-256-GCM both times, so a tampered record fails to open rather than
returning something plausible.

The master key comes from ``DOC_SECRET_KEY``. If that is not set one is made
and kept in the database, which works but puts the key in the same place as the
thing it protects -- the interface says so, because an operator should know
whether their backup contains both halves.
"""
from __future__ import annotations

import base64
import os
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import database

KEY_SETTING = "DOC_SECRET_KEY"
VERSION = 1

_cached: bytes | None = None


def _decode(raw: str) -> bytes:
    """Accept a key as base64, as hex, or as a plain passphrase."""
    text = raw.strip()
    try:
        data = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        if len(data) == 32:
            return data
    except Exception:
        pass
    try:
        data = bytes.fromhex(text)
        if len(data) == 32:
            return data
    except ValueError:
        pass
    # Anything else is stretched, so a short passphrase still yields a full key.
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=b"leuffendoc-vault-v1", iterations=200_000)
    return kdf.derive(text.encode())


def key_from_environment() -> bool:
    return bool((os.environ.get(KEY_SETTING) or "").strip())


def master_key() -> bytes:
    """The key everything else is wrapped with, made on first use if needed."""
    global _cached
    if _cached is not None:
        return _cached
    raw = (os.environ.get(KEY_SETTING) or database.get_setting(KEY_SETTING) or "").strip()
    if not raw:
        raw = base64.urlsafe_b64encode(os.urandom(32)).decode()
        database.set_setting(KEY_SETTING, raw)
    _cached = _decode(raw)
    return _cached


def seal(plaintext: str) -> dict:
    """Encrypt one secret. Returns the parts to store, nothing readable."""
    data_key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    ciphertext = AESGCM(data_key).encrypt(nonce, plaintext.encode(), None)
    wrap_nonce = os.urandom(12)
    wrapped = AESGCM(master_key()).encrypt(wrap_nonce, data_key, None)
    return {"wrapped_key": wrapped, "wrap_nonce": wrap_nonce,
            "nonce": nonce, "ciphertext": ciphertext,
            "key_version": VERSION, "updated_at": time.time()}


def unseal(record: dict) -> str:
    """Read one secret back. Raises if the key is wrong or the record was
    altered -- which is the point of using GCM rather than plain AES."""
    data_key = AESGCM(master_key()).decrypt(record["wrap_nonce"], record["wrapped_key"], None)
    return AESGCM(data_key).decrypt(record["nonce"], record["ciphertext"], None).decode()


def state() -> dict:
    """Where the key lives, for the notice in the interface."""
    stored = bool(database.get_setting(KEY_SETTING))
    return {"from_environment": key_from_environment(),
            "in_database": stored and not key_from_environment()}
