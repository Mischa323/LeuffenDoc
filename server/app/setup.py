"""The first start: a set-up screen instead of environment variables.

A fresh LeuffenDoc opens on ``/setup``. Everything the container used to need
in its environment -- its address, the link with the RMM, who administers it,
the reverse proxy in front of it -- is chosen there and kept in the database.
The environment still wins where it is set, which is how an operator pins a
value or gets back in; it is simply no longer needed.

Until set-up is done, anyone who can reach the page could make the server
theirs, and point it at an RMM of their own. So the page asks for a **set-up
code** first, which is only printed in the container's log: whoever can read
that runs the container. Five wrong attempts and a new code is printed, so it
cannot be guessed at.
"""
from __future__ import annotations

import os
import secrets
import threading

from fastapi import Request

from . import database, settings

DONE = "DOC_SETUP_DONE"
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"      # nothing to misread
MAX_ATTEMPTS = 5

_code: str | None = None
_attempts = 0
_lock = threading.Lock()

# A container started the old way already says what it is; it never sees the
# set-up screen.
_CONFIGURED_BY_ENV = ("DOC_RMM_URL", "DOC_PUBLIC_URL", "DOC_M365_CLIENT_ID", "DOC_DEV_LOGIN",
                      "DOC_BOOTSTRAP_ADMIN")


def needs() -> bool:
    return not database.get_setting(DONE)


def mark_done() -> None:
    database.set_setting(DONE, "1")


def settle_existing() -> None:
    """At start-up: an installation that already has people, or was configured
    through its environment, is set up -- it must never be sent to /setup."""
    if not needs():
        return
    if database.user_count() > 0 or any((os.environ.get(k) or "").strip() for k in _CONFIGURED_BY_ENV):
        mark_done()


def _new_code() -> str:
    global _code, _attempts
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    _code, _attempts = f"{raw[:4]}-{raw[4:]}", 0
    bar = "=" * 64
    print(f"\n{bar}\n  LeuffenDoc is nog niet ingesteld.\n"
          f"  Open de pagina in je browser en vul deze installatiecode in:\n\n"
          f"      {_code}\n\n{bar}\n", flush=True)
    return _code


def announce() -> None:
    """Print the code, if there is set-up to do."""
    if needs():
        with _lock:
            _new_code()


def check(code: str) -> bool:
    """The code, compared in constant time. Too many misses and it changes."""
    global _attempts
    with _lock:
        if _code is None:
            _new_code()
        given = (code or "").strip().upper().replace(" ", "")
        if len(given) == 8:
            given = f"{given[:4]}-{given[4:]}"
        if secrets.compare_digest(given.encode(), _code.encode()):
            return True
        _attempts += 1
        if _attempts >= MAX_ATTEMPTS:
            _new_code()
        return False


def detect(request: Request) -> dict:
    """What the server can tell from the browser's own request -- the starting
    values of the set-up screen. A request that carries X-Forwarded-For came
    through a reverse proxy, and the address it came from is that proxy's."""
    forwarded = request.headers.get("x-forwarded-for")
    proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    peer = request.client.host if request.client else ""
    return {"via_proxy": bool(forwarded), "proxy_address": peer if forwarded else "",
            "scheme": proto or request.url.scheme, "host": host,
            "vault_key_from_env": bool((os.environ.get("DOC_SECRET_KEY") or "").strip())}


def apply(values: dict) -> None:
    """Store what the set-up screen chose. Anything the environment already
    fixes is left to it."""
    public = (values.get("public_url") or "").strip().rstrip("/")
    chosen = {
        "DOC_PUBLIC_URL": public,
        "DOC_TRUST_PROXY": bool(values.get("trust_proxy")),
        "DOC_PROXY_IPS": (values.get("proxy_ips") or "").strip(),
        # Secure cookies whenever people arrive over https -- which behind a
        # proxy is the normal case, and the only one that should be.
        "DOC_SECURE_COOKIES": public.startswith("https://"),
    }
    for key, value in chosen.items():
        if not settings.from_environment(key):
            settings.put(key, value)
    # Administrators are stored whatever the environment says: the two lists
    # count together (see auth.bootstrap_admins).
    admins = [a.strip().lower() for a in (values.get("admins") or []) if a and "@" in a]
    if admins:
        settings.put("DOC_BOOTSTRAP_ADMIN", ", ".join(sorted(set(admins))))
