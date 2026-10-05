"""Patch cabinets: what hangs in one, and at which height.

A cabinet is an item of the kind ``rack`` (see schema.RACK): where it stands
and how many units it has. What is in it is a list of slots, each at a height
counted the way the rails are -- U1 at the bottom -- and as many units tall as
the thing is. A slot is either something documented at that customer (a
switch, a firewall, a server; its page is a click away, and a switch shows
which of its ports are taken) or a passive part that is never worth a page of
its own: a patch panel, a blanking plate, a cable manager, a shelf, a power
strip, a UPS.

Nothing overlaps, nothing sticks out of the cabinet, and nothing hangs in it
twice; the server checks that, whatever the page sent.
"""
from __future__ import annotations

import uuid

from . import database

DEFAULT_UNITS = 42
MAX_UNITS = 60

# The parts that are not documented items: what they are called, and how tall
# a common one is.
PASSIVE = {
    "patch": {"label": "Patchpaneel", "height": 1},
    "blank": {"label": "Blindplaat", "height": 1},
    "cable": {"label": "Kabelgoot", "height": 1},
    "shelf": {"label": "Plank", "height": 2},
    "pdu": {"label": "Stekkerdoos", "height": 1},
    "ups": {"label": "UPS", "height": 2},
    "other": {"label": "Overig", "height": 1},
}


def units_of(rack: dict) -> int:
    try:
        units = int((rack.get("fields") or {}).get("units") or DEFAULT_UNITS)
    except (TypeError, ValueError):
        units = DEFAULT_UNITS
    return max(1, min(MAX_UNITS, units))


def clean(rack: dict, raw_slots: list, items: dict) -> list:
    """The slots as they may be stored, or ValueError saying what is wrong.
    ``items`` holds the customer's items by id."""
    units = units_of(rack)
    taken: dict[int, str] = {}
    placed: set = set()
    out = []
    for raw in raw_slots or []:
        kind = raw.get("kind")
        if kind == "item":
            item_id = str(raw.get("item") or "")
            target = items.get(item_id)
            if not target or item_id == rack["id"] or target["kind"] == "rack":
                raise ValueError("Dat apparaat bestaat niet bij deze klant")
            if item_id in placed:
                raise ValueError(f"{target['name']} hangt al in deze kast")
            placed.add(item_id)
            name = target["name"]
        elif kind in PASSIVE:
            name = str(raw.get("label") or "").strip()[:60] or PASSIVE[kind]["label"]
        else:
            raise ValueError("Onbekend onderdeel")
        try:
            at = int(raw.get("at"))
            height = int(raw.get("height") or 1)
        except (TypeError, ValueError):
            raise ValueError(f"{name}: hoogte en plaats moeten getallen zijn")
        if height < 1 or at < 1 or at + height - 1 > units:
            raise ValueError(f"{name} past daar niet: de kast is {units}U")
        for u in range(at, at + height):
            if u in taken:
                raise ValueError(f"U{u} is al bezet door {taken[u]}")
            taken[u] = name
        slot = {"id": str(raw.get("id") or uuid.uuid4().hex)[:16], "kind": kind,
                "at": at, "height": height}
        if kind == "item":
            slot["item"] = raw["item"]
        else:
            label = str(raw.get("label") or "").strip()[:60]
            if label:
                slot["label"] = label
            if kind == "patch":
                try:
                    ports = int(raw.get("ports") or 24)
                except (TypeError, ValueError):
                    ports = 24
                slot["ports"] = max(1, min(96, ports))
        out.append(slot)
    out.sort(key=lambda s: -s["at"])
    return out


def view(rack: dict, items: dict, hidden: set) -> dict:
    """The cabinet as its page draws it: the slots, and what each documented
    thing in it is -- for a switch, which of its ports are taken, by what."""
    slots = database.rack_slots(rack["id"])
    devices = {}
    for slot in slots:
        if slot.get("kind") != "item":
            continue
        item = items.get(slot.get("item"))
        if not item:
            continue                                  # deleted since: drawn as gone
        if item["id"] in hidden:
            devices[item["id"]] = {"hidden": True}
            continue
        fields = item.get("fields") or {}
        device = {"id": item["id"], "name": item["name"], "kind": item["kind"],
                  "role": fields.get("role") or "", "status": fields.get("status") or "",
                  "archived": bool(item.get("archived"))}
        if item["kind"] == "network":
            try:
                count = int(fields.get("ports") or 0)
            except (TypeError, ValueError):
                count = 0
            if count:
                device["ports"] = [{
                    "number": p["number"], "label": p["label"], "vlan": p["vlan"],
                    "used": bool(p["adapter"]),
                    "who": ("" if not p["adapter"] else "afgeschermd" if p["adapter"]["item_id"] in hidden
                            else f"{p['adapter']['item_name']} ({p['adapter']['name'] or 'adapter'})"),
                } for p in database.ports_of(item["id"], count)]
        devices[item["id"]] = device
    return {"units": units_of(rack), "slots": slots, "devices": devices, "passive": PASSIVE}


def describe(slots: list, items: dict) -> list:
    """What hangs where, top down, in words -- for the export."""
    out = []
    for slot in sorted(slots, key=lambda s: -s.get("at", 0)):
        top = slot["at"] + slot["height"] - 1
        where = f"U{slot['at']}" if slot["height"] == 1 else f"U{slot['at']}–U{top}"
        if slot["kind"] == "item":
            what = (items.get(slot.get("item")) or {}).get("name") or "(niet meer te zien)"
        else:
            what = slot.get("label") or PASSIVE.get(slot["kind"], {}).get("label", slot["kind"])
            if slot["kind"] == "patch":
                what += f" ({slot.get('ports', 24)} poorten)"
        out.append({"where": where, "what": what})
    return out
