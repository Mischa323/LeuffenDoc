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

An administrator manages it in Instellingen: shows it to keep a copy elsewhere
(and says so), or replaces it -- every small key rewrapped, every fingerprint
redone, the shared links and sealed settings likewise, in one transaction, so
everything moves to the new key or nothing does.
"""
from __future__ import annotations

import base64
import json
import os
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import database

KEY_SETTING = "DOC_SECRET_KEY"
# Who said they keep a copy of the key elsewhere, and when.
SAVED_SETTING = "DOC_VAULT_KEY_SAVED"
VERSION = 1
MIN_OWN_KEY = 16

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


def fingerprint(plaintext: str) -> str:
    """The same password gives the same fingerprint, so one used in two places
    can be found without opening either. Keyed with a key derived from the
    master key: without that, a stolen database cannot be checked against a
    list of common passwords by hashing the list."""
    import hashlib
    import hmac
    key = hmac.new(master_key(), b"leuffendoc-fingerprint-v1", hashlib.sha256).digest()
    return hmac.new(key, plaintext.encode(), hashlib.sha256).hexdigest()


def _stored() -> str:
    return (database.get_setting(KEY_SETTING) or "").strip()


def state() -> dict:
    """Where the key lives, for the notice in the interface: in the
    environment or in the database, whether somebody keeps a copy elsewhere,
    and -- with the key in the environment -- whether an old copy is still in
    the database."""
    stored, env = _stored(), key_from_environment()
    saved = None
    if stored and not env:
        try:
            saved = json.loads(database.get_setting(SAVED_SETTING) or "null")
        except ValueError:
            saved = None
    copy = bool(env and stored)
    return {"from_environment": env, "in_database": bool(stored) and not env, "saved": saved,
            "copy_in_database": copy,
            "copy_matches": copy and _decode(stored) == _decode(os.environ[KEY_SETTING])}


def new_key_text() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def reveal() -> str:
    """The key as it is kept, to store a copy elsewhere. Not one that comes
    from the environment: LeuffenDoc does not keep that one."""
    if key_from_environment():
        raise ValueError("De sleutel komt uit DOC_SECRET_KEY in de omgeving van de container; "
                         "LeuffenDoc bewaart hem niet en kan hem dus ook niet tonen.")
    master_key()                                 # makes one when there is none yet
    return _stored()


def mark_saved(by: str) -> None:
    database.set_setting(SAVED_SETTING, json.dumps({"at": time.time(), "by": by}))


def _rewrap(old: bytes, new: bytes, wrapped: bytes, wrap_nonce: bytes) -> tuple:
    data_key = AESGCM(old).decrypt(wrap_nonce, wrapped, None)
    nonce = os.urandom(12)
    return AESGCM(new).encrypt(nonce, data_key, None), nonce, data_key


def rekey(new_raw: str) -> dict:
    """Put the vault under another master key. Each secret's small key is
    unwrapped with the old one and wrapped with the new; the fingerprints,
    keyed with the master key, are redone; the shared links and the secret
    settings move with them. One transaction: when anything does not open,
    nothing changes and the old key stays."""
    global _cached
    import hashlib
    import hmac
    if key_from_environment():
        raise ValueError("De sleutel komt uit DOC_SECRET_KEY in de omgeving van de container; "
                         "vervang hem daar.")
    text = (new_raw or "").strip()
    if len(text) < MIN_OWN_KEY:
        raise ValueError(f"Kies een sleutel of wachtwoordzin van minstens {MIN_OWN_KEY} tekens")
    old, new = master_key(), _decode(text)
    if old == new:
        raise ValueError("Dat is de sleutel die er al is")
    marker = hmac.new(new, b"leuffendoc-fingerprint-v1", hashlib.sha256).digest()
    counts = {"passwords": 0, "shares": 0, "settings": 0}

    def repacked(raw: dict) -> dict:
        record = {k: base64.b64decode(v) for k, v in raw.items() if k != "key_version"}
        record["wrapped_key"], record["wrap_nonce"], _ = _rewrap(old, new, record["wrapped_key"], record["wrap_nonce"])
        out = {k: base64.b64encode(v).decode() for k, v in record.items() if isinstance(v, (bytes, bytearray))}
        out["key_version"] = raw.get("key_version", VERSION)
        return out

    sealed = "sealed:"                          # settings.SEALED, without importing settings here
    try:
        with database.write() as conn:
            for r in conn.execute("SELECT item_id, field_key, wrapped_key, wrap_nonce, nonce, ciphertext, "
                                  "fingerprint FROM secrets").fetchall():
                wrapped, wrap_nonce, data_key = _rewrap(old, new, r["wrapped_key"], r["wrap_nonce"])
                fingerprint = r["fingerprint"]
                if fingerprint:
                    plain = AESGCM(data_key).decrypt(r["nonce"], r["ciphertext"], None)
                    fingerprint = hmac.new(marker, plain, hashlib.sha256).hexdigest()
                conn.execute("UPDATE secrets SET wrapped_key=?, wrap_nonce=?, fingerprint=? "
                             "WHERE item_id=? AND field_key=?",
                             (wrapped, wrap_nonce, fingerprint, r["item_id"], r["field_key"]))
                counts["passwords"] += 1
            for r in conn.execute("SELECT id, sealed_json FROM shares WHERE sealed_json != ''").fetchall():
                conn.execute("UPDATE shares SET sealed_json=? WHERE id=?",
                             (json.dumps(repacked(json.loads(r["sealed_json"]))), r["id"]))
                counts["shares"] += 1
            for r in conn.execute("SELECT key, value FROM settings WHERE value LIKE ?", (sealed + "%",)).fetchall():
                raw = json.loads(r["value"][len(sealed):])
                conn.execute("UPDATE settings SET value=? WHERE key=?",
                             (sealed + json.dumps(repacked(raw)), r["key"]))
                counts["settings"] += 1
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (KEY_SETTING, text))
            # A new key nobody has kept yet.
            conn.execute("DELETE FROM settings WHERE key=?", (SAVED_SETTING,))
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError("Niet alles in de kluis ging open met de huidige sleutel, dus er is niets "
                         "veranderd") from exc
    _cached = new
    return counts


def forget_copy() -> None:
    """With the key in the environment, the copy LeuffenDoc once made in the
    database is only a risk -- but only one that is the same key goes."""
    st = state()
    if not st["copy_in_database"]:
        raise ValueError("Er staat geen kopie van de sleutel in de database")
    if not st["copy_matches"]:
        raise ValueError("De sleutel in de database is een andere dan die in DOC_SECRET_KEY; "
                         "die blijft staan tot duidelijk is welke de wachtwoorden opent")
    with database.write() as conn:
        conn.execute("DELETE FROM settings WHERE key IN (?, ?)", (KEY_SETTING, SAVED_SETTING))


def pack(record: dict) -> str:
    """A sealed record as text, for storing in a column."""
    out = {k: base64.b64encode(v).decode() for k, v in record.items()
           if isinstance(v, (bytes, bytearray))}
    out["key_version"] = record.get("key_version", VERSION)
    return json.dumps(out)


def unpack(text: str) -> dict:
    raw = json.loads(text)
    record = {k: base64.b64decode(v) for k, v in raw.items() if k != "key_version"}
    record["key_version"] = raw.get("key_version", VERSION)
    return record
