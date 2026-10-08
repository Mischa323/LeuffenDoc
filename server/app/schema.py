"""What can be documented, and which fields each thing has.

One catalogue, read by both sides: the server validates against it and the
interface builds its forms from it, so a field added here appears in the
interface without a line of JavaScript changing.

Two families live in here, and the difference is deliberate:

  * **configurations** -- the equipment you can point at: computers and
    servers, network equipment, printers; and
  * the customer's **own parts** -- an internet connection, a location, a
    contact. Those are not equipment and do not pretend to be.

A field marked ``rmm`` is one the RMM already knows for a linked device. It is
then shown from the RMM and not typed here, because a documented memory size
that nobody updates is worse than none at all. Everything the RMM cannot know
-- when it was installed and by whom, which switch port, the warranty -- stays
in your hands, on the same page.

Phase 3 makes this catalogue extensible: types you define yourself, stored in
the database, joining the ones below.
"""
from __future__ import annotations

import re

from . import database

# Field types the interface knows how to render:
#   text, textarea, number, date, select, mac, ip, bool, ref, list
# A `ref` field holds the id of another item, of the kind named in `ref`.
# A `list` field holds several labelled values -- [{"label": "Mobiel",
# "value": "06-..."}] -- because one phone number per person is a fiction.
# A `secret` field is encrypted and never travels with the item (see vault.py);
# only a type you define yourself can have one, and it may have several.

# Not "gearchiveerd": equipment that is out of use is archived, and one fact
# belongs in one place.
STATUS = ["In gebruik", "Reserve", "In reparatie"]

# Whether equipment hangs in the rails of a patch cabinet, or stands -- on a
# shelf or the bottom of it (see rack.py).
RACK_FORMS = ["19 inch (U)", "Los / staand"]


def _f(key, label, type="text", **extra):
    return {"key": key, "label": label, "type": type, **extra}


def _rack_fields() -> list:
    return [
        _f("rackmount", "Formaat", "select", options=RACK_FORMS, icon="rack",
           hint="Hangt het in de rails van een patchkast, of staat het op een plank of de bodem? "
                "Leeg: zoals zoiets meestal is."),
        _f("rack_units", "Hoogte in een rack (U)", "number",
           hint="Alleen bij 19 inch: hoeveel units het hoog is."),
    ]


# --------------------------------------------------------------------------- #
# Configurations -- equipment
# --------------------------------------------------------------------------- #
COMPUTER = {
    "label": "Computer of server",
    "plural": "Computers & servers",
    "icon": "desktop",
    "family": "configuratie",
    "sub": "Werkplekken, laptops, servers en NAS-en",
    "backref": "Wat hiernaar verwijst",
    # What a list shows at a glance.
    "columns": ["role", "status", "os", "installed_at", "eol"],
    "groups": [
        {"key": "wat", "label": "Wat het is", "fields": [
            _f("role", "Soort", "select", options=["Desktop", "Laptop", "Server",
                                                   "Virtuele machine", "NAS", "Tablet"]),
            _f("status", "Status", "select", options=STATUS),
            _f("purpose", "Waar het voor dient", "textarea",
               hint="Waarom staat deze machine er — welke rol, welke toepassing."),
            _f("location", "Locatie", "ref", ref="location", icon="building"),
            _f("host", "Draait op", "ref", ref="configuratie", icon="server",
               hint="Voor een virtuele machine: de server waarop hij draait."),
            _f("user", "In gebruik bij", "ref", ref="contact", icon="user"),
        ]},
        {"key": "hardware", "label": "Hardware", "fields": [
            _f("cpu", "Processor", rmm="cpu", icon="cpu"),
            _f("memory", "Geheugen", rmm="memory", icon="mem"),
            _f("storage", "Schijven", rmm="storage", icon="disk"),
            _f("os", "Besturingssysteem", rmm="os", icon="package"),
            _f("manufacturer", "Merk", rmm="manufacturer", icon="box"),
            _f("model", "Model", rmm="model", icon="box"),
            _f("serial", "Serienummer", rmm="serial", icon="clipboard"),
            _f("vm_state", "In Hyper-V", rmm="vm_state", icon="layers"),
            *_rack_fields(),
        ]},
        {"key": "beheer", "label": "Beheer", "fields": [
            _f("installed_at", "Geïnstalleerd op", "date"),
            _f("installed_by", "Geïnstalleerd door",
               hint="Wie de machine heeft opgeleverd. De RMM weet dit niet."),
            _f("purchased_at", "Aangeschaft op", "date"),
            _f("warranty_until", "Garantie tot", "date", expiry=True),
            _f("eol", "Verloopt op", "date", expiry=True,
               hint="Wanneer dit apparaat vervangen of afgeschreven moet zijn. Verlopen apparatuur staat bovenaan het klantoverzicht."),
            _f("notes", "Notities", "textarea"),
        ]},
    ],
}

NETWORK = {
    "label": "Netwerkapparaat",
    "plural": "Netwerkapparatuur",
    "icon": "network",
    "family": "configuratie",
    "sub": "Switches, firewalls, routers en access points",
    "backref": "Wat hierop aangesloten is",
    # What a list shows at a glance.
    "columns": ["role", "status", "mgmt_ip", "eol"],
    "groups": [
        {"key": "wat", "label": "Wat het is", "fields": [
            _f("role", "Soort", "select",
               options=["Router", "Switch", "Firewall", "Wifi-punt", "Modem"]),
            _f("status", "Status", "select", options=STATUS),
            _f("ports", "Aantal poorten", "number", icon="network",
               hint="Alleen bij een switch. Hiermee wordt de poortenlijst opgebouwd."),
            _f("location", "Locatie", "ref", ref="location"),
        ]},
        {"key": "hardware", "label": "Apparaat", "fields": [
            _f("manufacturer", "Merk", rmm="manufacturer"),
            _f("model", "Model", rmm="model"),
            _f("serial", "Serienummer", rmm="serial"),
            _f("firmware", "Firmware", icon="package"),
            _f("mgmt_ip", "Beheeradres", "ip", icon="globe"),
            *_rack_fields(),
        ]},
        {"key": "beheer", "label": "Beheer", "fields": [
            _f("installed_at", "Geïnstalleerd op", "date"),
            _f("installed_by", "Geïnstalleerd door"),
            _f("warranty_until", "Garantie tot", "date", expiry=True),
            _f("eol", "Verloopt op", "date", expiry=True,
               hint="Wanneer dit apparaat vervangen of afgeschreven moet zijn. Verlopen apparatuur staat bovenaan het klantoverzicht."),
            _f("notes", "Notities", "textarea"),
        ]},
    ],
}

PRINTER = {
    "label": "Printer",
    "plural": "Printers",
    "icon": "printer",
    "family": "configuratie",
    "sub": "Printers en multifunctionals",
    "backref": "Wat hiernaar verwijst",
    # What a list shows at a glance.
    "columns": ["role", "status", "placement", "eol"],
    "groups": [
        {"key": "wat", "label": "Wat het is", "fields": [
            _f("role", "Soort", "select",
               options=["Printer", "Multifunctional", "Labelprinter", "Plotter"]),
            _f("status", "Status", "select", options=STATUS),
            _f("location", "Locatie", "ref", ref="location"),
            _f("placement", "Waar hij staat", hint="De ruimte of verdieping."),
        ]},
        {"key": "hardware", "label": "Apparaat", "fields": [
            _f("manufacturer", "Merk", rmm="manufacturer"),
            _f("model", "Model", rmm="model"),
            _f("serial", "Serienummer", rmm="serial"),
            _f("mgmt_ip", "Beheeradres", "ip"),
            _f("supplies", "Verbruiksartikelen",
               hint="Welke toner of cartridge erin gaat."),
            *_rack_fields(),
        ]},
        {"key": "beheer", "label": "Beheer", "fields": [
            _f("installed_at", "Geïnstalleerd op", "date"),
            _f("installed_by", "Geïnstalleerd door"),
            _f("warranty_until", "Garantie tot", "date", expiry=True),
            _f("eol", "Verloopt op", "date", expiry=True,
               hint="Wanneer dit apparaat vervangen of afgeschreven moet zijn. Verlopen apparatuur staat bovenaan het klantoverzicht."),
            _f("notes", "Notities", "textarea"),
        ]},
    ],
}

# --------------------------------------------------------------------------- #
# The customer's own parts -- not equipment, so not configurations
# --------------------------------------------------------------------------- #
INTERNET = {
    "label": "Internetverbinding",
    "plural": "Internetverbindingen",
    "icon": "globe",
    "family": "onderdeel",
    "sub": "Lijnen, providers, vaste adressen en contracten",
    "backref": "Wat hiernaar verwijst",
    # What a list shows at a glance.
    "columns": ["provider", "line_type", "speed_down", "contract_until"],
    "groups": [
        {"key": "lijn", "label": "De lijn", "fields": [
            _f("provider", "Provider", icon="cloud"),
            _f("line_type", "Soort lijn", "select",
               options=["Glasvezel", "Coax", "DSL", "4G/5G", "Straalverbinding"]),
            _f("speed_down", "Snelheid neer", hint="Bijvoorbeeld 1 Gbit/s.", icon="arrowDown"),
            _f("speed_up", "Snelheid op", icon="arrowUp"),
            _f("ip_range", "Vast IP-blok", icon="globe",
               hint="Het toegewezen adres of blok, bijvoorbeeld 203.0.113.8/29."),
            _f("location", "Locatie", "ref", ref="location"),
            _f("router", "Aangesloten op", "ref", ref="network",
               hint="De firewall of router waar de lijn op binnenkomt."),
        ]},
        {"key": "contract", "label": "Contract", "fields": [
            _f("account_number", "Klant- of circuitnummer"),
            _f("contract_until", "Contract tot", "date", expiry=True),
            _f("notice_period", "Opzegtermijn"),
            _f("monthly", "Bedrag per maand", icon="euro"),
        ]},
        {"key": "storing", "label": "Bij een storing", "fields": [
            _f("support_phone", "Storingsnummer", icon="phone"),
            _f("support_hours", "Bereikbaar"),
            _f("notes", "Notities", "textarea"),
        ]},
    ],
}

LOCATION = {
    "label": "Locatie",
    "plural": "Locaties",
    "icon": "building",
    "family": "onderdeel",
    "sub": "Vestigingen en panden van deze klant",
    "backref": "Wat hier staat",
    # What a list shows at a glance.
    "columns": ["city", "phone"],
    "groups": [
        {"key": "adres", "label": "Adres", "fields": [
            _f("address", "Straat en nummer"),
            _f("postcode", "Postcode"),
            _f("city", "Plaats"),
            _f("phone", "Telefoon"),
        ]},
        {"key": "over", "label": "Over deze locatie", "fields": [
            _f("access", "Toegang",
               hint="Hoe je binnenkomt: sleutel, badge, bij wie je je meldt."),
            _f("notes", "Notities", "textarea"),
        ]},
    ],
}

# A patch cabinet: where it stands and how tall it is. What hangs in it, and at
# which height, is drawn on its page (see rack.py) -- the switches and servers
# documented here, and the patch panels, shelves and power strips between them.
RACK = {
    "label": "Patchkast",
    "plural": "Patchkasten",
    "icon": "rack",
    "family": "onderdeel",
    "sub": "Kasten en wat erin hangt, zoals het er echt uitziet",
    "backref": "Wat hiernaar verwijst",
    "columns": ["location", "placement", "units"],
    "groups": [
        {"key": "wat", "label": "Waar en hoe groot", "fields": [
            _f("location", "Locatie", "ref", ref="location", icon="building"),
            _f("placement", "Waar hij staat",
               hint="De ruimte: de serverruimte in de kelder, de meterkast, de werkplaats."),
            _f("units", "Hoogte (U)", "number", icon="rack",
               hint="Hoeveel units erin passen: 42, 24, 12, 9 … Leeg is 42."),
            _f("depth", "Diepte", hint="Bijvoorbeeld 600 of 800 mm — past die server erin?"),
        ]},
        {"key": "over", "label": "Over", "fields": [
            _f("access", "Sleutel en toegang", hint="Waar de sleutel ligt, wie hem heeft."),
            _f("notes", "Notities", "textarea"),
        ]},
    ],
}

CONTACT = {
    "label": "Contactpersoon",
    "plural": "Contactpersonen",
    "icon": "user",
    "family": "onderdeel",
    "sub": "Wie je bij deze klant belt",
    "backref": "Waar deze persoon bij hoort",
    # What a list shows at a glance.
    "columns": ["job", "emails", "phones"],
    "groups": [
        {"key": "wie", "label": "Wie", "fields": [
            _f("job", "Functie"),
            _f("emails", "E-mailadressen", "list", icon="mail",
               labels=["Werk", "Privé", "Algemeen", "Facturatie"],
               hint="Meerdere mag: zet erbij welk adres waarvoor is."),
            _f("phones", "Telefoonnummers", "list", icon="phone",
               labels=["Werk", "Mobiel", "Privé", "Centrale", "Storing"]),
            _f("primary", "Hoofdcontactpersoon", "bool"),
        ]},
        {"key": "over", "label": "Over", "fields": [
            _f("location", "Locatie", "ref", ref="location"),
            _f("notes", "Notities", "textarea"),
        ]},
    ],
}

# --------------------------------------------------------------------------- #
# The vault
#
# A password is an item like the rest, so it gets the same history, the same
# access and -- the point -- the same links: a password sits next to the
# firewall it belongs to instead of in a separate list nobody opens.
#
# Only the password itself is encrypted, and it is not a field. Fields travel
# through every list and land in the history as "from this to that", which is
# exactly what a secret must never do.
# --------------------------------------------------------------------------- #
PASSWORD = {
    "label": "Wachtwoord",
    "plural": "Wachtwoorden",
    "icon": "key",
    "family": "kluis",
    "sub": "Versleuteld bewaard, en gekoppeld aan waar het bij hoort",
    "backref": "Wat hiernaar verwijst",
    # What a list shows at a glance.
    "columns": ["category", "device", "username", "rotate_at"],
    "groups": [
        {"key": "wat", "label": "Waarvoor", "fields": [
            # Any configuration: a reference may name a kind, or a family of them.
            _f("device", "Hoort bij", "ref", ref="configuratie", icon="box",
               hint="Het apparaat waar dit wachtwoord bij hoort — een computer, netwerkapparaat of printer."),
            _f("category", "Soort", "select",
               options=["Beheerder", "Gebruiker", "Dienst", "Netwerk", "Overig"]),
            _f("username", "Gebruikersnaam", icon="user"),
            _f("url", "Adres", hint="Waar je ermee inlogt.", icon="globe"),
        ]},
        {"key": "beheer", "label": "Beheer", "fields": [
            _f("rotate_at", "Vervangen vóór", "date", expiry=True,
               hint="Wanneer dit wachtwoord gewijzigd moet zijn."),
            _f("notes", "Notities", "textarea",
               hint="Let op: deze notitie wordt niet versleuteld en staat in de "
                    "geschiedenis. Zet er geen tweede wachtwoord in."),
        ]},
    ],
}

# --------------------------------------------------------------------------- #
# Free-form documents
#
# For what does not fit in fields: a procedure, an explanation, how to restart
# something at three in the morning. It is an item like the rest, so it can be
# hung on the machine it is about and turns up in the same search.
# --------------------------------------------------------------------------- #
DOCUMENT = {
    "label": "Document",
    "plural": "Documenten",
    "icon": "file",
    "family": "document",
    "sub": "Procedures en uitleg die niet in velden past",
    "backref": "Wat hiernaar verwijst",
    # What a list shows at a glance.
    "columns": ["category", "review_by"],
    "groups": [
        {"key": "wat", "label": "Waarover", "fields": [
            _f("category", "Soort", "select",
               options=["Procedure", "Uitleg", "Noodprocedure", "Afspraken", "Overig"]),
            _f("summary", "Waar het over gaat",
               hint="Één zin, zodat de lijst leesbaar blijft."),
            _f("review_by", "Nakijken vóór", "date", expiry=True,
               hint="Documentatie die niemand meer nakijkt gaat stilletjes liegen."),
        ]},
        {"key": "tekst", "label": "Tekst", "fields": [
            _f("body", "Inhoud", "textarea", long=True),
        ]},
    ],
}

# Everything above is built in. Types people define themselves live in the
# database and join these at run time -- same shape, same rendering, so nothing
# downstream can tell the difference.
# --------------------------------------------------------------------------- #
# Configuration types
#
# Desktops and laptops, routers, switches and wifi points: what an MSP looks
# for. The kind stays computer, network or printer -- links, switch ports and
# the RMM hang on that -- and its "Soort" is the type, with a plural and an
# icon so it can have its own place in the sidebar and the lists.
# --------------------------------------------------------------------------- #
SUBTYPES = {
    "computer": [("Desktop", "Desktops", "desktop"), ("Laptop", "Laptops", "laptop"),
                 ("Server", "Servers", "server"), ("Virtuele machine", "Virtuele machines", "layers"),
                 ("NAS", "NAS'en", "disk"), ("Tablet", "Tablets", "tablet")],
    "network": [("Router", "Routers", "router"), ("Switch", "Switches", "network"),
                ("Firewall", "Firewalls", "shield"), ("Wifi-punt", "Wifi-punten", "wifi"),
                ("Modem", "Modems", "globe")],
    "printer": [("Printer", "Printers", "printer"), ("Multifunctional", "Multifunctionals", "printer"),
                ("Labelprinter", "Labelprinters", "printer"), ("Plotter", "Plotters", "printer")],
}
# (Older names -- Werkplek, Access point -- are renamed at start-up; see database._migrate.)

for _kind, _spec in (("computer", COMPUTER), ("network", NETWORK), ("printer", PRINTER)):
    _spec["subtypes"] = [{"id": re.sub(r"[^a-z0-9]+", "-", role.lower()).strip("-"), "role": role,
                          "label": role, "plural": plural, "icon": icon}
                         for role, plural, icon in SUBTYPES[_kind]]

BUILT_IN: dict[str, dict] = {
    "computer": COMPUTER,
    "network": NETWORK,
    "printer": PRINTER,
    "internet": INTERNET,
    "rack": RACK,
    "location": LOCATION,
    "contact": CONTACT,
    "password": PASSWORD,
    "document": DOCUMENT,
}

# Field types somebody may pick when defining a type of their own. Not `ref`
# without a target, and not the RMM-backed ones: those only mean something for
# a kind the RMM actually reports.
CUSTOM_FIELD_TYPES = ["text", "textarea", "number", "date", "select", "bool",
                      "ip", "mac", "list", "secret", "ref"]

_custom: dict | None = None
_built_in: dict | None = None

# --------------------------------------------------------------------------- #
# Layouts: the blocks of a type, and what sits in each
#
# Built in or made here, a type's page is laid out in blocks. Which blocks, in
# what order, how wide, and which fields go where is up to whoever runs this
# server -- stored as a layout and laid over the definition at run time, so the
# code below still says what a field *is* and the layout only where it goes.
#
# A built-in field can be moved, renamed, explained differently and hidden,
# but not removed or turned into something else: the RMM sync, the Hyper-V
# guests, the switch ports and the vault count on it. A hidden field keeps its
# value and simply is not shown. New fields can be added to any type; on a
# built-in one their keys start with "x_", so a field a later version adds to
# the code can never collide with one somebody made here.
# --------------------------------------------------------------------------- #
WIDTHS = ("full", "half")
# The type of a configuration: the sidebar and the configuration types hang on it.
ALWAYS_SHOWN = {"role"}
EXTRA_PREFIX = "x_"


def forget_custom() -> None:
    """Drop the cached definitions after one is written."""
    global _custom, _built_in
    _custom = None
    _built_in = None


def arrange(spec: dict, layout: dict | None) -> dict:
    """A type with a layout laid over it: its blocks, in order, each with its
    fields; overrides applied; fields added here included. Whatever the layout
    does not mention -- a field a later version of the code added -- lands at
    the end of the block it was defined in, so nothing ever disappears."""
    if not layout:
        return spec
    pool: dict[str, tuple[dict, str | None]] = {}
    overrides = layout.get("overrides") or {}
    for group in spec["groups"]:
        for field in group["fields"]:
            merged = dict(field)
            change = overrides.get(field["key"]) or {}
            if change.get("label"):
                merged["label"] = change["label"]
            if "hint" in change:
                if change["hint"]:
                    merged["hint"] = change["hint"]
                else:
                    merged.pop("hint", None)
            if change.get("options") and field["type"] == "select" and field["key"] not in ALWAYS_SHOWN:
                merged["options"] = list(change["options"])
            if change.get("hidden") and field["key"] not in ALWAYS_SHOWN:
                merged["hidden"] = True
            pool[field["key"]] = (merged, group["key"])
    for field in layout.get("extra") or []:
        if field.get("key") and field["key"] not in pool:
            pool[field["key"]] = ({**field, "extra": True}, None)

    groups, placed = [], set()
    for group in layout.get("groups") or []:
        fields = []
        for key in group.get("fields") or []:
            if key in pool and key not in placed:
                fields.append(pool[key][0])
                placed.add(key)
        groups.append({"key": group["key"], "label": group.get("label") or "Blok",
                       "width": group.get("width") if group.get("width") in WIDTHS else "full",
                       "fields": fields})
    for key, (field, born_in) in pool.items():
        if key in placed:
            continue
        target = next((g for g in groups if g["key"] == born_in), None)
        if target is None:
            if not groups:
                groups.append({"key": "gegevens", "label": "Gegevens", "width": "full", "fields": []})
            target = groups[-1]
        target["fields"].append(field)

    shown = {f["key"] for g in groups for f in g["fields"]
             if not f.get("hidden") and f["type"] != "secret"}
    columns = [c for c in (layout.get("columns") if layout.get("columns") is not None
                           else spec.get("columns") or []) if c in shown]
    return {**spec, "groups": groups, "columns": columns, "customized": True}


def _as_spec(row: dict) -> dict:
    """One stored definition in the shape the built-in ones have: one block,
    "Gegevens", until someone lays it out in more."""
    spec = {
        "label": row["label"], "plural": row["plural"],
        "icon": row.get("icon") or "layers",
        "family": "eigen",
        "sub": row.get("sub") or "",
        "backref": row.get("backref") or "Wat hiernaar verwijst",
        "columns": row.get("columns") or [],
        "custom": True,
        "adapters": bool(row.get("adapters")),
        "groups": [{"key": "gegevens", "label": "Gegevens", "width": "full",
                    "fields": row.get("fields") or []}],
    }
    layout = row.get("layout") or {}
    if layout.get("groups"):
        spec = arrange(spec, {"groups": layout["groups"], "columns": spec["columns"]})
        spec.pop("customized", None)
    return spec


def custom() -> dict:
    global _custom
    if _custom is None:
        try:
            _custom = {t["id"]: _as_spec(t) for t in database.list_item_types()}
        except Exception:                      # before the database exists
            return {}
    return _custom


def built_in() -> dict:
    """The built-in kinds, each with its saved layout (if any) laid over it."""
    global _built_in
    if _built_in is None:
        try:
            saved = database.kind_layouts()
        except Exception:                      # before the database exists
            return BUILT_IN
        _built_in = {name: arrange(spec, saved.get(name)) for name, spec in BUILT_IN.items()}
    return _built_in


def KINDS_all() -> dict:
    return {**built_in(), **custom()}


def slug(label: str) -> str:
    """A readable id from a label: "Microsoft 365-tenant" -> "microsoft-365-tenant"."""
    text = (label or "").strip().lower()
    text = text.replace("&", " en ")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:40] or "type"


def adapter_kinds() -> set:
    """Which kinds carry network adapters -- equipment, plus any type whose
    maker ticked the box."""
    return ADAPTER_KINDS | {name for name, spec in custom().items() if spec.get("adapters")}


def secret_fields_of(name: str) -> list:
    return [f["key"] for f in fields_of(name).values() if f["type"] == "secret"]

# Equipment carries network adapters; an internet connection or a contact does
# not, so the interface only offers them where they mean something.
ADAPTER_KINDS = {"computer", "network", "printer"}


def kind(name: str) -> dict | None:
    return KINDS_all().get(name)


def fields_of(name: str) -> dict[str, dict]:
    """Every field of a kind, keyed, with its group folded in -- hidden ones
    included: they still hold a value, which must survive a save."""
    out: dict[str, dict] = {}
    for group in KINDS_all().get(name, {}).get("groups", []):
        for field in group["fields"]:
            out[field["key"]] = {**field, "group": group["key"]}
    return out


def shown_fields_of(name: str) -> dict[str, dict]:
    """The fields a person sees: what pages, warnings, exports and the RMM's
    Docs tab go by."""
    return {k: f for k, f in fields_of(name).items() if not f.get("hidden")}


def catalogue() -> dict:
    """The whole thing, as the interface receives it."""
    kinds = adapter_kinds()
    return {name: {**spec, "adapters": name in kinds}
            for name, spec in KINDS_all().items()}


def ref_fields() -> dict:
    """Per kind, the fields that hold a reference to another item."""
    return {name: [f for f in fields_of(name).values() if f["type"] == "ref"]
            for name in KINDS_all()}


def clean(name: str, values: dict) -> dict:
    """Keep what the kind actually has, drop the rest.

    Fields the RMM fills are refused here as well: accepting them would let a
    typed value sit underneath a synced one, invisible until the link is
    removed and the old value suddenly reappears.
    """
    known = fields_of(name)
    out = {}
    for key, value in (values or {}).items():
        spec = known.get(key)
        if not spec or spec.get("rmm"):
            continue
        # A secret is never a field value: it does not travel with the item and
        # it does not go into the history, so a form cannot set one this way.
        if spec["type"] == "secret":
            continue
        if value is None:
            continue
        if spec["type"] == "list":
            rows = []
            for entry in (value if isinstance(value, list) else []):
                if not isinstance(entry, dict):
                    continue
                text = str(entry.get("value") or "").strip()
                if text:
                    rows.append({"label": str(entry.get("label") or "").strip(),
                                 "value": text})
            if rows:
                out[key] = rows
            continue
        if spec["type"] == "bool":
            # The history stores what a person reads ("ja"/"nee"), so undoing a
            # change hands those words back here -- and bool("nee") is True.
            if isinstance(value, str):
                out[key] = value.strip().lower() in ("ja", "true", "1", "yes", "aan")
            else:
                out[key] = bool(value)
        elif spec["type"] == "number":
            text = str(value).strip()
            if text:
                try:
                    out[key] = int(float(text))
                except ValueError:
                    continue
        else:
            text = str(value)
            # A long text keeps the whitespace it was written with: the
            # indentation of a command in a procedure is part of the procedure.
            # Everything else is trimmed, since a trailing space in a name is
            # never meant.
            if not spec.get("long"):
                text = text.strip()
            if text.strip():
                out[key] = text
    return out


def clean_form(name: str, values: dict) -> dict:
    """What a form sent, ready to store -- emptying a field included.

    :func:`clean` drops empty values, which is right when reading a payload but
    wrong for a form: a field the person deliberately cleared arrives empty and
    has to stay empty, or the old value silently comes back.
    """
    out = clean(name, values)
    known = fields_of(name)
    for key, value in (values or {}).items():
        spec = known.get(key)
        if spec and not spec.get("rmm") and spec["type"] != "secret" and key not in out:
            out[key] = ""
    return out


def label_of(name: str, key: str) -> str:
    """A field's name as a person reads it, for the revision history."""
    field = fields_of(name).get(key)
    return field["label"] if field else key
