"""The settings an administrator can change from the interface.

One list, so the page, the server and the code that reads a setting all agree
on what exists. Each value comes from, in order:

  1. the **environment** -- which wins, because whoever runs the container has
     the last word; the page shows such a value as fixed and says why;
  2. the **database** -- what was saved from the page; and
  3. the **default** below.

Two settings are secrets (the RMM's API key and the Microsoft 365 client
secret). They are stored sealed with the vault's key, never sent back to a
browser, and the page only learns whether one is set.

What stays out of here on purpose: the proxy, cookies, the port and the
bootstrap administrators. Those decide whether anyone can reach or sign in to
this page at all, so changing them from it could lock the door behind you.
"""
from __future__ import annotations

import base64
import json
import os

from . import database

SEALED = "sealed:"

# key -> how to treat it. `group` places it on the page.
SPEC: dict[str, dict] = {
    # -- General
    "DOC_PUBLIC_URL": {"group": "algemeen", "type": "url", "default": ""},
    "EXPIRY_WARN_DAYS": {"group": "algemeen", "type": "int", "default": 60,
                         "min": 1, "max": 365},

    # -- The RMM link
    "DOC_RMM_URL": {"group": "rmm", "type": "url", "default": ""},
    "DOC_RMM_PUBLIC_URL": {"group": "rmm", "type": "url", "default": ""},
    "DOC_RMM_API_KEY": {"group": "rmm", "type": "secret", "default": ""},
    "DOC_RMM_INSECURE_TLS": {"group": "rmm", "type": "bool", "default": False},
    "DOC_SYNC_MINUTES": {"group": "rmm", "type": "int", "default": 15, "min": 1, "max": 1440},

    # -- Microsoft 365
    "DOC_M365_TENANT": {"group": "m365", "type": "text", "default": ""},
    "DOC_M365_CLIENT_ID": {"group": "m365", "type": "text", "default": ""},
    "DOC_M365_CLIENT_SECRET": {"group": "m365", "type": "secret", "default": ""},
    "DOC_M365_ALLOW": {"group": "m365", "type": "text", "default": ""},

    # -- Passwords
    "PW_LENGTH": {"group": "wachtwoorden", "type": "int", "default": 20, "min": 8, "max": 128},
    "PW_LOWER": {"group": "wachtwoorden", "type": "bool", "default": True},
    "PW_UPPER": {"group": "wachtwoorden", "type": "bool", "default": True},
    "PW_DIGITS": {"group": "wachtwoorden", "type": "bool", "default": True},
    "PW_SYMBOLS": {"group": "wachtwoorden", "type": "bool", "default": True},
    "PW_SYMBOL_SET": {"group": "wachtwoorden", "type": "text", "default": "!@#%^&*-_=+"},
    "PW_NO_LOOKALIKES": {"group": "wachtwoorden", "type": "bool", "default": True},
    "PW_EACH_CLASS": {"group": "wachtwoorden", "type": "bool", "default": True},
    "PW_REVEAL_SECONDS": {"group": "wachtwoorden", "type": "int", "default": 30,
                          "min": 5, "max": 600},
    "PW_MAX_AGE_DAYS": {"group": "wachtwoorden", "type": "int", "default": 365,
                        "min": 0, "max": 3650},
}

# Settings every signed-in person's browser needs, and nothing more: how to
# make a password, how long to show one, and when a date starts to warn.
PUBLIC = ["PW_LENGTH", "PW_LOWER", "PW_UPPER", "PW_DIGITS", "PW_SYMBOLS", "PW_SYMBOL_SET",
          "PW_NO_LOOKALIKES", "PW_EACH_CLASS", "PW_REVEAL_SECONDS", "EXPIRY_WARN_DAYS"]


def from_environment(key: str) -> bool:
    return bool((os.environ.get(key) or "").strip())


def _coerce(key: str, raw):
    spec = SPEC[key]
    kind = spec["type"]
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in ("1", "true", "yes", "ja", "aan", "on")
    if kind == "int":
        try:
            value = int(str(raw).strip())
        except ValueError:
            return spec["default"]
        return max(spec.get("min", value), min(spec.get("max", value), value))
    return str(raw).strip()


def get(key: str):
    """The value in force, typed."""
    spec = SPEC[key]
    if spec["type"] == "secret":
        return secret(key)
    env = (os.environ.get(key) or "").strip()
    if env:
        return _coerce(key, env)
    stored = database.get_setting(key)
    if stored not in (None, ""):
        return _coerce(key, stored)
    return spec["default"]


def secret(key: str) -> str:
    """A secret setting, unsealed. Empty when there is none."""
    env = (os.environ.get(key) or "").strip()
    if env:
        return env
    stored = database.get_setting(key) or ""
    if not stored.startswith(SEALED):
        return stored                          # written before sealing existed
    from . import vault
    raw = json.loads(stored[len(SEALED):])
    record = {k: base64.b64decode(v) for k, v in raw.items() if k != "key_version"}
    record["key_version"] = raw.get("key_version", 1)
    try:
        return vault.unseal(record)
    except Exception:
        return ""


def put(key: str, value) -> None:
    spec = SPEC[key]
    if spec["type"] == "secret":
        text = str(value or "")
        if not text:
            database.set_setting(key, "")
            return
        from . import vault
        record = vault.seal(text)
        packed = {k: base64.b64encode(v).decode() for k, v in record.items()
                  if isinstance(v, (bytes, bytearray))}
        packed["key_version"] = record["key_version"]
        database.set_setting(key, SEALED + json.dumps(packed))
        return
    value = _coerce(key, value)
    database.set_setting(key, "1" if value is True else "0" if value is False else str(value))


def describe() -> dict:
    """Everything the settings page shows: each value, where it comes from,
    and -- for a secret -- only whether there is one."""
    out = {}
    for key, spec in SPEC.items():
        entry = {"type": spec["type"], "group": spec["group"],
                 "from_env": from_environment(key), "default": spec["default"]}
        if spec["type"] == "secret":
            value = secret(key)
            entry["set"] = bool(value)
            # The last four characters, so two keys can be told apart without
            # the page ever holding one.
            entry["hint"] = f"…{value[-4:]}" if len(value) >= 8 else ""
        else:
            entry["value"] = get(key)
            for bound in ("min", "max"):
                if bound in spec:
                    entry[bound] = spec[bound]
        out[key] = entry
    return out


def public() -> dict:
    return {key: get(key) for key in PUBLIC}
