"""Who is signed in.

Sessions are a signed cookie (itsdangerous), the same approach the RMM uses, so
nothing has to be kept server-side and a restart doesn't sign everyone out.

Two ways in, both landing here:

  * **through the RMM** -- the RMM already knows this person, mints a single-use
    ticket, and LeuffenDoc exchanges it server-to-server for their identity,
    customers and permissions. That keeps 2FA, IP rules, Microsoft 365 and
    account removal in one place (see `rmm.py`).
  * **Microsoft 365 directly** -- the fallback for when the RMM is unreachable
    or someone has no RMM account.

The sign-in routes themselves live in `main.py`; this module is the plumbing:
the secret, the cookie, and the dependency that turns a request into a user.
"""
from __future__ import annotations

import ipaddress
import os
import secrets

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import database, settings

COOKIE = "leuffendoc_session"


def session_days() -> int:
    return int(settings.get("DOC_SESSION_DAYS"))


def _resolve_secret() -> str:
    """The session-signing secret: the environment first, then one generated
    into the data volume. Generating it (rather than shipping a default) means a
    fresh install is never signed with a key anyone else could know."""
    env = os.environ.get("DOC_SESSION_SECRET")
    if env:
        return env
    saved = database.get_setting("DOC_SESSION_SECRET")
    if saved:
        return saved
    fresh = secrets.token_urlsafe(48)
    database.set_setting("DOC_SESSION_SECRET", fresh)
    return fresh


_serializer: URLSafeTimedSerializer | None = None


def serializer() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        _serializer = URLSafeTimedSerializer(_resolve_secret(), salt="leuffendoc-session")
    return _serializer


def make_cookie(email: str) -> str:
    return serializer().dumps({"email": email.lower()})


def read_cookie(value: str) -> dict | None:
    try:
        return serializer().loads(value, max_age=session_days() * 86400)
    except (BadSignature, SignatureExpired):
        return None


def cookie_kwargs() -> dict:
    """Cookie flags. `Secure` is on unless explicitly disabled, which is only
    sensible for local development over plain HTTP."""
    return {"httponly": True, "secure": bool(settings.get("DOC_SECURE_COOKIES")), "samesite": "lax",
            "max_age": session_days() * 86400, "path": "/"}


def trust_proxy() -> bool:
    return bool(settings.get("DOC_TRUST_PROXY"))


def proxy_ips() -> str:
    """Where the reverse proxy connects from; empty or "*" means anywhere."""
    return (settings.get("DOC_PROXY_IPS") or "").strip()


def _from_proxy(request: Request) -> bool:
    """Whether this connection came from the proxy we were told about -- the
    only case in which its forwarded headers are believed."""
    if not trust_proxy() or not request.client:
        return False
    allowed = proxy_ips()
    if allowed in ("", "*"):
        return True
    try:
        peer = ipaddress.ip_address(request.client.host)
    except ValueError:
        return False
    for part in allowed.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if peer in ipaddress.ip_network(part, strict=False):
                return True
        except ValueError:
            continue
    return False


def request_scheme(request: Request) -> str:
    """http or https as the visitor used it, which behind a proxy is not what
    arrives here."""
    if _from_proxy(request):
        proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
        if proto in ("http", "https"):
            return proto
    return request.url.scheme


def client_ip(request: Request) -> str:
    """The caller's address.

    Who resolves `X-Forwarded-For` depends on `DOC_PROXY_IPS`:

    * **Pinned to the proxy** -- uvicorn has already done it, and only for
      connections that actually came from that proxy, so someone reaching the
      container directly cannot write their own address into the audit log. Its
      answer stands.
    * **Left as `*`** -- uvicorn believes any caller and takes the *first* entry
      of the header, which is exactly the part a browser can write itself. So
      read it here instead and take the **last** entry: each proxy appends what
      it saw, so the last one is what *our* proxy saw. (A proxy told to
      overwrite rather than append sends one entry, and the two agree.)

    See `run.py` and the reverse-proxy section of the README.
    """
    if _from_proxy(request):
        hops = forwarded_hops(request)
        if hops:
            return hops[-1]
    return request.client.host if request.client else "?"


def forwarded_hops(request: Request) -> list[str]:
    """The addresses in `X-Forwarded-For`, as sent. More than one means the
    proxy is *appending* to a header the visitor's browser may have supplied,
    and the oldest entry is then whatever they cared to claim."""
    raw = request.headers.get("x-forwarded-for") or ""
    return [h.strip() for h in raw.split(",") if h.strip()]


def bootstrap_admins() -> set[str]:
    """Accounts that are administrators whatever the database says.

    `DOC_BOOTSTRAP_ADMIN` (one or more addresses, comma separated) is both the
    way to set up a fresh install and the way back in when nobody is left with
    the rights -- rather than editing the database by hand.
    """
    # Both count: the ones chosen at set-up, and any the container is started
    # with -- the latter being the way back in if the former were lost.
    raw = f"{os.environ.get('DOC_BOOTSTRAP_ADMIN', '')},{database.get_setting('DOC_BOOTSTRAP_ADMIN') or ''}"
    return {e.strip().lower() for e in raw.replace(";", ",").split(",") if e.strip()}


def optional_user(request: Request) -> dict | None:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    data = read_cookie(raw)
    if not data:
        return None
    user = database.get_user(data.get("email", ""))
    if not user:
        # Signed out everywhere the moment the account is gone -- which is how a
        # removal in the RMM reaches this side.
        return None
    if user["email"] in bootstrap_admins():
        user["is_admin"] = 1
    return user


def current_user(request: Request) -> dict:
    user = optional_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    return user


def require_admin(user: dict) -> None:
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Administrators only")


def sign_in(response, email: str) -> None:
    """Attach the session cookie for this person to a response."""
    response.set_cookie(COOKIE, make_cookie(email), **cookie_kwargs())


def sign_out(response) -> None:
    response.delete_cookie(COOKIE, path="/")
