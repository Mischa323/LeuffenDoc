"""What the RMM shows about a machine, sent from here.

The RMM's device drawer has a **Docs** tab. What is on it comes from here: what
was written down about the machine, the switch port it hangs on, and the
passwords, documents and people linked to it -- by name, with a way through to
the page. It is *sent*, not fetched: LeuffenDoc already talks to the RMM with
its API key, so the RMM needs no key of its own for this server and no way
into it, which behind two reverse proxies is the part that tends to break.

Only what anyone at the customer may read here goes across. Never a password,
and nothing shut off to named colleagues: the RMM shows the tab to whoever may
open the device, and knows nothing about who was named here.

Each round works out every machine's summary and sends only the ones that
changed since the last time, so a round in which nothing happened costs one
look at the database and no traffic.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import threading
import time

import httpx

from . import database, rmm, schema, settings

log = logging.getLogger("leuffendoc.docpush")

# What the last round did, for the status on the Klanten page.
last_push: dict = {"at": None, "ok": None, "detail": "nog niet uitgevoerd",
                   "devices": 0, "sent": 0}

# A change made here asks for a round soon, rather than at the next sync. The
# short wait gathers the several requests one save can consist of.
SETTLE_SECONDS = 3
_asked_at: float | None = None
_asked = threading.Lock()
_running = threading.Lock()
CHUNK = 100


def soon() -> None:
    global _asked_at
    with _asked:
        _asked_at = time.monotonic()


def due() -> bool:
    with _asked:
        return _asked_at is not None and time.monotonic() - _asked_at >= SETTLE_SECONDS


def _taken() -> None:
    global _asked_at
    with _asked:
        _asked_at = None


# --------------------------------------------------------------------------- #
# One machine, as the RMM will show it
# --------------------------------------------------------------------------- #
def _path(org_id: str, item_id: str) -> str:
    return f"/#/klant/{org_id}/item/{item_id}"


def _where(org_id: str, item_id: str) -> dict:
    """A link to a page here: absolute when the public address is known, and a
    path the RMM can put its own idea of our address in front of otherwise."""
    path = _path(org_id, item_id)
    base = (settings.get("DOC_PUBLIC_URL") or "").rstrip("/")
    return {"path": path, "url": f"{base}{path}" if base.startswith("http") else None}


def _date(value) -> str | None:
    try:
        on = datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        return str(value)
    return f"{on.day}-{on.month}-{on.year}"


def _flag(value, today: datetime.date, warn: int) -> dict | None:
    try:
        days = (datetime.date.fromisoformat(str(value)[:10]) - today).days
    except ValueError:
        return None
    if days < 0:
        return {"tone": "bad", "text": "verlopen"}
    if days <= warn:
        return {"tone": "warn", "text": "vandaag" if days == 0 else f"over {days} dag{'en' if days != 1 else ''}"}
    return None


def _text(field: dict, value, by_id: dict, shown: set) -> tuple[str | None, dict]:
    """A value as it reads, and -- for a reference -- where it points."""
    kind = field["type"]
    if kind == "ref":
        target = by_id.get(value)
        if not target or target["id"] not in shown:
            return None, {}
        return target["name"], _where(target["org_id"], target["id"])
    if kind == "date":
        return _date(value), {}
    if kind == "bool":
        return ("Ja" if value else "Nee"), {}
    if kind == "list":
        lines = [f"{e.get('label')}: {e.get('value')}" if e.get("label") else str(e.get("value"))
                 for e in value if isinstance(e, dict) and e.get("value")]
        return ("\n".join(lines) or None), {}
    return str(value), {}


def summary(item: dict, by_id: dict, pointing: dict, shown: set,
            today: datetime.date, warn: int) -> dict:
    spec = schema.kind(item["kind"]) or {}
    fields = []
    for key, field in schema.fields_of(item["kind"]).items():
        # The RMM already shows what it reported itself; secrets never travel.
        if field.get("rmm") or field["type"] == "secret":
            continue
        value = item["fields"].get(key)
        if value is None or value == "" or value == []:
            continue
        text, where = _text(field, value, by_id, shown)
        if not text:
            continue
        fields.append({"label": field["label"], "value": text,
                       "multiline": field["type"] in ("textarea", "long", "list"), **where,
                       "flag": _flag(value, today, warn) if field.get("expiry") else None})

    ports = []
    for adapter in database.list_adapters(item["id"]):
        port = adapter.get("port")
        if not port or port["switch_id"] not in shown:
            continue
        ports.append({"adapter": adapter.get("name"), "mac": adapter.get("mac"),
                      "switch": port["switch_name"], "port": str(port["number"]),
                      "vlan": port.get("vlan"), "label": port.get("label"),
                      **_where(item["org_id"], port["switch_id"])})

    # Linked both ways: what was linked to it, and what points at it.
    related, seen = [], set()
    others = [r for r in database.relations_of(item["id"])]
    others += [by_id[o] for o in pointing.get(item["id"], []) if o in by_id]
    for other in others:
        if other["id"] in seen or other["id"] not in shown or other.get("archived"):
            continue
        seen.add(other["id"])
        other_spec = schema.kind(other["kind"]) or {}
        related.append({"kind": other["kind"], "kind_label": other_spec.get("plural")
                        or other_spec.get("label") or other["kind"],
                        "name": other["name"], **_where(item["org_id"], other["id"])})
    order = {"password": 0, "document": 1}
    related.sort(key=lambda r: (order.get(r["kind"], 2), r["kind_label"], r["name"].lower()))

    return {"name": item["name"], "kind_label": spec.get("label", item["kind"]),
            "archived": bool(item.get("archived")), **_where(item["org_id"], item["id"]),
            "updated_at": item.get("updated_at"), "updated_by": item.get("updated_by"),
            "fields": fields, "ports": ports, "related": related}


def _fingerprint(doc: dict) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()


def wanted() -> dict:
    """Every machine's summary, keyed by its id in the RMM."""
    restricted = database.restricted_items()
    warn = int(settings.get("EXPIRY_WARN_DAYS"))
    today = datetime.date.today()
    by_org: dict[str, list] = {}
    for item in database.rmm_items():
        if not item.get("rmm_gone"):
            by_org.setdefault(item["org_id"], []).append(item)
    refs = schema.ref_fields()
    out = {}
    for org_id, machines in by_org.items():
        everything = database.list_items(org_id, include_archived=True)
        by_id = {i["id"]: i for i in everything}
        shown = {i["id"] for i in everything if i["id"] not in restricted}
        pointing: dict[str, list] = {}
        for other in everything:
            for field in refs.get(other["kind"], []):
                target = other["fields"].get(field["key"])
                if target:
                    pointing.setdefault(target, []).append(other["id"])
        for item in machines:
            if item["id"] in shown:
                out[item["rmm_device_id"]] = summary(item, by_id, pointing, shown, today, warn)
    return out


# --------------------------------------------------------------------------- #
# Sending
# --------------------------------------------------------------------------- #
def _send(to_set: dict, to_clear: list) -> dict:
    with rmm._client() as client:
        r = client.post(f"{rmm.base_url()}/api/v1/documentation",
                        json={"set": to_set, "clear": to_clear})
    r.raise_for_status()
    return r.json()


def push() -> dict:
    """One round: send what changed, forget what went. Never raises."""
    _taken()
    if not rmm.configured():
        last_push.update(at=time.time(), ok=None, detail="de RMM is niet ingesteld")
        return last_push
    if not _running.acquire(blocking=False):     # a round is already under way
        soon()
        return last_push
    try:
        docs = wanted()
        before = database.doc_push_state()
        hashes = {device: _fingerprint(doc) for device, doc in docs.items()}
        to_set = [d for d in docs if before.get(d) != hashes[d]]
        to_clear = [d for d in before if d not in docs]
        sent = 0
        for i in range(0, max(len(to_set), len(to_clear)), CHUNK):
            chunk = to_set[i:i + CHUNK]
            gone = to_clear[i:i + CHUNK]
            _send({d: docs[d] for d in chunk}, gone)
            # A device the RMM no longer has is remembered all the same, so it
            # is not sent again every round; it goes when it changes.
            database.doc_push_done({d: hashes[d] for d in chunk}, gone)
            sent += len(chunk) + len(gone)
        last_push.update(at=time.time(), ok=True, devices=len(docs), sent=sent,
                         detail="gelukt" if sent else "niets gewijzigd")
    except httpx.HTTPStatusError as exc:
        detail = ("de RMM is te oud om documentatie te tonen — werk hem bij"
                  if exc.response.status_code in (404, 405) else rmm._explain(exc))
        log.warning("sending documentation to the RMM failed: %r", exc)
        last_push.update(at=time.time(), ok=False, detail=detail)
    except Exception as exc:
        log.warning("sending documentation to the RMM failed: %r", exc)
        last_push.update(at=time.time(), ok=False, detail=rmm._explain(exc))
    finally:
        _running.release()
    return last_push
