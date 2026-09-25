"""Linking with the RMM with one button.

The set-up screen (or Instellingen, later) asks only for the RMM's address.
The browser is sent there with this server's address and the hash of a secret
kept here (PKCE); an administrator of the RMM approves; the browser comes back
with a single-use code; and this server exchanges code and secret for an API
key over its own connection. The key never passes through a browser, and the
RMM sets this server's address on its side in the same step.

The RMM's address as a browser knows it is not always one this server can
reach -- the NAS may not reach its own public name, or the RMM may sit on a
self-signed certificate on the LAN. The code is only used once the exchange
actually reaches the RMM, so the page can ask for an address that does work
and try again.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
import urllib.parse

import httpx

TTL = 900
_pending: dict[str, dict] = {}
_lock = threading.Lock()


class Unreachable(Exception):
    """The RMM could not be reached from this server at that address."""


def clean_url(url: str) -> str | None:
    parts = urllib.parse.urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"


def start(rmm_url: str, public_url: str, mode: str, extra: dict | None = None) -> str:
    """Remember a pairing in progress; the address to send the browser to."""
    rmm = clean_url(rmm_url)
    if not rmm:
        raise ValueError("Vul het adres van de RMM in, beginnend met https://")
    doc = clean_url(public_url)
    if not doc:
        raise ValueError("Het adres van LeuffenDoc zelf ontbreekt")
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(24)
    now = time.time()
    with _lock:
        for old in [s for s, p in _pending.items() if p["expires"] < now]:
            _pending.pop(old, None)
        _pending[state] = {"verifier": verifier, "rmm_url": rmm, "server_url": rmm,
                           "insecure": False, "doc_url": doc, "mode": mode,
                           "extra": extra or {}, "code": None, "expires": now + TTL}
    return (f"{rmm}/pair?doc={urllib.parse.quote(doc, safe='')}"
            f"&challenge={challenge}&state={urllib.parse.quote(state, safe='')}")


def get(state: str) -> dict | None:
    with _lock:
        pending = _pending.get(state or "")
        return dict(pending) if pending and pending["expires"] >= time.time() else None


def receive_code(state: str, code: str) -> None:
    with _lock:
        if state in _pending:
            _pending[state]["code"] = code


def _exchange(url: str, code: str, verifier: str, insecure: bool) -> dict:
    try:
        with httpx.Client(timeout=15.0, verify=not insecure) as client:
            r = client.post(f"{url}/api/v1/pair/exchange", json={"code": code, "verifier": verifier})
    except httpx.ConnectError as exc:
        text = str(exc).lower()
        if "certificate" in text or "ssl" in text:
            raise Unreachable(f"{url} heeft een certificaat dat deze server niet vertrouwt")
        raise Unreachable(f"deze server krijgt geen verbinding met {url}")
    except httpx.TimeoutException:
        raise Unreachable(f"{url} antwoordt niet op tijd")
    except httpx.HTTPError as exc:
        raise Unreachable(f"{url}: {exc}")
    if r.status_code == 404:
        raise ValueError("Deze RMM kent koppelen met één knop nog niet — werk hem bij, of koppel handmatig")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = None
        raise ValueError(detail or f"De RMM weigerde de koppeling ({r.status_code})")
    return r.json()


def finish(state: str, server_url: str | None = None, insecure: bool | None = None) -> tuple[dict, dict]:
    """Exchange the code for an API key. Returns the pairing and the RMM's answer."""
    pending = get(state)
    if not pending or not pending.get("code"):
        raise ValueError("Deze koppeling is verlopen. Begin opnieuw.")
    url = clean_url(server_url) if server_url else pending["server_url"]
    if not url:
        raise ValueError("Dat is geen adres dat met http:// of https:// begint")
    insecure = pending["insecure"] if insecure is None else bool(insecure)
    with _lock:
        if state in _pending:
            _pending[state].update(server_url=url, insecure=insecure)
    answer = _exchange(url, pending["code"], pending["verifier"], insecure)
    with _lock:
        _pending.pop(state, None)
    pending.update(server_url=url, insecure=insecure)
    return pending, answer
