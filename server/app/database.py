"""SQLite storage for LeuffenDoc.

Same shape as the RMM's database module, deliberately: one connection **per
thread** (FastAPI answers requests on a thread pool, and a shared connection
turns two simultaneous reads into an internal error), writes serialised behind a
lock, and additive `ALTER` migrations run at start-up.

To add a column: put it in `SCHEMA` *and* add an `if col not in cols` line to
:func:`_migrate`, so new and existing databases end up the same.
"""
from __future__ import annotations

import json
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

-- Everything that gets documented: a computer, a switch, a printer, an
-- internet connection, a location, a contact. One table rather than one per
-- kind, because what surrounds them is the same for all -- who may see it, its
-- history, what it is related to, search -- and because the types people define
-- themselves later have to slip in here without a new table each.
--
-- `fields_json` holds the kind's own fields; which fields those are lives in
-- schema.py. `source` says where an item came from: typed here, or mirrored
-- from a device in the RMM.
CREATE TABLE IF NOT EXISTS items (
    id            TEXT PRIMARY KEY,
    org_id        TEXT NOT NULL,
    kind          TEXT NOT NULL,
    name          TEXT NOT NULL,
    fields_json   TEXT NOT NULL DEFAULT '{}',
    source        TEXT NOT NULL DEFAULT 'manual',   -- 'manual' | 'rmm'
    rmm_device_id TEXT,
    rmm_json      TEXT,        -- what the RMM last told us about it
    rmm_seen_at   REAL,        -- when the RMM last still had it
    rmm_gone      INTEGER NOT NULL DEFAULT 0,
    archived      INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL,
    created_by    TEXT,
    updated_at    REAL NOT NULL,
    updated_by    TEXT,
    FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_items_org ON items(org_id, kind, name COLLATE NOCASE);
CREATE UNIQUE INDEX IF NOT EXISTS idx_items_rmm ON items(rmm_device_id)
    WHERE rmm_device_id IS NOT NULL;

-- Network adapters hang under a piece of equipment. The MAC address is the
-- point: it is what ties a machine to the port it is patched into.
CREATE TABLE IF NOT EXISTS adapters (
    id          TEXT PRIMARY KEY,
    item_id     TEXT NOT NULL,
    name        TEXT,
    mac         TEXT,
    ipv4        TEXT,
    ipv6        TEXT,
    assignment  TEXT,          -- 'dhcp' | 'static'
    vlan        TEXT,
    speed       TEXT,
    source      TEXT NOT NULL DEFAULT 'manual',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_adapters_item ON adapters(item_id);

-- A switch's ports. The port row is where the connection is kept, so a port can
-- exist while empty (which is how you find a free one) and no two adapters can
-- claim the same port.
CREATE TABLE IF NOT EXISTS switch_ports (
    id          TEXT PRIMARY KEY,
    switch_id   TEXT NOT NULL,
    number      INTEGER NOT NULL,
    label       TEXT,
    vlan        TEXT,
    adapter_id  TEXT UNIQUE,
    updated_at  REAL NOT NULL,
    updated_by  TEXT,
    UNIQUE (switch_id, number),
    FOREIGN KEY (switch_id) REFERENCES items(id) ON DELETE CASCADE,
    FOREIGN KEY (adapter_id) REFERENCES adapters(id) ON DELETE SET NULL
);

-- Anything may be related to anything: a password to a firewall, a document to
-- a server, an internet connection to the router it lands on. Stored once, with
-- the two ids in a fixed order, and read from both sides.
CREATE TABLE IF NOT EXISTS relations (
    id          TEXT PRIMARY KEY,
    a_id        TEXT NOT NULL,
    b_id        TEXT NOT NULL,
    label       TEXT,
    created_at  REAL NOT NULL,
    created_by  TEXT,
    UNIQUE (a_id, b_id),
    FOREIGN KEY (a_id) REFERENCES items(id) ON DELETE CASCADE,
    FOREIGN KEY (b_id) REFERENCES items(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_rel_a ON relations(a_id);
CREATE INDEX IF NOT EXISTS idx_rel_b ON relations(b_id);

-- Every change to every item: who, when, which field, from what to what. The
-- RMM writes here too, so "memory 8 -> 16 GB" is recorded without anyone
-- having to keep it up.
CREATE TABLE IF NOT EXISTS revisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id      TEXT NOT NULL,
    at           REAL NOT NULL,
    user_email   TEXT,          -- empty when the RMM made the change
    source       TEXT NOT NULL DEFAULT 'manual',
    action       TEXT NOT NULL, -- created | updated | archived | restored
    changes_json TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_rev_item ON revisions(item_id, at DESC);
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


# --------------------------------------------------------------------------- #
# Documented items
#
# Everything here writes its own history: a change with nobody's name on it is
# what makes shared documentation untrustworthy. The difference is worked out
# inside the same write as the change itself, so the item and the line about it
# can never disagree.
# --------------------------------------------------------------------------- #
def _item_out(r: dict) -> dict:
    r = dict(r)
    r["fields"] = json.loads(r.pop("fields_json", None) or "{}")
    r["rmm"] = json.loads(r.pop("rmm_json", None) or "null")
    r["archived"] = bool(r.get("archived"))
    r["rmm_gone"] = bool(r.get("rmm_gone"))
    return r


def list_items(org_id: str, kind: str | None = None,
               include_archived: bool = False) -> list[dict]:
    sql = "SELECT * FROM items WHERE org_id=?"
    args: list = [org_id]
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    if not include_archived:
        sql += " AND archived=0"
    sql += " ORDER BY name COLLATE NOCASE"
    return [_item_out(r) for r in rows(sql, tuple(args))]


def get_item(item_id: str) -> dict | None:
    r = row("SELECT * FROM items WHERE id=?", (item_id,))
    return _item_out(r) if r else None


def item_by_rmm_device(device_id: str) -> dict | None:
    r = row("SELECT * FROM items WHERE rmm_device_id=?", (device_id,))
    return _item_out(r) if r else None


def count_items(org_id: str) -> dict:
    """How many of each kind a customer has, for the overview."""
    return {r["kind"]: r["n"] for r in
            rows("SELECT kind, COUNT(*) AS n FROM items WHERE org_id=? AND archived=0 "
                 "GROUP BY kind", (org_id,))}


def _plain(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "ja" if value else "nee"
    return str(value)


def _diff(before: dict, after: dict, label) -> list:
    changes = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        changes.append({"key": key, "label": label(key),
                        "from": _plain(old), "to": _plain(new)})
    return changes


def create_item(org_id: str, kind: str, name: str, fields: dict, by: str | None,
                source: str = "manual", rmm_device_id: str | None = None,
                rmm: dict | None = None, label=None) -> dict:
    now = time.time()
    item_id = uuid.uuid4().hex[:12]
    label = label or (lambda key: key)
    fields = fields or {}
    with write() as conn:
        conn.execute(
            "INSERT INTO items (id, org_id, kind, name, fields_json, source, rmm_device_id, "
            "rmm_json, rmm_seen_at, created_at, created_by, updated_at, updated_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item_id, org_id, kind, name, json.dumps(fields), source, rmm_device_id,
             json.dumps(rmm) if rmm else None, now if rmm_device_id else None,
             now, by, now, by))
        changes = _diff({}, {"naam": name, **fields},
                        lambda key: "Naam" if key == "naam" else label(key))
        conn.execute("INSERT INTO revisions (item_id, at, user_email, source, action, "
                     "changes_json) VALUES (?, ?, ?, ?, 'created', ?)",
                     (item_id, now, by, source, json.dumps(changes)))
    return get_item(item_id)


def update_item(item_id: str, name: str | None = None, fields: dict | None = None,
                by: str | None = None, source: str = "manual",
                rmm: dict | None = None, rmm_gone: bool | None = None,
                label=None) -> dict:
    """Apply a change and record exactly what moved.

    `fields` is merged, not replaced: a form that sends one group of fields must
    not silently empty the rest. A field sent empty is removed.
    """
    label = label or (lambda key: key)
    now = time.time()
    with write() as conn:
        r = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        if not r:
            raise KeyError(item_id)
        before_fields = json.loads(r["fields_json"] or "{}")
        after_fields = dict(before_fields)
        for key, value in (fields or {}).items():
            if value in (None, ""):
                after_fields.pop(key, None)
            else:
                after_fields[key] = value
        after_name = (name or "").strip() or r["name"]
        changes = _diff({"naam": r["name"], **before_fields},
                        {"naam": after_name, **after_fields},
                        lambda key: "Naam" if key == "naam" else label(key))
        sets = ["name=?", "fields_json=?", "updated_at=?", "updated_by=?"]
        args: list = [after_name, json.dumps(after_fields), now, by]
        if rmm is not None:
            sets += ["rmm_json=?", "rmm_seen_at=?", "rmm_gone=0"]
            args += [json.dumps(rmm), now]
        if rmm_gone is not None:
            sets.append("rmm_gone=?")
            args.append(int(rmm_gone))
        conn.execute(f"UPDATE items SET {', '.join(sets)} WHERE id=?", (*args, item_id))
        # Nothing moved means nothing to write down; a sync that changes nothing
        # should not fill the history with empty lines.
        if changes:
            conn.execute("INSERT INTO revisions (item_id, at, user_email, source, action, "
                         "changes_json) VALUES (?, ?, ?, ?, 'updated', ?)",
                         (item_id, now, by, source, json.dumps(changes)))
    return get_item(item_id)


def set_archived(item_id: str, archived: bool, by: str | None) -> dict:
    now = time.time()
    with write() as conn:
        conn.execute("UPDATE items SET archived=?, updated_at=?, updated_by=? WHERE id=?",
                     (int(archived), now, by, item_id))
        conn.execute("INSERT INTO revisions (item_id, at, user_email, source, action, "
                     "changes_json) VALUES (?, ?, ?, 'manual', ?, '[]')",
                     (item_id, now, by, "archived" if archived else "restored"))
    return get_item(item_id)


def delete_item(item_id: str) -> None:
    with write() as conn:
        conn.execute("DELETE FROM items WHERE id=?", (item_id,))


def list_revisions(item_id: str, limit: int = 200) -> list:
    out = []
    for r in rows("SELECT * FROM revisions WHERE item_id=? ORDER BY at DESC, id DESC LIMIT ?",
                  (item_id, limit)):
        r = dict(r)
        r["changes"] = json.loads(r.pop("changes_json", None) or "[]")
        out.append(r)
    return out


def get_revision(revision_id: int) -> dict | None:
    r = row("SELECT * FROM revisions WHERE id=?", (revision_id,))
    if not r:
        return None
    r = dict(r)
    r["changes"] = json.loads(r.pop("changes_json", None) or "[]")
    return r


# --------------------------------------------------------------------------- #
# Relations -- anything to anything, stored once and read from both sides
# --------------------------------------------------------------------------- #
def _pair(a: str, b: str) -> tuple:
    """One fixed order, so the same link cannot be stored twice."""
    return (a, b) if a <= b else (b, a)


def relate(a_id: str, b_id: str, label: str | None, by: str | None) -> str:
    if a_id == b_id:
        raise ValueError("Een item kan niet aan zichzelf gekoppeld worden")
    a, b = _pair(a_id, b_id)
    existing = row("SELECT id FROM relations WHERE a_id=? AND b_id=?", (a, b))
    if existing:
        return existing["id"]
    rel_id = uuid.uuid4().hex[:12]
    with write() as conn:
        conn.execute("INSERT INTO relations (id, a_id, b_id, label, created_at, created_by) "
                     "VALUES (?, ?, ?, ?, ?, ?)", (rel_id, a, b, label, time.time(), by))
    return rel_id


def unrelate(relation_id: str) -> None:
    with write() as conn:
        conn.execute("DELETE FROM relations WHERE id=?", (relation_id,))


def get_relation(relation_id: str) -> dict | None:
    return row("SELECT * FROM relations WHERE id=?", (relation_id,))


def relations_of(item_id: str) -> list:
    """What this item is related to, whichever side it was linked from."""
    return rows(
        "SELECT r.id AS relation_id, r.label, i.id, i.kind, i.name, i.archived "
        "FROM relations r JOIN items i ON i.id = CASE WHEN r.a_id=? THEN r.b_id ELSE r.a_id END "
        "WHERE r.a_id=? OR r.b_id=? ORDER BY i.kind, i.name COLLATE NOCASE",
        (item_id, item_id, item_id))
