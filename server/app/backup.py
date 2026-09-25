"""Back-ups: taken while running, carried away encrypted, put back without a restart.

Copying the database file of a running server is not a back-up: SQLite in WAL
mode keeps the latest changes in a second file, and a copy taken halfway
through a write can come back broken. A **snapshot** here is made by SQLite
itself (``VACUUM INTO``), from one consistent moment, into ``backups/`` next to
the database -- so whatever backs up the data volume picks up something that
opens.

A snapshot **leaving** the server always goes out encrypted with a passphrase
the administrator chooses: it holds every customer's documentation and, when
``DOC_SECRET_KEY`` is not set in the environment, the key to the vault as well.

**Putting one back** replaces the database's contents in place, under the
write lock, so the server keeps running. Before anything is replaced the
snapshot is checked -- that it is whole, that it is a LeuffenDoc database, and
that the passwords in it open with the key that will be in force afterwards --
and the current state is itself kept as a snapshot, so putting one back can
always be undone.
"""
from __future__ import annotations

import base64
import datetime
import gzip
import hashlib
import json
import os
import re
import sqlite3
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import database, schema, vault

MAGIC = b"LEUFFENDOC-BACKUP\n"
KINDS = {"auto": "Automatisch", "handmatig": "Handmatig", "geupload": "Geüpload",
         "voor-terugzetten": "Vóór terugzetten"}
_NAME = re.compile(r"^(auto|handmatig|geupload|voor-terugzetten)-\d{8}-\d{6}(-\d+)?\.db$")
# Settings that belong to this installation rather than to its documentation:
# putting a snapshot back must not sign everyone out, nor make this container
# forget what its own image looks like.
KEEP_ON_RESTORE = ("DOC_SESSION_SECRET", "DOC_IMAGE_DEFAULTS")
REQUIRED_TABLES = {"settings", "organizations", "users", "items", "secrets", "audit"}
MAX_UPLOAD = 512 * 1024 * 1024


def folder() -> str:
    path = os.path.join(os.path.dirname(os.path.abspath(database.DB_PATH)), "backups")
    os.makedirs(path, exist_ok=True)
    return path


def path_of(name: str) -> str:
    """A snapshot's file, for a name that can only ever be one of ours."""
    if not _NAME.match(name or ""):
        raise ValueError("Deze back-up bestaat niet")
    path = os.path.join(folder(), name)
    if not os.path.isfile(path):
        raise ValueError("Deze back-up bestaat niet")
    return path


def _new_name(kind: str) -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    name, n = f"{kind}-{stamp}.db", 1
    while os.path.exists(os.path.join(folder(), name)):
        n += 1
        name = f"{kind}-{stamp}-{n}.db"
    return name


# --------------------------------------------------------------------------- #
# Snapshots in the data volume
# --------------------------------------------------------------------------- #
def snapshot(kind: str = "handmatig") -> dict:
    """One consistent copy of the database, made by SQLite itself."""
    name = _new_name(kind)
    target = os.path.join(folder(), name)
    source = sqlite3.connect(database.DB_PATH)
    try:
        source.execute("VACUUM INTO ?", (target,))
    finally:
        source.close()
    return info(name)


def _counts(path: str) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        one = lambda sql: conn.execute(sql).fetchone()[0]    # noqa: E731
        return {"customers": one("SELECT COUNT(*) FROM organizations"),
                "items": one("SELECT COUNT(*) FROM items WHERE archived=0"),
                "passwords": one("SELECT COUNT(*) FROM secrets"),
                "users": one("SELECT COUNT(*) FROM users"),
                "last_change": one("SELECT MAX(updated_at) FROM items")}
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def info(name: str) -> dict:
    path = os.path.join(folder(), name)
    kind = _NAME.match(name).group(1)
    stat = os.stat(path)
    return {"name": name, "kind": kind, "label": KINDS.get(kind, kind),
            "size": stat.st_size, "made_at": stat.st_mtime, **_counts(path)}


def list_backups() -> list:
    names = [n for n in os.listdir(folder()) if _NAME.match(n)]
    return sorted((info(n) for n in names), key=lambda b: -b["made_at"])


def delete(name: str) -> None:
    os.remove(path_of(name))


def prune(keep: int) -> int:
    """Keep the newest `keep` automatic snapshots. The others -- made by hand,
    uploaded, taken before a restore -- stay until someone removes them."""
    autos = [b for b in list_backups() if b["kind"] == "auto"]
    gone = 0
    for old in autos[max(keep, 1):]:
        os.remove(os.path.join(folder(), old["name"]))
        gone += 1
    return gone


def last_auto() -> float | None:
    autos = [b for b in list_backups() if b["kind"] == "auto"]
    return autos[0]["made_at"] if autos else None


# --------------------------------------------------------------------------- #
# Carrying one away: encrypted with a passphrase
# --------------------------------------------------------------------------- #
def _derive(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(passphrase.encode(), salt=salt, n=n, r=r, p=p,
                          maxmem=128 * 1024 * 1024, dklen=32)


def seal_file(name: str, passphrase: str) -> bytes:
    if len(passphrase or "") < 12:
        raise ValueError("Kies een wachtwoordzin van minstens 12 tekens")
    with open(path_of(name), "rb") as fh:
        plain = gzip.compress(fh.read(), compresslevel=6)
    salt, nonce = os.urandom(16), os.urandom(12)
    header = {"format": 1, "kdf": "scrypt", "n": 2 ** 15, "r": 8, "p": 1,
              "salt": base64.b64encode(salt).decode(), "nonce": base64.b64encode(nonce).decode(),
              "made_at": os.path.getmtime(path_of(name)), "source": name}
    head = json.dumps(header, sort_keys=True).encode()
    key = _derive(passphrase, salt, header["n"], header["r"], header["p"])
    # The header is authenticated along with the contents: nobody can swap the
    # parameters without the passphrase failing.
    return MAGIC + head + b"\n" + AESGCM(key).encrypt(nonce, plain, head)


def open_file(data: bytes, passphrase: str) -> bytes:
    """The database inside an upload: decrypted if it is one of ours, as it is
    if it is a plain SQLite file (a snapshot taken off the volume by hand)."""
    if data.startswith(b"SQLite format 3\x00"):
        return data
    if not data.startswith(MAGIC):
        raise ValueError("Dit is geen back-up van LeuffenDoc")
    rest = data[len(MAGIC):]
    head, _, body = rest.partition(b"\n")
    try:
        header = json.loads(head)
        key = _derive(passphrase or "", base64.b64decode(header["salt"]),
                      int(header["n"]), int(header["r"]), int(header["p"]))
        plain = AESGCM(key).decrypt(base64.b64decode(header["nonce"]), body, head)
    except (ValueError, KeyError, TypeError):
        raise ValueError("Deze back-up is beschadigd")
    except Exception:
        # AES-GCM says only "invalid tag": the passphrase, or a damaged file.
        raise ValueError("De wachtwoordzin klopt niet, of het bestand is beschadigd")
    return gzip.decompress(plain)


def receive(data: bytes, passphrase: str) -> dict:
    """An uploaded back-up, checked and kept as a snapshot ready to put back."""
    if len(data) > MAX_UPLOAD:
        raise ValueError("Dit bestand is te groot voor een back-up")
    plain = open_file(data, passphrase)
    name = _new_name("geupload")
    path = os.path.join(folder(), name)
    with open(path, "wb") as fh:
        fh.write(plain)
    try:
        check(path)
    except ValueError:
        os.remove(path)
        raise
    return info(name)


# --------------------------------------------------------------------------- #
# Putting one back
# --------------------------------------------------------------------------- #
def _key_after(conn: sqlite3.Connection) -> str:
    """The master key that will be in force once this snapshot is back: the
    environment's if it is set, otherwise whatever the snapshot carries."""
    env = (os.environ.get(vault.KEY_SETTING) or "").strip()
    if env:
        return env
    r = conn.execute("SELECT value FROM settings WHERE key=?", (vault.KEY_SETTING,)).fetchone()
    return (r[0] or "").strip() if r else ""


def check(path: str) -> dict:
    """Refuse a snapshot that would leave the server worse off."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        try:
            ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
        except sqlite3.Error:
            raise ValueError("Dit bestand is geen database die SQLite kan openen")
        if ok != "ok":
            raise ValueError("De database in deze back-up is beschadigd")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not REQUIRED_TABLES <= tables:
            raise ValueError("Dit is geen database van LeuffenDoc")
        record = conn.execute("SELECT wrapped_key, wrap_nonce FROM secrets LIMIT 1").fetchone()
        if record:
            raw = _key_after(conn)
            if not raw:
                raise ValueError("De wachtwoorden in deze back-up zijn versleuteld met een sleutel "
                                 "die er niet in zit — die kwam uit DOC_SECRET_KEY. Zet die eerst "
                                 "in de omgeving van de container.")
            try:
                AESGCM(vault._decode(raw)).decrypt(record[1], record[0], None)
            except Exception:
                raise ValueError("De wachtwoorden in deze back-up gaan niet open met de sleutel "
                                 "die daarna zou gelden. Klopt DOC_SECRET_KEY?")
    finally:
        conn.close()
    return {"ok": True}


def restore(name: str) -> dict:
    """Replace everything with a snapshot, keeping the current state as one."""
    source = path_of(name)
    check(source)
    before = snapshot("voor-terugzetten")
    kept = {key: database.get_setting(key) for key in KEEP_ON_RESTORE}
    # What the RMM holds right now, so the next round compares the restored
    # documentation with that -- and takes away what no longer exists.
    in_rmm = database.doc_push_state()
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        with database._lock:
            # The backup API writes the snapshot's pages into the live
            # database; every other connection sees the new contents on its
            # next read, so nothing has to reconnect or restart.
            dst = sqlite3.connect(database.DB_PATH)
            try:
                src.backup(dst)
            except sqlite3.Error as exc:
                raise ValueError(f"Terugzetten lukte niet ({exc}); er is niets veranderd")
            finally:
                dst.close()
    finally:
        src.close()
    database.after_restore()
    for key, value in kept.items():
        if value is not None:
            database.set_setting(key, value)
    database.replace_doc_pushes(in_rmm)
    # Whatever was worked out from the old contents is out of date now.
    vault._cached = None
    schema.forget_custom()
    return {"restored": info(name), "before": before, "at": time.time()}
