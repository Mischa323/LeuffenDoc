"""Talking to the Leuffen RMM.

The RMM is where accounts and customers live. LeuffenDoc asks it two things:

  * **who is this?** -- a single-use ticket the browser brought back, redeemed
    server-to-server with the API key, so the ticket alone is not enough to
    become anybody; and
  * **who exists, and what may they see?** -- the periodic sync, which is what
    makes access granted (or withdrawn) in the RMM show up here without a second
    administration.

Nothing here raises on a network failure by itself: the RMM being unreachable
must not take LeuffenDoc down with it, which is exactly why the Microsoft 365
sign-in exists alongside this one.
"""
from __future__ import annotations

import logging
import os
import time
import urllib.parse

import httpx

from . import database

log = logging.getLogger("leuffendoc.rmm")

# What the last sync did, for the status shown in the interface.
last_sync: dict = {"at": None, "ok": None, "detail": "nog niet uitgevoerd",
                   "users": 0, "orgs": 0}


def _setting(key: str) -> str:
    return (os.environ.get(key) or database.get_setting(key) or "").strip()


def base_url() -> str:
    """Where *this server* reaches the RMM. Behind the same reverse proxy that
    is often an internal address."""
    return _setting("DOC_RMM_URL").rstrip("/")


def public_base_url() -> str:
    """Where *a browser* reaches the RMM. The same address in a simple setup,
    and a different one whenever the two servers talk over an internal network
    the browser knows nothing about -- send someone to that and they land
    nowhere."""
    return (_setting("DOC_RMM_PUBLIC_URL") or _setting("DOC_RMM_URL")).rstrip("/")


def api_key() -> str:
    return _setting("DOC_RMM_API_KEY")


def configured() -> bool:
    return bool(base_url() and api_key())


def _client() -> httpx.Client:
    # An RMM on a self-signed certificate is normal on a LAN; the operator says
    # so explicitly rather than us quietly accepting any certificate.
    verify = _setting("DOC_RMM_INSECURE_TLS") not in ("1", "true", "yes")
    return httpx.Client(timeout=15.0, verify=verify,
                        headers={"X-API-Key": api_key()})


def handoff_url(return_to: str) -> str:
    """Where to send the browser to have the RMM identify someone."""
    return (f"{public_base_url()}/auth/sso/handoff"
            f"?return={urllib.parse.quote(return_to, safe='')}")


def exchange_ticket(ticket: str) -> dict:
    """Redeem a hand-off ticket. Returns the identity, or raises."""
    with _client() as client:
        r = client.post(f"{base_url()}/api/v1/sso/exchange", json={"ticket": ticket})
    if r.status_code == 401:
        raise PermissionError(r.json().get("detail", "De aanmeldlink is verlopen"))
    r.raise_for_status()
    return r.json()


def fetch_orgs() -> list[dict]:
    with _client() as client:
        r = client.get(f"{base_url()}/api/v1/orgs")
    r.raise_for_status()
    return r.json().get("orgs", [])


def fetch_users() -> list[dict]:
    with _client() as client:
        r = client.get(f"{base_url()}/api/v1/users")
    r.raise_for_status()
    return r.json().get("users", [])


# --------------------------------------------------------------------------- #
# Bringing identities across
# --------------------------------------------------------------------------- #
def apply_identity(identity: dict, source: str = "rmm") -> dict:
    """Store one person and the customers they may see, exactly as the RMM has
    it. Replacing their access (rather than adding to it) is deliberate: access
    taken away there has to disappear here too."""
    email = (identity.get("email") or "").strip().lower()
    if not email:
        raise ValueError("identity has no email address")
    user = database.upsert_user(email,
                                display_name=identity.get("display_name") or None,
                                is_admin=bool(identity.get("is_global_admin")),
                                source=source)
    org_ids = []
    for org in identity.get("orgs") or []:
        if not org.get("id"):
            continue
        org_ids.append(database.upsert_org(org.get("name") or org["id"], rmm_org_id=org["id"]))
    database.set_user_orgs(email, org_ids)
    return user


def _explain(exc: Exception) -> str:
    """What went wrong, in a sentence an administrator can act on. The library's
    own message is a URL and a link to a status-code reference, which says
    nothing about which of the three likely causes this is."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return "de RMM weigert de API-sleutel (DOC_RMM_API_KEY)"
        if code == 404:
            return ("dit adres is geen RMM, of de RMM is te oud voor deze koppeling "
                    f"({exc.request.url.path} bestaat daar niet)")
        return f"de RMM antwoordde met {code}"
    if isinstance(exc, httpx.ConnectError):
        return f"geen verbinding met {base_url()}"
    if isinstance(exc, httpx.TimeoutException):
        return f"{base_url()} antwoordt niet op tijd"
    return f"{type(exc).__name__}: {exc}"[:200]


def sync() -> dict:
    """Pull every account and its customers from the RMM."""
    if not configured():
        last_sync.update(at=time.time(), ok=None, detail="de RMM is niet ingesteld")
        return last_sync
    try:
        # Customers first, and on their own: one that nobody has been assigned
        # to yet still needs to exist here, ready to be documented.
        orgs = fetch_orgs()
        users = fetch_users()
    except Exception as exc:                       # network, TLS, a wrong key
        log.warning("sync from the RMM failed: %r", exc)
        last_sync.update(at=time.time(), ok=False, detail=_explain(exc))
        return last_sync
    for org in orgs:
        if org.get("id"):
            database.upsert_org(org.get("name") or org["id"], rmm_org_id=org["id"])
    for identity in users:
        try:
            apply_identity(identity)
        except Exception as exc:
            log.warning("could not apply %s: %r", identity.get("email"), exc)
    last_sync.update(at=time.time(), ok=True, detail="gelukt",
                     users=len(users), orgs=len(orgs))
    database.audit("rmm.sync", detail=f"{len(users)} gebruikers, {len(orgs)} klanten")
    return last_sync
