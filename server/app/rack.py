"""Patch cabinets: what hangs in one, what stands in it, and where.

A cabinet is an item of the kind ``rack`` (see schema.RACK): where it stands
and how many units it has. What is in it is a list of slots, each at a height
counted the way the rails are -- U1 at the bottom -- and as many units tall as
the thing is. A slot is either something documented at that customer (a
switch, a firewall, a server; its page is a click away, and a switch shows
which of its ports are taken) or a passive part that is never worth a page of
its own: a patch panel, a blanking plate, a cable manager, a power strip, a
rack-mounted UPS.

Not everything in a cabinet is 19 inch. A modem from the provider, a desktop
NAS, a UPS that lies on its side: they stand on a shelf, or on the bottom of
the cabinet. A shelf and the bottom are slots too -- the bottom always at U1 --
and hold what stands on them, documented or not. Whether something documented
is 19 inch (and how many units) is said on its own page; until somebody says,
it is guessed from what it is.

Nothing overlaps, nothing sticks out of the cabinet, and nothing is in it
twice; the server checks that, whatever the page sent.
"""
from __future__ import annotations

import uuid

from . import database, schema

DEFAULT_UNITS = 42
MAX_UNITS = 60
MAX_STANDING = 8

# What a configuration's Formaat field can say (see schema).
RACKMOUNT, LOOSE = schema.RACK_FORMS

# The parts that are not documented items: what they are called, and how tall
# a common one is. A shelf and the bottom hold what stands on them.
PASSIVE = {
    "patch": {"label": "Patchpaneel", "height": 1},
    "blank": {"label": "Blindplaat", "height": 1},
    "cable": {"label": "Kabelgoot", "height": 1},
    "shelf": {"label": "Plank", "height": 2, "holds": True},
    "floor": {"label": "Bodem", "height": 4, "holds": True, "bottom": True},
    "pdu": {"label": "Stekkerdoos", "height": 1},
    "ups": {"label": "UPS (19 inch)", "height": 2},
    "other": {"label": "Overig", "height": 1},
}

# What stands on a shelf or the bottom without a page of its own.
STANDING = {
    "ups_box": {"label": "Losse UPS"},
    "box": {"label": "Los apparaat"},
}

# What can be put in a cabinet: equipment, and types of your own -- not the
# customer's locations, people or passwords, and not a virtual machine.
EQUIPMENT = {"computer", "network", "printer"}


def units_of(rack: dict) -> int:
    try:
        units = int((rack.get("fields") or {}).get("units") or DEFAULT_UNITS)
    except (TypeError, ValueError):
        units = DEFAULT_UNITS
    return max(1, min(MAX_UNITS, units))


def form_of(item: dict) -> dict:
    """Whether something hangs in the rails (and how many units) or stands --
    as said on its page, or else as such a thing usually is."""
    fields = item.get("fields") or {}
    role = fields.get("role") or ""
    try:
        units = max(1, min(20, int(fields.get("rack_units") or 0))) if fields.get("rack_units") else 0
    except (TypeError, ValueError):
        units = 0
    usual = 2 if item["kind"] == "computer" and role == "Server" else 1
    if fields.get("rackmount") == RACKMOUNT:
        return {"rack": True, "units": units or usual, "guessed": False}
    if fields.get("rackmount") == LOOSE:
        return {"rack": False, "units": None, "guessed": False}
    if item["kind"] == "network":
        rack = role in ("Switch", "Router", "Firewall")
    elif item["kind"] == "computer":
        rack = role == "Server"
    else:
        rack = False
    return {"rack": rack, "units": (units or usual) if rack else None, "guessed": True}


def placeable(item: dict) -> bool:
    if item["kind"] == "rack" or item.get("archived"):
        return False
    if item["kind"] == "computer" and (item.get("fields") or {}).get("role") == "Virtuele machine":
        return False
    return item["kind"] in EQUIPMENT or item["kind"] in schema.custom()


def clean(rack: dict, raw_slots: list, items: dict) -> list:
    """The slots as they may be stored, or ValueError saying what is wrong.
    ``items`` holds the customer's items by id."""
    units = units_of(rack)
    taken: dict[int, str] = {}
    placed: set = set()
    out = []

    def device(item_id: str) -> dict:
        target = items.get(item_id)
        if not target or item_id == rack["id"] or target["kind"] == "rack":
            raise ValueError("Dat apparaat bestaat niet bij deze klant")
        if item_id in placed:
            raise ValueError(f"{target['name']} staat al in deze kast")
        placed.add(item_id)
        return target

    for raw in raw_slots or []:
        kind = raw.get("kind")
        if kind == "item":
            name = device(str(raw.get("item") or ""))["name"]
        elif kind in PASSIVE:
            name = str(raw.get("label") or "").strip()[:60] or PASSIVE[kind]["label"]
        else:
            raise ValueError("Onbekend onderdeel")
        try:
            at = int(raw.get("at"))
            height = int(raw.get("height") or 1)
        except (TypeError, ValueError):
            raise ValueError(f"{name}: hoogte en plaats moeten getallen zijn")
        if PASSIVE.get(kind, {}).get("bottom") and at != 1:
            raise ValueError("De bodem is altijd onderin de kast")
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
        if PASSIVE.get(kind, {}).get("holds"):
            standing = []
            things = raw.get("items") or []
            if len(things) > MAX_STANDING:
                raise ValueError(f"Op {name.lower()} passen hier hoogstens {MAX_STANDING} dingen")
            for thing in things:
                entry = {"id": str(thing.get("id") or uuid.uuid4().hex)[:16]}
                if thing.get("item"):
                    entry["item"] = device(str(thing["item"]))["id"]
                elif thing.get("kind") in STANDING:
                    entry["kind"] = thing["kind"]
                    label = str(thing.get("label") or "").strip()[:60]
                    if label:
                        entry["label"] = label
                else:
                    raise ValueError(f"Onbekend onderdeel op {name.lower()}")
                standing.append(entry)
            slot["items"] = standing
        out.append(slot)
    out.sort(key=lambda s: -s["at"])
    return out


def _device(item: dict, hidden: set) -> dict:
    fields = item.get("fields") or {}
    device = {"id": item["id"], "name": item["name"], "kind": item["kind"],
              "role": fields.get("role") or "", "status": fields.get("status") or "",
              "archived": bool(item.get("archived")), **form_of(item)}
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
    return device


def ids_in(slots: list) -> list:
    """Every documented thing in a cabinet: in the rails, and standing."""
    out = []
    for slot in slots:
        if slot.get("kind") == "item" and slot.get("item"):
            out.append(slot["item"])
        out += [t["item"] for t in slot.get("items") or [] if t.get("item")]
    return out


def view(rack: dict, items: dict, hidden: set) -> dict:
    """The cabinet as its page draws it: the slots; what each documented thing
    in it is (for a switch, which of its ports are taken, by what); and what
    else of this customer's could go in, each saying whether it is 19 inch."""
    slots = database.rack_slots(rack["id"])
    devices = {}
    inside = set(ids_in(slots))
    for item_id in inside:
        item = items.get(item_id)
        if not item:
            continue                                  # deleted since: drawn as gone
        devices[item_id] = {"hidden": True} if item_id in hidden else _device(item, hidden)
    candidates = sorted(({"id": i["id"], "name": i["name"], "kind": i["kind"],
                          "role": (i.get("fields") or {}).get("role") or "", **form_of(i)}
                         for i in items.values()
                         if i["id"] not in hidden and i["id"] not in inside and placeable(i)),
                        key=lambda c: c["name"].lower())
    return {"units": units_of(rack), "slots": slots, "devices": devices, "candidates": candidates,
            "passive": PASSIVE, "standing": STANDING, "forms": [RACKMOUNT, LOOSE]}


def changes(before: list, after: list, items: dict) -> list:
    """What changed in a cabinet, in words: put in, taken out, moved -- for its
    history, which should say more than how many parts it now has."""
    def name(entry: dict) -> str:
        if entry.get("item"):
            return (items.get(entry["item"]) or {}).get("name") or "apparaat"
        kind = entry.get("kind")
        return entry.get("label") or PASSIVE.get(kind, {}).get("label") or STANDING.get(kind, {}).get("label") or "onderdeel"

    def where(slot: dict) -> str:
        top = slot["at"] + slot["height"] - 1
        return f"U{slot['at']}" if slot["height"] == 1 else f"U{slot['at']}–U{top}"

    # A documented thing is itself wherever it goes -- from the rails to a
    # shelf is a move; a passive part is known by its slot.
    key = lambda entry: entry.get("item") or entry["id"]  # noqa: E731

    def flat(slots: list) -> dict:
        out = {}
        for slot in slots:
            out[key(slot)] = (name(slot), where(slot))
            holder = name(slot).lower()
            for thing in slot.get("items") or []:
                out[key(thing)] = (name(thing), f"op {holder}")
        return out

    old, new = flat(before), flat(after)
    said = []
    for k, (what, at) in new.items():
        if k not in old:
            said.append(f"{what} {at} gezet" if at.startswith("op ") else f"{what} op {at} geplaatst")
        elif old[k][1] != at:
            said.append(f"{what} {old[k][1]} → {at}")
    for k, (what, _) in old.items():
        if k not in new:
            said.append(f"{what} eruit")
    return said


def describe(slots: list, items: dict) -> list:
    """What hangs and stands where, top down, in words -- for the export."""
    name = lambda item_id: (items.get(item_id) or {}).get("name") or "(niet meer te zien)"  # noqa: E731
    out = []
    for slot in sorted(slots, key=lambda s: -s.get("at", 0)):
        top = slot["at"] + slot["height"] - 1
        where = f"U{slot['at']}" if slot["height"] == 1 else f"U{slot['at']}–U{top}"
        if slot["kind"] == "item":
            what = name(slot.get("item"))
        else:
            what = slot.get("label") or PASSIVE.get(slot["kind"], {}).get("label", slot["kind"])
            if slot["kind"] == "patch":
                what += f" ({slot.get('ports', 24)} poorten)"
            standing = [name(t["item"]) if t.get("item")
                        else t.get("label") or STANDING.get(t.get("kind"), {}).get("label", "?")
                        for t in slot.get("items") or []]
            if standing:
                what += ", met " + ", ".join(standing)
        out.append({"where": where, "what": what})
    return out
