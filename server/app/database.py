"""SQLite storage for LeuffenDoc.

Same shape as the RMM's database module, deliberately: one connection **per
thread** (FastAPI answers requests on a thread pool, and a shared connection
turns two simultaneous reads into an internal error), writes serialised behind a
lock, and additive `ALTER` migrations run at start-up.

To add a column: put it in `SCHEMA` *and* add an `if col not in cols` line to
:func:`_migrate`, so new and existing databases end up the same.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Iterator

DB_PATH = os.environ.get("DOC_DB_PATH",
                         os.path.join(os.path.dirname(__file__), "..", "data", "leuffendoc.db"))

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()
_threadlocal = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT
);

-- Customers. `rmm_org_id` ties one to its organisation in the RMM, which is how
-- documentation and devices find each other; a customer that exists only here
-- (no RMM organisation) simply leaves it empty.
CREATE TABLE IF NOT EXISTS organizations (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    rmm_org_id  TEXT UNIQUE,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

-- People who can sign in. Accounts are mirrored from the RMM (source='rmm') or
-- created here for a Microsoft 365 sign-in that has no RMM account ('m365');
-- 'local' is the bootstrap administrator.
CREATE TABLE IF NOT EXISTS users (
    email        TEXT PRIMARY KEY,
    display_name TEXT,
    is_admin     INTEGER NOT NULL DEFAULT 0,
    source       TEXT NOT NULL DEFAULT 'rmm',
    created_at   REAL NOT NULL,
    last_seen    REAL
);

CREATE TABLE IF NOT EXISTS org_users (
    org_id      TEXT NOT NULL,
    user_email  TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'tech',
    PRIMARY KEY (org_id, user_email),
    FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE CASCADE
);

-- Everything that touches a customer's information is written down: who, when,
-- from where. The vault leans on this, so it is here from the start.
CREATE TABLE IF NOT EXISTS audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          REAL NOT NULL,
    user_email  TEXT,
    org_id      TEXT,
    action      TEXT NOT NULL,
    target      TEXT,
    detail      TEXT,
    ip          TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_at ON audit(at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_org ON audit(org_id, at DESC);
"""


def _new_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    global _conn
    if _conn is not None:
        return
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    _conn = _new_conn()
    _conn.executescript(SCHEMA)
    _migrate(_conn)
    _conn.commit()
    _threadlocal.conn = _conn      # the initialising thread reuses this one


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive migrations for databases created by an earlier version."""
    return


def get_conn() -> sqlite3.Connection:
    """This thread's connection (see the module docstring)."""
    if _conn is None:
        raise RuntimeError("Database not initialised; call init_db() first")
    conn = getattr(_threadlocal, "conn", None)
    if conn is None:
        conn = _new_conn()
        _threadlocal.conn = conn
    return conn


@contextmanager
def write() -> Iterator[sqlite3.Connection]:
    conn = get_conn()
    with _lock:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def rows(sql: str, args: tuple = ()) -> list[dict]:
    return [dict(r) for r in get_conn().execute(sql, args)]


def row(sql: str, args: tuple = ()) -> dict | None:
    r = get_conn().execute(sql, args).fetchone()
    return dict(r) if r else None


# --------------------------------------------------------------------------- #
# Settings (what the setup wizard saves; environment variables win over these)
# --------------------------------------------------------------------------- #
def get_setting(key: str, default: str | None = None) -> str | None:
    r = row("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else default


def set_setting(key: str, value: str | None) -> None:
    with write() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def all_settings() -> dict:
    return {r["key"]: r["value"] for r in rows("SELECT key, value FROM settings")}


# --------------------------------------------------------------------------- #
# Organisations
# --------------------------------------------------------------------------- #
def list_orgs() -> list[dict]:
    return rows("SELECT * FROM organizations ORDER BY name COLLATE NOCASE")


def get_org(org_id: str) -> dict | None:
    return row("SELECT * FROM organizations WHERE id=?", (org_id,))


def upsert_org(name: str, rmm_org_id: str | None = None, org_id: str | None = None) -> str:
    """Create or update a customer. Matched on the RMM organisation where there
    is one, so a rename in the RMM follows through instead of doubling up."""
    now = time.time()
    existing = None
    if org_id:
        existing = get_org(org_id)
    elif rmm_org_id:
        existing = row("SELECT * FROM organizations WHERE rmm_org_id=?", (rmm_org_id,))
    with write() as conn:
        if existing:
            conn.execute("UPDATE organizations SET name=?, rmm_org_id=COALESCE(?, rmm_org_id), "
                         "updated_at=? WHERE id=?",
                         (name, rmm_org_id, now, existing["id"]))
            return existing["id"]
        new_id = org_id or uuid.uuid4().hex[:12]
        conn.execute("INSERT INTO organizations (id, name, rmm_org_id, created_at, updated_at) "
                     "VALUES (?, ?, ?, ?, ?)", (new_id, name, rmm_org_id, now, now))
        return new_id


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
def get_user(email: str) -> dict | None:
    return row("SELECT * FROM users WHERE email=?", (email.lower(),))


def list_users() -> list[dict]:
    return rows("SELECT * FROM users ORDER BY email")


def upsert_user(email: str, display_name: str | None = None, is_admin: bool | None = None,
                source: str = "rmm") -> dict:
    email = email.lower()
    now = time.time()
    existing = get_user(email)
    with write() as conn:
        if existing:
            conn.execute(
                "UPDATE users SET display_name=COALESCE(?, display_name), "
                "is_admin=COALESCE(?, is_admin), source=?, last_seen=? WHERE email=?",
                (display_name, None if is_admin is None else int(is_admin), source, now, email))
        else:
            conn.execute(
                "INSERT INTO users (email, display_name, is_admin, source, created_at, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (email, display_name, int(bool(is_admin)), source, now, now))
    return get_user(email)  # type: ignore[return-value]


def set_user_orgs(email: str, org_ids: list[str], role: str = "tech") -> None:
    """Replace someone's customer access in one go -- how a sync from the RMM
    lands, so access removed there is removed here."""
    email = email.lower()
    with write() as conn:
        conn.execute("DELETE FROM org_users WHERE user_email=?", (email,))
        conn.executemany("INSERT OR IGNORE INTO org_users (org_id, user_email, role) VALUES (?, ?, ?)",
                         [(oid, email, role) for oid in org_ids])


def user_orgs(email: str) -> list[dict]:
    return rows("SELECT o.*, ou.role FROM organizations o "
                "JOIN org_users ou ON ou.org_id = o.id AND ou.user_email = ? "
                "ORDER BY o.name COLLATE NOCASE", (email.lower(),))


def user_count() -> int:
    return get_conn().execute("SELECT COUNT(*) FROM users").fetchone()[0]


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #
def audit(action: str, user_email: str | None = None, org_id: str | None = None,
          target: str | None = None, detail: str | None = None, ip: str | None = None) -> None:
    """Record one action. Never hand it a secret -- `detail` is meant for what
    was touched, not what it contained."""
    with write() as conn:
        conn.execute("INSERT INTO audit (at, user_email, org_id, action, target, detail, ip) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (time.time(), user_email, org_id, action, target, detail, ip))


def list_audit(org_id: str | None = None, limit: int = 200) -> list[dict]:
    if org_id:
        return rows("SELECT * FROM audit WHERE org_id=? ORDER BY at DESC LIMIT ?", (org_id, limit))
    return rows("SELECT * FROM audit ORDER BY at DESC LIMIT ?", (limit,))
