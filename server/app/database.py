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

-- The encrypted half of a password. Kept out of the item itself on purpose:
-- an item's fields are handed out by every list, and they land in the history
-- as "from this to that". A secret must never travel that way.
CREATE TABLE IF NOT EXISTS secrets (
    item_id     TEXT NOT NULL,
    field_key   TEXT NOT NULL DEFAULT 'main',
    wrapped_key BLOB NOT NULL,
    wrap_nonce  BLOB NOT NULL,
    nonce       BLOB NOT NULL,
    ciphertext  BLOB NOT NULL,
    key_version INTEGER NOT NULL DEFAULT 1,
    updated_at  REAL NOT NULL,
    updated_by  TEXT,
    strength    INTEGER,     -- 0 zwak, 1 matig, 2 sterk; judged when stored
    fingerprint TEXT,        -- keyed hash, to find the same password elsewhere
    PRIMARY KEY (item_id, field_key),
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
);

-- Who may see an item that has been shut off from the rest of the customer.
-- No rows means it is not restricted: everyone with access to the customer
-- sees it. Any rows, and only those people (and administrators) do.
CREATE TABLE IF NOT EXISTS item_access (
    item_id     TEXT NOT NULL,
    user_email  TEXT NOT NULL,
    PRIMARY KEY (item_id, user_email),
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_item_access_user ON item_access(user_email);

-- A password shared with someone who has no account, for a while and a few
-- looks. Only a hash of the link is kept: someone reading the database cannot
-- make a working link from it. The password itself is sealed into the share
-- at the moment it is made -- a snapshot, so changing a leaked password does
-- not hand the new one to whoever holds an old link.
CREATE TABLE IF NOT EXISTS shares (
    id          TEXT PRIMARY KEY,
    item_id     TEXT NOT NULL,
    field_key   TEXT NOT NULL DEFAULT 'main',
    token_hash  TEXT NOT NULL UNIQUE,
    sealed_json TEXT NOT NULL,
    note        TEXT,
    created_at  REAL NOT NULL,
    created_by  TEXT,
    expires_at  REAL NOT NULL,
    max_views   INTEGER NOT NULL DEFAULT 1,
    views       INTEGER NOT NULL DEFAULT 0,
    last_view   REAL,
    revoked_at  REAL,
    revoked_why TEXT,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_shares_item ON shares(item_id);

-- What was last sent to the RMM about each machine, as a hash: a round only
-- sends what changed since.
CREATE TABLE IF NOT EXISTS doc_pushes (
    device_id TEXT PRIMARY KEY,
    hash      TEXT NOT NULL,
    pushed_at REAL NOT NULL
);

-- Types people define themselves. The built-in ones live in schema.py; these
-- join them at run time and are rendered by exactly the same code, which is
-- why the interface needs nothing new to show one.
CREATE TABLE IF NOT EXISTS item_types (
    id           TEXT PRIMARY KEY,      -- what items.kind holds
    label        TEXT NOT NULL,
    plural       TEXT NOT NULL,
    icon         TEXT,
    sub          TEXT,
    backref      TEXT,
    adapters     INTEGER NOT NULL DEFAULT 0,
    columns_json TEXT NOT NULL DEFAULT '[]',
    fields_json  TEXT NOT NULL DEFAULT '[]',
    created_at   REAL NOT NULL,
    created_by   TEXT,
    updated_at   REAL NOT NULL,
    updated_by   TEXT
);
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


def after_restore() -> None:
    """Bring contents put back from a snapshot up to this version's schema --
    the snapshot may be from before a column existed."""
    conn = _new_conn()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive migrations for databases created by an earlier version."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(secrets)")}
    if cols and "field_key" not in cols:
        # A vault entry used to hold one password. A type you define yourself
        # can have several, so the key is now the item *and* the field; what is
        # already stored becomes the item's main one.
        conn.executescript("""
            ALTER TABLE secrets RENAME TO secrets_old;
            CREATE TABLE secrets (
                item_id     TEXT NOT NULL,
                field_key   TEXT NOT NULL DEFAULT 'main',
                wrapped_key BLOB NOT NULL,
                wrap_nonce  BLOB NOT NULL,
                nonce       BLOB NOT NULL,
                ciphertext  BLOB NOT NULL,
                key_version INTEGER NOT NULL DEFAULT 1,
                updated_at  REAL NOT NULL,
                updated_by  TEXT,
                PRIMARY KEY (item_id, field_key),
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
            );
            INSERT INTO secrets (item_id, field_key, wrapped_key, wrap_nonce, nonce,
                                 ciphertext, key_version, updated_at, updated_by)
                SELECT item_id, 'main', wrapped_key, wrap_nonce, nonce, ciphertext,
                       key_version, updated_at, updated_by FROM secrets_old;
            DROP TABLE secrets_old;
        """)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(secrets)")}
    if "fingerprint" not in cols:
        # Judged when a password is stored. Rows from before have neither
        # until an administrator has them judged, from Kluis.
        conn.execute("ALTER TABLE secrets ADD COLUMN strength INTEGER")
        conn.execute("ALTER TABLE secrets ADD COLUMN fingerprint TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_secrets_fingerprint ON secrets(fingerprint)")


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


def set_user_orgs(email: str, orgs: list, role: str = "member") -> None:
    """Replace someone's customer access in one go -- how a sync from the RMM
    lands, so access removed there is removed here.

    `orgs` holds customer ids, or (id, role) pairs when the role differs per
    customer -- which it does when it comes from the RMM.
    """
    email = email.lower()
    pairs = [o if isinstance(o, (tuple, list)) else (o, role) for o in orgs]
    with write() as conn:
        conn.execute("DELETE FROM org_users WHERE user_email=?", (email,))
        conn.executemany("INSERT OR IGNORE INTO org_users (org_id, user_email, role) VALUES (?, ?, ?)",
                         [(oid, email, r or role) for oid, r in pairs])


def user_role(email: str, org_id: str) -> str | None:
    """Someone's role at one customer, or None if they have no access there."""
    r = row("SELECT role FROM org_users WHERE user_email=? AND org_id=?", (email.lower(), org_id))
    return r["role"] if r else None


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
    """One value, as a person reads it in the history."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "ja" if value else "nee"
    if isinstance(value, list):
        # A list of labelled values reads as "Werk: 06-… , Mobiel: 06-…"
        # rather than as the JSON it is stored as.
        return ", ".join(
            f"{e.get('label')}: {e.get('value')}" if isinstance(e, dict) and e.get("label")
            else str(e.get("value") if isinstance(e, dict) else e)
            for e in value)
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
                rmm_keys=None, label=None) -> dict:
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
        sets = ["name=?", "fields_json=?"]
        args: list = [after_name, json.dumps(after_fields)]
        if rmm is not None:
            # What the RMM reports is history too: "memory 8 -> 16 GB" is worth
            # having, and nobody had to keep it up. Only the keys that are
            # fields of this kind are compared, so the rest of the payload
            # (hostname, adapters, when it was last seen) stays out of it.
            before_rmm = json.loads(r["rmm_json"] or "{}")
            changes += _diff({k: before_rmm.get(k) for k in (rmm_keys or [])},
                             {k: rmm.get(k) for k in (rmm_keys or [])}, label)
            sets += ["rmm_json=?", "rmm_seen_at=?", "rmm_gone=0"]
            args += [json.dumps(rmm), now]
        if rmm_gone is not None:
            sets.append("rmm_gone=?")
            args.append(int(rmm_gone))
        # Only a change that moved something makes an item "last changed": a
        # sync that finds the machine as it was must not make every machine
        # look edited by nobody a minute ago.
        if changes:
            sets += ["updated_at=?", "updated_by=?"]
            args += [now, by]
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


def rmm_items() -> list:
    """Every item that mirrors a device in the RMM."""
    return [_item_out(r) for r in
            rows("SELECT * FROM items WHERE source='rmm' AND rmm_device_id IS NOT NULL")]


def mark_rmm_gone(item_id: str, gone: bool) -> None:
    """A device that left the RMM keeps its page -- the documentation hanging
    off it is usually exactly what you want afterwards -- but says so, and says
    so in its history as well."""
    now = time.time()
    with write() as conn:
        conn.execute("UPDATE items SET rmm_gone=?, updated_at=? WHERE id=?",
                     (int(gone), now, item_id))
        conn.execute("INSERT INTO revisions (item_id, at, user_email, source, action, "
                     "changes_json) VALUES (?, ?, NULL, 'rmm', ?, '[]')",
                     (item_id, now, "rmm-gone" if gone else "rmm-back"))


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


# --------------------------------------------------------------------------- #
# Secrets
#
# Only ever read one at a time and by name: there is no "list every password",
# because nothing in the interface needs one and its existence would be the
# most useful call in the place for anyone who should not have it.
# --------------------------------------------------------------------------- #
def put_secret(item_id: str, record: dict, by: str | None, field: str = "main") -> None:
    with write() as conn:
        conn.execute(
            "INSERT INTO secrets (item_id, field_key, wrapped_key, wrap_nonce, nonce, ciphertext, "
            "key_version, updated_at, updated_by, strength, fingerprint) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(item_id, field_key) DO UPDATE SET wrapped_key=excluded.wrapped_key, "
            "wrap_nonce=excluded.wrap_nonce, nonce=excluded.nonce, "
            "ciphertext=excluded.ciphertext, key_version=excluded.key_version, "
            "updated_at=excluded.updated_at, updated_by=excluded.updated_by, "
            "strength=excluded.strength, fingerprint=excluded.fingerprint",
            (item_id, field, record["wrapped_key"], record["wrap_nonce"], record["nonce"],
             record["ciphertext"], record["key_version"], record["updated_at"], by,
             record.get("strength"), record.get("fingerprint")))


def get_secret(item_id: str, field: str = "main") -> dict | None:
    return row("SELECT * FROM secrets WHERE item_id=? AND field_key=?", (item_id, field))


def secret_state(item_id: str, field: str = "main") -> dict:
    r = row("SELECT updated_at, updated_by, strength FROM secrets WHERE item_id=? AND field_key=?",
            (item_id, field))
    return {"has_secret": bool(r), "secret_updated_at": r["updated_at"] if r else None,
            "secret_updated_by": r["updated_by"] if r else None,
            "secret_strength": r["strength"] if r else None}


def secret_fields(item_id: str) -> dict:
    """Which fields of one item hold a secret, and when each last changed."""
    return {r["field_key"]: {"has_secret": True, "secret_updated_at": r["updated_at"],
                             "secret_updated_by": r["updated_by"],
                             "secret_strength": r["strength"]}
            for r in rows("SELECT field_key, updated_at, updated_by, strength FROM secrets "
                          "WHERE item_id=?", (item_id,))}


def vault_rows() -> list:
    """Every stored password in use, with where it lives -- never what it is."""
    return rows(
        "SELECT s.item_id, s.field_key, s.updated_at, s.updated_by, s.strength, s.fingerprint, "
        "i.name, i.kind, i.org_id, i.fields_json, o.name AS org_name FROM secrets s "
        "JOIN items i ON i.id = s.item_id JOIN organizations o ON o.id = i.org_id "
        "WHERE i.archived = 0 ORDER BY o.name COLLATE NOCASE, i.name COLLATE NOCASE")


def unjudged_secrets() -> list:
    return rows("SELECT * FROM secrets WHERE fingerprint IS NULL")


def judge_secret(item_id: str, field: str, strength: int, fingerprint: str) -> None:
    with write() as conn:
        conn.execute("UPDATE secrets SET strength=?, fingerprint=? WHERE item_id=? AND field_key=?",
                     (strength, fingerprint, item_id, field))


def drop_secret(item_id: str, field: str = "main") -> None:
    with write() as conn:
        conn.execute("DELETE FROM secrets WHERE item_id=? AND field_key=?", (item_id, field))


# --------------------------------------------------------------------------- #
# Network adapters, and the switch ports they hang on
#
# The connection is kept on the *port*, not on the adapter. That way a port can
# exist while empty -- which is how you find a free one -- and the database
# itself refuses to let two machines claim the same port, rather than trusting
# everyone to notice.
#
# Ports are not created in advance. A 48-port switch would mean 48 empty rows
# waiting for someone to use them, and changing the port count would mean
# reconciling them. Only a port somebody has actually done something with is
# stored; the rest of the list is worked out from the switch's port count.
# --------------------------------------------------------------------------- #
ADAPTER_FIELDS = {"name": "Naam", "mac": "MAC-adres", "ipv4": "IPv4-adres",
                  "ipv6": "IPv6-adres", "assignment": "Toewijzing",
                  "vlan": "VLAN", "speed": "Snelheid"}


def record(item_id: str, action: str, changes: list, by: str | None,
           source: str = "manual") -> None:
    """Write one line of history by hand, for the things that are not fields --
    an adapter added, a cable moved to another port."""
    with write() as conn:
        conn.execute("INSERT INTO revisions (item_id, at, user_email, source, action, "
                     "changes_json) VALUES (?, ?, ?, ?, ?, ?)",
                     (item_id, time.time(), by, source, action, json.dumps(changes)))


def list_adapters(item_id: str) -> list:
    """Every adapter of one machine, each with the port it is patched into."""
    out = []
    for r in rows("SELECT * FROM adapters WHERE item_id=? ORDER BY name COLLATE NOCASE", (item_id,)):
        r = dict(r)
        r["port"] = row(
            "SELECT p.number, p.label, p.vlan, i.id AS switch_id, i.name AS switch_name "
            "FROM switch_ports p JOIN items i ON i.id = p.switch_id WHERE p.adapter_id=?",
            (r["id"],))
        out.append(r)
    return out


def get_adapter(adapter_id: str) -> dict | None:
    return row("SELECT * FROM adapters WHERE id=?", (adapter_id,))


def add_adapter(item_id: str, values: dict, source: str = "manual") -> dict:
    now = time.time()
    adapter_id = uuid.uuid4().hex[:12]
    keys = [k for k in ADAPTER_FIELDS if k in values]
    with write() as conn:
        conn.execute(
            f"INSERT INTO adapters (id, item_id, source, created_at, updated_at"
            f"{''.join(', ' + k for k in keys)}) "
            f"VALUES (?, ?, ?, ?, ?{', ?' * len(keys)})",
            (adapter_id, item_id, source, now, now, *[values[k] for k in keys]))
    return get_adapter(adapter_id)


def update_adapter(adapter_id: str, values: dict) -> tuple:
    """Returns the adapter and what changed, so the caller can write it down."""
    before = get_adapter(adapter_id)
    if not before:
        raise KeyError(adapter_id)
    keys = [k for k in ADAPTER_FIELDS if k in values]
    changes = [{"key": k, "label": f"{before['name'] or 'Adapter'} – {ADAPTER_FIELDS[k]}",
                "from": before[k] or "", "to": values[k] or ""}
               for k in keys if (before[k] or "") != (values[k] or "")]
    if keys:
        with write() as conn:
            conn.execute(f"UPDATE adapters SET {', '.join(k + '=?' for k in keys)}, updated_at=? "
                         f"WHERE id=?", (*[values[k] for k in keys], time.time(), adapter_id))
    return get_adapter(adapter_id), changes


def delete_adapter(adapter_id: str) -> None:
    with write() as conn:
        conn.execute("DELETE FROM adapters WHERE id=?", (adapter_id,))


def sync_adapters(item_id: str, nics: list) -> None:
    """Bring a machine's adapters in line with what the RMM reports.

    Matched on the MAC address rather than on position or name, so an adapter
    that is renamed keeps the port it is patched into -- the MAC is the thing
    that is actually on the end of the cable.
    """
    existing = {(a["mac"] or "").lower(): a for a in
                rows("SELECT * FROM adapters WHERE item_id=? AND source='rmm'", (item_id,))}
    seen = set()
    for nic in nics or []:
        mac = (nic.get("mac") or "").lower()
        if not mac:
            continue                      # without a MAC there is nothing to match on
        seen.add(mac)
        values = {"name": nic.get("name") or "", "mac": nic.get("mac") or "",
                  "ipv4": ", ".join(nic.get("ipv4") or []),
                  "ipv6": ", ".join(nic.get("ipv6") or [])}
        if mac in existing:
            update_adapter(existing[mac]["id"], values)
        else:
            add_adapter(item_id, values, source="rmm")
    for mac, adapter in existing.items():
        if mac not in seen:
            delete_adapter(adapter["id"])


# --------------------------------------------------------------------------- #
# Ports
# --------------------------------------------------------------------------- #
def ports_of(switch_id: str, count: int) -> list:
    """The patch list of one switch: every port, taken or free.

    A port beyond the switch's port count is still listed when something is on
    it -- lowering the number in a form should not quietly hide a machine.
    """
    stored = {}
    for r in rows(
            "SELECT p.*, a.name AS adapter_name, a.mac AS adapter_mac, "
            "i.id AS item_id, i.name AS item_name, i.kind AS item_kind "
            "FROM switch_ports p LEFT JOIN adapters a ON a.id = p.adapter_id "
            "LEFT JOIN items i ON i.id = a.item_id WHERE p.switch_id=?", (switch_id,)):
        stored[r["number"]] = r
    highest = max([count or 0] + list(stored) + [0])
    out = []
    for number in range(1, highest + 1):
        r = stored.get(number)
        out.append({
            "number": number,
            "beyond": number > (count or 0),
            "label": (r or {}).get("label") or "",
            "vlan": (r or {}).get("vlan") or "",
            "adapter": ({"id": r["adapter_id"], "name": r["adapter_name"],
                         "mac": r["adapter_mac"], "item_id": r["item_id"],
                         "item_name": r["item_name"], "item_kind": r["item_kind"]}
                        if r and r.get("adapter_id") else None),
        })
    return out


def set_port(switch_id: str, number: int, label=None, vlan=None,
             adapter_id: str | None = None, clear_adapter: bool = False,
             by: str | None = None) -> None:
    """Write one port. `adapter_id` patches something in; `clear_adapter`
    unpatches whatever was there."""
    now = time.time()
    with write() as conn:
        existing = conn.execute(
            "SELECT * FROM switch_ports WHERE switch_id=? AND number=?",
            (switch_id, number)).fetchone()
        if adapter_id:
            # One cable per port, and one port per cable: an adapter moving to a
            # new port leaves its old one empty rather than appearing on both.
            conn.execute("UPDATE switch_ports SET adapter_id=NULL, updated_at=? "
                         "WHERE adapter_id=?", (now, adapter_id))
        if existing:
            sets, args = [], []
            if label is not None:
                sets.append("label=?")
                args.append(label)
            if vlan is not None:
                sets.append("vlan=?")
                args.append(vlan)
            if adapter_id or clear_adapter:
                sets.append("adapter_id=?")
                args.append(None if clear_adapter else adapter_id)
            sets += ["updated_at=?", "updated_by=?"]
            args += [now, by]
            conn.execute(f"UPDATE switch_ports SET {', '.join(sets)} WHERE id=?",
                         (*args, existing["id"]))
        else:
            conn.execute(
                "INSERT INTO switch_ports (id, switch_id, number, label, vlan, adapter_id, "
                "updated_at, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex[:12], switch_id, number, label or None, vlan or None,
                 None if clear_adapter else adapter_id, now, by))


def port_of_adapter(adapter_id: str) -> dict | None:
    return row("SELECT p.number, p.switch_id, i.name AS switch_name FROM switch_ports p "
               "JOIN items i ON i.id = p.switch_id WHERE p.adapter_id=?", (adapter_id,))


def port_holder(switch_id: str, number: int) -> dict | None:
    """What is already on a port, so a second claim can say what is in the way."""
    return row("SELECT a.id, a.name, i.name AS item_name FROM switch_ports p "
               "JOIN adapters a ON a.id = p.adapter_id JOIN items i ON i.id = a.item_id "
               "WHERE p.switch_id=? AND p.number=?", (switch_id, number))


# --------------------------------------------------------------------------- #
# Types people define themselves
#
# Stored as a definition, not as a table per type: a type is a label and a list
# of fields, and the items made from it live in the same `items` table as
# everything else. That is what makes history, links, search and access work
# for a type nobody had thought of when this was written.
# --------------------------------------------------------------------------- #
def _type_out(r: dict) -> dict:
    r = dict(r)
    r["fields"] = json.loads(r.pop("fields_json", None) or "[]")
    r["columns"] = json.loads(r.pop("columns_json", None) or "[]")
    r["adapters"] = bool(r.get("adapters"))
    return r


def list_item_types() -> list:
    return [_type_out(r) for r in
            rows("SELECT * FROM item_types ORDER BY label COLLATE NOCASE")]


def get_item_type(type_id: str) -> dict | None:
    r = row("SELECT * FROM item_types WHERE id=?", (type_id,))
    return _type_out(r) if r else None


def save_item_type(type_id: str, spec: dict, by: str | None, creating: bool) -> dict:
    now = time.time()
    with write() as conn:
        if creating:
            conn.execute(
                "INSERT INTO item_types (id, label, plural, icon, sub, backref, adapters, "
                "columns_json, fields_json, created_at, created_by, updated_at, updated_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (type_id, spec["label"], spec["plural"], spec.get("icon"), spec.get("sub"),
                 spec.get("backref"), int(bool(spec.get("adapters"))),
                 json.dumps(spec.get("columns") or []), json.dumps(spec.get("fields") or []),
                 now, by, now, by))
        else:
            conn.execute(
                "UPDATE item_types SET label=?, plural=?, icon=?, sub=?, backref=?, adapters=?, "
                "columns_json=?, fields_json=?, updated_at=?, updated_by=? WHERE id=?",
                (spec["label"], spec["plural"], spec.get("icon"), spec.get("sub"),
                 spec.get("backref"), int(bool(spec.get("adapters"))),
                 json.dumps(spec.get("columns") or []), json.dumps(spec.get("fields") or []),
                 now, by, type_id))
    return get_item_type(type_id)


def delete_item_type(type_id: str) -> None:
    with write() as conn:
        conn.execute("DELETE FROM item_types WHERE id=?", (type_id,))


def items_of_kind(kind: str) -> int:
    """How many things exist of a type -- what a delete has to answer to."""
    return get_conn().execute("SELECT COUNT(*) FROM items WHERE kind=?", (kind,)).fetchone()[0]


# --------------------------------------------------------------------------- #
# Items shut off to named people
# --------------------------------------------------------------------------- #
def hidden_items(email: str) -> set:
    """Items that are restricted to other people -- the ones this person must
    not see at all, anywhere."""
    return {r["item_id"] for r in rows(
        "SELECT DISTINCT item_id FROM item_access WHERE item_id NOT IN "
        "(SELECT item_id FROM item_access WHERE user_email=?)", (email.lower(),))}


def restricted_items() -> set:
    return {r["item_id"] for r in rows("SELECT DISTINCT item_id FROM item_access")}


def item_people(item_id: str) -> list:
    return [r["user_email"] for r in
            rows("SELECT user_email FROM item_access WHERE item_id=? ORDER BY user_email",
                 (item_id,))]


def set_item_people(item_id: str, emails: list) -> None:
    with write() as conn:
        conn.execute("DELETE FROM item_access WHERE item_id=?", (item_id,))
        conn.executemany("INSERT OR IGNORE INTO item_access (item_id, user_email) VALUES (?, ?)",
                         [(item_id, e.lower()) for e in emails])


def people_at(org_id: str) -> list:
    """Everyone who can see a customer: those given it, and administrators."""
    return rows(
        "SELECT email, display_name, is_admin FROM users WHERE is_admin=1 OR email IN "
        "(SELECT user_email FROM org_users WHERE org_id=?) ORDER BY email", (org_id,))


# --------------------------------------------------------------------------- #
# Documentation sent to the RMM
# --------------------------------------------------------------------------- #
def doc_push_state() -> dict:
    return {r["device_id"]: r["hash"] for r in rows("SELECT device_id, hash FROM doc_pushes")}


def replace_doc_pushes(state: dict) -> None:
    now = time.time()
    with write() as conn:
        conn.execute("DELETE FROM doc_pushes")
        conn.executemany("INSERT INTO doc_pushes (device_id, hash, pushed_at) VALUES (?, ?, ?)",
                         [(device, digest, now) for device, digest in state.items()])


def doc_push_done(sent: dict, cleared: list) -> None:
    now = time.time()
    with write() as conn:
        for device_id, digest in sent.items():
            conn.execute("INSERT INTO doc_pushes (device_id, hash, pushed_at) VALUES (?, ?, ?) "
                         "ON CONFLICT(device_id) DO UPDATE SET hash=excluded.hash, "
                         "pushed_at=excluded.pushed_at", (device_id, digest, now))
        for device_id in cleared:
            conn.execute("DELETE FROM doc_pushes WHERE device_id=?", (device_id,))


# --------------------------------------------------------------------------- #
# Share links
# --------------------------------------------------------------------------- #
def add_share(item_id: str, field: str, token_hash: str, sealed: str, note: str | None,
              by: str | None, expires_at: float, max_views: int) -> dict:
    share_id = uuid.uuid4().hex[:12]
    with write() as conn:
        conn.execute(
            "INSERT INTO shares (id, item_id, field_key, token_hash, sealed_json, note, "
            "created_at, created_by, expires_at, max_views) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (share_id, item_id, field, token_hash, sealed, note, time.time(), by,
             expires_at, max_views))
    return get_share(share_id)


def get_share(share_id: str) -> dict | None:
    return row("SELECT * FROM shares WHERE id=?", (share_id,))


def share_by_token(token_hash: str) -> dict | None:
    return row("SELECT * FROM shares WHERE token_hash=?", (token_hash,))


def shares_of(item_id: str) -> list:
    return rows("SELECT id, item_id, field_key, note, created_at, created_by, expires_at, "
                "max_views, views, last_view, revoked_at, revoked_why FROM shares "
                "WHERE item_id=? ORDER BY created_at DESC", (item_id,))


def count_view(share_id: str) -> bool:
    """Take one look, if one is left. Done in a single statement, so two people
    opening a one-time link at the same moment cannot both get it."""
    now = time.time()
    with write() as conn:
        cur = conn.execute(
            "UPDATE shares SET views = views + 1, last_view=? WHERE id=? AND revoked_at IS NULL "
            "AND views < max_views AND expires_at > ?", (now, share_id, now))
        return cur.rowcount == 1


def revoke_share(share_id: str, why: str) -> None:
    with write() as conn:
        conn.execute("UPDATE shares SET revoked_at=?, revoked_why=? WHERE id=? AND revoked_at IS NULL",
                     (time.time(), why, share_id))
    forget_spent_shares()


def forget_spent_shares() -> int:
    """Drop the sealed copy from every link that can no longer be opened. The
    row stays, for the list and the log; the old password it carried has no
    business outliving the link."""
    now = time.time()
    with write() as conn:
        cur = conn.execute(
            "UPDATE shares SET sealed_json='' WHERE sealed_json != '' AND "
            "(revoked_at IS NOT NULL OR views >= max_views OR expires_at <= ?)", (now,))
        return cur.rowcount


def revoke_open_shares(item_id: str, field: str, why: str) -> int:
    now = time.time()
    with write() as conn:
        cur = conn.execute(
            "UPDATE shares SET revoked_at=?, revoked_why=? WHERE item_id=? AND field_key=? "
            "AND revoked_at IS NULL AND views < max_views AND expires_at > ?",
            (now, why, item_id, field, now))
        closed = cur.rowcount
    forget_spent_shares()
    return closed
