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

# Field types the interface knows how to render:
#   text, textarea, number, date, select, mac, ip, bool, ref
# A `ref` field holds the id of another item, of the kind named in `ref`.

# Not "afgevoerd": equipment that is out of use is archived, and one fact
# belongs in one place.
STATUS = ["In gebruik", "Reserve", "In reparatie"]


def _f(key, label, type="text", **extra):
    return {"key": key, "label": label, "type": type, **extra}


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
            _f("role", "Soort", "select", options=["Werkplek", "Laptop", "Server",
                                                   "Virtuele machine", "NAS", "Tablet"]),
            _f("status", "Status", "select", options=STATUS),
            _f("purpose", "Waar het voor dient", "textarea",
               hint="Waarom staat deze machine er — welke rol, welke toepassing."),
            _f("location", "Locatie", "ref", ref="location"),
            _f("user", "In gebruik bij", "ref", ref="contact"),
        ]},
        {"key": "hardware", "label": "Hardware", "fields": [
            _f("cpu", "Processor", rmm="cpu"),
            _f("memory", "Geheugen", rmm="memory"),
            _f("storage", "Schijven", rmm="storage"),
            _f("os", "Besturingssysteem", rmm="os"),
            _f("manufacturer", "Merk", rmm="manufacturer"),
            _f("model", "Model", rmm="model"),
            _f("serial", "Serienummer", rmm="serial"),
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
               options=["Switch", "Firewall", "Router", "Access point", "Modem"]),
            _f("status", "Status", "select", options=STATUS),
            _f("ports", "Aantal poorten", "number",
               hint="Alleen bij een switch. Hiermee wordt de poortenlijst opgebouwd."),
            _f("location", "Locatie", "ref", ref="location"),
        ]},
        {"key": "hardware", "label": "Apparaat", "fields": [
            _f("manufacturer", "Merk", rmm="manufacturer"),
            _f("model", "Model", rmm="model"),
            _f("serial", "Serienummer", rmm="serial"),
            _f("firmware", "Firmware"),
            _f("mgmt_ip", "Beheeradres", "ip"),
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
    "icon": "copy",
    "family": "configuratie",
    "sub": "Printers en multifunctionals",
    "backref": "Wat hiernaar verwijst",
    # What a list shows at a glance.
    "columns": ["status", "placement", "eol"],
    "groups": [
        {"key": "wat", "label": "Wat het is", "fields": [
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
            _f("provider", "Provider"),
            _f("line_type", "Soort lijn", "select",
               options=["Glasvezel", "Coax", "DSL", "4G/5G", "Straalverbinding"]),
            _f("speed_down", "Snelheid neer", hint="Bijvoorbeeld 1 Gbit/s."),
            _f("speed_up", "Snelheid op"),
            _f("ip_range", "Vast IP-blok",
               hint="Het toegewezen adres of blok, bijvoorbeeld 203.0.113.8/29."),
            _f("location", "Locatie", "ref", ref="location"),
            _f("router", "Aangesloten op", "ref", ref="network",
               hint="De firewall of router waar de lijn op binnenkomt."),
        ]},
        {"key": "contract", "label": "Contract", "fields": [
            _f("account_number", "Klant- of circuitnummer"),
            _f("contract_until", "Contract tot", "date", expiry=True),
            _f("notice_period", "Opzegtermijn"),
            _f("monthly", "Bedrag per maand"),
        ]},
        {"key": "storing", "label": "Bij een storing", "fields": [
            _f("support_phone", "Storingsnummer"),
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

CONTACT = {
    "label": "Contactpersoon",
    "plural": "Contactpersonen",
    "icon": "user",
    "family": "onderdeel",
    "sub": "Wie je bij deze klant belt",
    "backref": "Waar deze persoon bij hoort",
    # What a list shows at a glance.
    "columns": ["job", "email", "phone"],
    "groups": [
        {"key": "wie", "label": "Wie", "fields": [
            _f("job", "Functie"),
            _f("email", "E-mailadres"),
            _f("phone", "Telefoon"),
            _f("mobile", "Mobiel"),
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
    "columns": ["category", "username", "rotate_at"],
    "groups": [
        {"key": "wat", "label": "Waarvoor", "fields": [
            _f("category", "Soort", "select",
               options=["Beheerder", "Gebruiker", "Dienst", "Netwerk", "Overig"]),
            _f("username", "Gebruikersnaam"),
            _f("url", "Adres", hint="Waar je ermee inlogt."),
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

KINDS: dict[str, dict] = {
    "computer": COMPUTER,
    "network": NETWORK,
    "printer": PRINTER,
    "internet": INTERNET,
    "location": LOCATION,
    "contact": CONTACT,
    "password": PASSWORD,
}

# Equipment carries network adapters; an internet connection or a contact does
# not, so the interface only offers them where they mean something.
ADAPTER_KINDS = {"computer", "network", "printer"}


def kind(name: str) -> dict | None:
    return KINDS.get(name)


def fields_of(name: str) -> dict[str, dict]:
    """Every field of a kind, keyed, with its group folded in."""
    out: dict[str, dict] = {}
    for group in KINDS.get(name, {}).get("groups", []):
        for field in group["fields"]:
            out[field["key"]] = {**field, "group": group["key"]}
    return out


def catalogue() -> dict:
    """The whole thing, as the interface receives it."""
    return {name: {**spec, "adapters": name in ADAPTER_KINDS}
            for name, spec in KINDS.items()}


def ref_fields() -> dict:
    """Per kind, the fields that hold a reference to another item."""
    return {name: [f for f in fields_of(name).values() if f["type"] == "ref"]
            for name in KINDS}


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
        if value is None:
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
            text = str(value).strip()
            if text:
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
        if spec and not spec.get("rmm") and key not in out:
            out[key] = ""
    return out


def label_of(name: str, key: str) -> str:
    """A field's name as a person reads it, for the revision history."""
    field = fields_of(name).get(key)
    return field["label"] if field else key
