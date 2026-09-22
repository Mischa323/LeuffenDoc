"""Signing in with Microsoft 365 directly.

The fallback path: it works when the RMM is unreachable, and lets someone in who
has no RMM account at all. Such a person arrives with **no customers** -- what
they may see is still decided here, by an administrator, because nothing in
Microsoft 365 knows about our customers.

Mirrors the RMM's own MSAL setup, so a tenant configured for one works for the
other (a second redirect URI is all it needs).
"""
from __future__ import annotations

import os

from . import database

SCOPES = ["User.Read"]


def _setting(key: str) -> str:
    return (os.environ.get(key) or database.get_setting(key) or "").strip()


def configured() -> bool:
    return bool(_setting("DOC_M365_CLIENT_ID") and _setting("DOC_M365_TENANT"))


def redirect_uri() -> str:
    explicit = _setting("DOC_M365_REDIRECT_URI")
    if explicit:
        return explicit
    return (_setting("DOC_PUBLIC_URL").rstrip("/") or "") + "/auth/m365/callback"


def _app():
    import msal
    tenant = _setting("DOC_M365_TENANT")
    return msal.ConfidentialClientApplication(
        _setting("DOC_M365_CLIENT_ID"),
        authority=f"https://login.microsoftonline.com/{tenant}",
        client_credential=_setting("DOC_M365_CLIENT_SECRET"))


def login_url(state: str) -> str:
    return _app().get_authorization_request_url(
        SCOPES, state=state, redirect_uri=redirect_uri())


def exchange_code(code: str) -> str:
    """The signed-in person's email address, or raise."""
    result = _app().acquire_token_by_authorization_code(
        code, scopes=SCOPES, redirect_uri=redirect_uri())
    if "id_token_claims" not in result:
        raise PermissionError(result.get("error_description") or "aanmelden mislukt")
    claims = result["id_token_claims"]
    email = (claims.get("preferred_username") or claims.get("email")
             or claims.get("upn") or "").strip().lower()
    if not email:
        raise PermissionError("Microsoft 365 gaf geen e-mailadres terug")
    return email


def permitted(email: str) -> bool:
    """Who from the tenant may in. Empty means everyone the tenant lets through
    -- fine when the app registration is already restricted to the right people,
    and otherwise a list of addresses or domains to hold it to."""
    raw = _setting("DOC_M365_ALLOW")
    if not raw:
        return True
    allowed = {e.strip().lower() for e in raw.replace(";", ",").split(",") if e.strip()}
    domain = email.split("@")[-1]
    return email in allowed or domain in allowed or f"@{domain}" in allowed
