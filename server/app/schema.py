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

STATUS = ["In gebruik", "Reserve", "In reparatie", "Afgevoerd"]


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
            _f("warranty_until", "Garantie tot", "date"),
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
            _f("warranty_until", "Garantie tot", "date"),
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
            _f("warranty_until", "Garantie tot", "date"),
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
            _f("contract_until", "Contract tot", "date"),
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

KINDS: dict[str, dict] = {
    "computer": COMPUTER,
    "network": NETWORK,
    "printer": PRINTER,
    "internet": INTERNET,
    "location": LOCATION,
    "contact": CONTACT,
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


def label_of(name: str, key: str) -> str:
    """A field's name as a person reads it, for the revision history."""
    field = fields_of(name).get(key)
    return field["label"] if field else key
