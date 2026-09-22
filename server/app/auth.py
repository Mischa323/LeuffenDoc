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

import os
import secrets

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import database

COOKIE = "leuffendoc_session"
SESSION_DAYS = int(os.environ.get("DOC_SESSION_DAYS", "30"))


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
        return serializer().loads(value, max_age=SESSION_DAYS * 86400)
    except (BadSignature, SignatureExpired):
        return None


def cookie_kwargs() -> dict:
    """Cookie flags. `Secure` is on unless explicitly disabled, which is only
    sensible for local development over plain HTTP."""
    secure = os.environ.get("DOC_SECURE_COOKIES", "1") not in ("0", "false", "no")
    return {"httponly": True, "secure": secure, "samesite": "lax",
            "max_age": SESSION_DAYS * 86400, "path": "/"}


def trust_proxy() -> bool:
    return os.environ.get("DOC_TRUST_PROXY", "0") == "1"


def client_ip(request: Request) -> str:
    """The caller's address.

    Deliberately *not* read from `X-Forwarded-For` here. That resolution happens
    one layer down, in uvicorn, which only believes the header when the
    connection itself comes from an address named in `DOC_PROXY_IPS` -- so a
    caller reaching the container directly cannot write their own address into
    the audit log. See `run.py`, and the reverse-proxy section of the README for
    the matching proxy configuration.
    """
    return request.client.host if request.client else "?"


def forwarded_hops(request: Request) -> list[str]:
    """The addresses in `X-Forwarded-For`, as sent. More than one means the
    proxy is *appending* to a header the visitor's browser may have supplied,
    and the oldest entry is then whatever they cared to claim."""
    raw = request.headers.get("x-forwarded-for") or ""
    return [h.strip() for h in raw.split(",") if h.strip()]


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
