"""A customer's Microsoft 365, as the RMM reads it.

The RMM links a tenant -- an app registration in it -- reads it from Microsoft
Graph every few hours, and warns when something in it runs out. LeuffenDoc
documents what it read the way it documents everything: as items, each with a
page of its own, linkable, with notes and files --

  * the tenant itself (``m365``, known as ``m365:<tenant id>``): its domains,
    security settings and SharePoint sites;
  * every account (``m365user``), shared mailbox (``m365mailbox``), group or
    Team (``m365group``) and app registration (``m365app``) in it, known by
    their id in the tenant (``m365u:<tenant>:<id>`` and so on);
  * every subscription, as a licence (``license``, ``m365s:<tenant>:<sku>``),
    next to the licences typed for other software.

What Microsoft 365 knows is shown from the reading and not typed over; what
only people know -- who may reach a shared mailbox, what an app registration
is for, the contact an account belongs to -- is typed here and kept. Something
that leaves the tenant keeps its page and says so. One typed here before, with
the same address or name, is taken over rather than doubled.

The RMM stores its reading language-neutral (``shared``, ``team``, ``True``);
here it is worded the way the page reads.
"""
from __future__ import annotations

import datetime
import logging

from . import database, schema

log = logging.getLogger("leuffendoc.m365")

PREFIX = "m365:"
# What is compared field by field for the tenant's history; who joined and
# left is said in words instead (see changes).
_PLAIN_KEYS = ["tenant_name", "primary_domain", "security_defaults"]

_SUB_STATUS = {"Enabled": "Actief", "Warning": "Verloopt", "Suspended": "Opgeschort",
               "Deleted": "Opgezegd", "LockedOut": "Geblokkeerd"}
_MAILBOX = {"shared": "Gedeeld", "room": "Ruimte", "equipment": "Apparatuur"}
_GROUP = {"team": "Team", "m365": "Microsoft 365-groep", "distribution": "Distributielijst",
          "mail_security": "Beveiligingsgroep", "security": "Beveiligingsgroep"}
_CA = {"enabled": "Aan", "disabled": "Uit", "report": "Alleen rapporteren"}
_PHONE = {"business": "Werk", "mobile": "Mobiel"}
_COMPLIANCE = {"compliant": "Ja", "noncompliant": "Nee", "inGracePeriod": "Bijna", "unknown": "Onbekend",
               "notApplicable": "", "configManager": "ConfigMgr"}
_MFA_METHODS = {"microsoftAuthenticatorPush": "Authenticator-app", "softwareOneTimePasscode": "Authenticator-code",
                "microsoftAuthenticatorPasswordless": "Authenticator zonder wachtwoord", "mobilePhone": "telefoon",
                "fido2": "beveiligingssleutel", "windowsHelloForBusiness": "Windows Hello",
                "email": "e-mail", "passKeyDeviceBound": "passkey", "temporaryAccessPass": "tijdelijke toegangscode",
                "hardwareOneTimePasscode": "hardwaretoken", "alternateMobilePhone": "tweede telefoon",
                "officePhone": "kantoortelefoon", "securityQuestion": "beveiligingsvragen"}
# How someone confirms a sign-in by default.
_MFA_DEFAULT = {"push": "Melding in de Authenticator-app", "oath": "Code uit een app", "sms": "Sms",
                "voiceMobile": "Gebeld worden", "voiceAlternateMobile": "Gebeld worden (tweede nummer)",
                "voiceOffice": "Gebeld worden (kantoor)", "none": "", "unknownFutureValue": ""}
PARTS = {"tenant": "Tenant en domeinen", "subscriptions": "Abonnementen", "users": "Gebruikers",
         "mailboxes": "Gedeelde mailboxen", "groups": "Groepen", "sites": "SharePoint",
         "apps": "App-registraties", "security_defaults": "Security defaults",
         "conditional_access": "Conditional Access", "managers": "Managers", "sign_ins": "Laatste aanmelding",
         "mfa": "MFA-registratie", "roles": "Beheerdersrollen", "devices": "Apparaten in Intune",
         "mailbox_usage": "Mailboxgrootte"}


def _label(kind: str):
    return lambda key: schema.label_of(kind, key)


def _moment(iso: str) -> str:
    """An ISO moment as a person reads it here: 9-10-2026 14:05, in Dutch time."""
    if not iso:
        return ""
    try:
        at = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso[:16]
    try:
        from zoneinfo import ZoneInfo
        at = at.astimezone(ZoneInfo("Europe/Amsterdam"))
    except Exception:
        pass
    return f"{at.day}-{at.month}-{at.year} {at:%H:%M}"


def _day(date: str) -> str:
    try:
        d = datetime.date.fromisoformat(date[:10])
    except (TypeError, ValueError):
        return date or ""
    return f"{d.day}-{d.month}-{d.year}"


def _bytes(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    for unit, step in (("TB", 1024 ** 4), ("GB", 1024 ** 3), ("MB", 1024 ** 2), ("kB", 1024)):
        if n >= step:
            v = n / step
            return (f"{v:.1f}".rstrip("0").rstrip(".") if v < 100 else f"{round(v)}").replace(".", ",") + f" {unit}"
    return f"{int(n)} B"


def _items(values) -> list:
    return [{"label": "", "value": str(v)} for v in values or [] if v]


def _mailbox(usage: dict | None) -> dict:
    usage = usage or {}
    size = _bytes(usage.get("size")) if usage.get("size") is not None else ""
    if size and usage.get("quota"):
        size += f" van {_bytes(usage['quota'])}"
    return {"mailbox_size": size, "mailbox_items": str(usage["items"]) if usage.get("items") is not None else "",
            "mailbox_activity": _day(usage.get("last_activity") or "")}


# --------------------------------------------------------------------------- #
# The tenant itself
# --------------------------------------------------------------------------- #
def payload(tenant: dict) -> dict:
    """The RMM's reading of one tenant as the fields of its m365 item, plus how
    the reading went (for the page to say) and a roster of what is in it (for
    the history to say who joined and left)."""
    snap = tenant.get("snapshot") or {}
    out: dict = {}
    if "tenant" in snap:
        t = snap["tenant"] or {}
        out["tenant_id"] = t.get("id") or tenant.get("tenant_id") or ""
        out["tenant_name"] = t.get("name") or ""
        out["primary_domain"] = t.get("default_domain") or ""
        out["domains"] = [{"label": "standaard" if d.get("default") else ("start" if d.get("initial") else ""),
                           "value": d.get("name") or ""} for d in t.get("domains") or [] if d.get("name")]
    if "sites" in snap:
        out["sites"] = [{"name": s.get("name") or "", "url": s.get("url") or ""} for s in snap["sites"]]
    if snap.get("security_defaults") is not None:
        out["security_defaults"] = "Aan" if snap["security_defaults"] else "Uit"
    if "ca" in snap:
        out["ca"] = [{"name": c.get("name") or "", "state": _CA.get(c.get("state"), c.get("state") or "")}
                     for c in snap["ca"]]
    holds = [k for k in schema.M365_KEYS if k in out]
    roster = {
        "users": {u.get("upn") or u.get("id"): u.get("name") or "" for u in snap.get("users") or []},
        "licences": {u.get("upn") or u.get("id"): ", ".join(u.get("licenses") or []) for u in snap.get("users") or []},
        "subscriptions": {s.get("product"): s.get("seats") for s in snap.get("subscriptions") or []},
        "mailboxes": sorted(m.get("address") or "" for m in snap.get("mailboxes") or []),
        "groups": sorted(g.get("name") or "" for g in snap.get("groups") or []),
        "apps": sorted(f"{a.get('app')}|{a.get('kind')}|{a.get('expires')}" for a in snap.get("apps") or []),
    } if snap else {}
    return {**out, "holds": holds, "source": "m365", "roster": roster,
            "problems": [{"part": PARTS.get(p.get("part"), p.get("part") or ""), "permission": p.get("permission") or "",
                          "error": p.get("error") or ""} for p in snap.get("problems") or []],
            "read_at": tenant.get("last_poll"), "ok": bool(tenant.get("ok")), "error": tenant.get("error") or ""}


# --------------------------------------------------------------------------- #
# What is in it: each its own item
# --------------------------------------------------------------------------- #
def _user(u: dict, tenant_item: str) -> dict:
    mfa = u.get("mfa")
    methods = ", ".join(_MFA_METHODS.get(m, m) for m in (mfa or {}).get("methods") or [])
    devices = [{"name": d.get("name") or "", "os": " ".join(x for x in (d.get("os"), d.get("os_version")) if x),
                "compliance": _COMPLIANCE.get(d.get("compliance"), d.get("compliance") or ""),
                "last_sync": _day(d.get("last_sync") or ""),
                "model": " ".join(x for x in (d.get("manufacturer"), d.get("model")) if x),
                "serial": d.get("serial") or ""} for d in u.get("devices") or []]
    manager = u.get("manager") or {}
    return {
        "role": "Gast" if u.get("guest") else ("Geblokkeerd" if not u.get("enabled") else "Gebruiker"),
        "upn": u.get("upn") or "", "mail": u.get("mail") or "", "aliases": _items(u.get("aliases")),
        "licenses": _items(u.get("licenses")), "tenant": tenant_item,
        "created": _day(u.get("created") or ""), "synced": "Ja" if u.get("synced") else "",
        "job": u.get("job") or "", "department": u.get("department") or "", "company": u.get("company") or "",
        "office": u.get("office") or "",
        "phones": [{"label": _PHONE.get(p.get("label"), p.get("label") or ""), "value": p.get("value") or ""}
                   for p in u.get("phones") or [] if p.get("value")],
        "city": ", ".join(x for x in (u.get("city"), u.get("country")) if x),
        "manager": f"{manager.get('name')} ({manager.get('upn')})" if manager.get("upn") else (manager.get("name") or ""),
        "employee_id": u.get("employee_id") or "",
        "mfa": ("" if mfa is None else (f"Ja — {methods}" if mfa.get("registered") and methods
                                        else "Ja" if mfa.get("registered") else "Nee, niet geregistreerd")),
        "mfa_default": _MFA_DEFAULT.get((mfa or {}).get("default") or "", (mfa or {}).get("default") or ""),
        "roles": _items(u.get("roles")),
        "last_sign_in": _moment(u.get("last_sign_in") or ""),
        "last_sign_in_background": _moment(u.get("last_sign_in_background") or ""),
        "password_changed": _day(u.get("password_changed") or ""),
        **_mailbox(u.get("mailbox")),
        "groups": _items(sorted(set(u.get("groups") or []))),
        "devices": devices,
    }


def _mailbox_item(m: dict, tenant_item: str) -> dict:
    return {"role": _MAILBOX.get(m.get("kind"), m.get("kind") or ""), "address": m.get("address") or "",
            "aliases": _items(m.get("aliases")), "tenant": tenant_item, **_mailbox(m.get("mailbox"))}


def _group(g: dict, tenant_item: str) -> dict:
    members = g.get("members") or []
    return {"role": _GROUP.get(g.get("kind"), g.get("kind") or ""), "mail": g.get("mail") or "",
            "description": g.get("description") or "",
            "visibility": {"Public": "Openbaar", "Private": "Privé", "HiddenMembership": "Verborgen leden"}
            .get(g.get("visibility") or "", g.get("visibility") or ""),
            "member_count": "dynamisch" if g.get("dynamic") else str(len(members)),
            "tenant": tenant_item, "created": _day(g.get("created") or ""),
            "owners": _items(g.get("owners")), "members": _items(members)}


def _app(a: dict, tenant_item: str) -> dict:
    creds = [{"kind": "Secret" if c.get("kind") == "secret" else "Certificaat", "name": c.get("name") or "",
              "expires": c.get("expires") or ""} for c in a.get("credentials") or []]
    dates = sorted(c["expires"] for c in creds if c["expires"])
    audience = {"AzureADMyOrg": "Alleen deze tenant", "AzureADMultipleOrgs": "Elke tenant",
                "AzureADandPersonalMicrosoftAccount": "Elke tenant en persoonlijke accounts",
                "PersonalMicrosoftAccount": "Persoonlijke accounts"}
    return {"app_id": a.get("app_id") or "", "next_expiry": dates[0] if dates else "",
            "audience": audience.get(a.get("audience") or "", a.get("audience") or ""), "tenant": tenant_item,
            "created": _day(a.get("created") or ""), "credentials": creds}


def _subscription(sub: dict, tenant_item: str) -> dict:
    return {"product": sub.get("product") or "", "license_type": "Abonnement",
            "seats": int(sub.get("seats") or 0), "seats_used": int(sub.get("used") or 0),
            "status": _SUB_STATUS.get(sub.get("status") or "", sub.get("status") or ""),
            "expires_at": sub.get("renews") or "", "tenant": tenant_item}


# For each part of a reading: the item kind, its id prefix, the reading's list,
# the row's own id, what makes a typed item the same one, the fields, and the
# fields whose change is history.
_CHILDREN = [
    ("m365user", "m365u:", "users", lambda r: r.get("id") or r.get("upn"), ("upn", lambda r: r.get("upn")), _user,
     ["role", "licenses", "department", "job", "roles", "manager"], lambda r: r.get("name") or r.get("upn")),
    ("m365mailbox", "m365m:", "mailboxes", lambda r: r.get("id") or r.get("address"),
     ("address", lambda r: r.get("address")), _mailbox_item, ["role", "address"],
     lambda r: r.get("name") or r.get("address")),
    ("m365group", "m365g:", "groups", lambda r: r.get("id") or r.get("name"), ("mail", lambda r: r.get("mail")),
     _group, ["role", "mail", "owners"], lambda r: r.get("name")),
    ("m365app", "m365a:", "applications", lambda r: r.get("app_id") or r.get("id"),
     ("app_id", lambda r: r.get("app_id")), _app, ["next_expiry"], lambda r: r.get("name")),
    ("license", "m365s:", "subscriptions", lambda r: r.get("sku_id") or r.get("sku") or r.get("product"),
     ("product", lambda r: r.get("product")), _subscription, ["seats", "status", "expires_at"],
     lambda r: r.get("product")),
]


def _sync_children(snap: dict, tid: str, org_id: str, tenant_item: str) -> int:
    """Every account, mailbox, group, app registration and subscription in a
    reading as an item; those gone from a part that was read say so."""
    made = 0
    for kind, prefix, part, row_id, (match_key, match), fields_of, history, name_of in _CHILDREN:
        if part not in snap:
            continue                        # not read this time (a permission missing): leave as it is
        seen = set()
        label = _label(kind)
        holds = [f["rmm"] for f in schema.fields_of(kind).values() if f.get("rmm")]
        for row in snap[part] or []:
            rid = str(row_id(row) or "").strip().lower()
            name = str(name_of(row) or "").strip()
            if not rid or not name:
                continue
            key = f"{prefix}{tid}:{rid}"
            if key in seen:
                continue
            seen.add(key)
            data = {**fields_of(row, tenant_item), "holds": holds, "source": "m365"}
            item = database.item_by_rmm_device(key)
            if not item:
                item = database.unlinked_by_field(org_id, kind, match_key, match(row) or "", name)
                if item:
                    database.link_rmm(item["id"], key, holds, source="m365")
                    item = database.get_item(item["id"])
            if not item:
                database.create_item(org_id, kind, name, {}, by=None, source="m365",
                                     rmm_device_id=key, rmm=data, label=label)
                made += 1
                continue
            database.update_item(item["id"], rmm=data, rmm_keys=history, by=None, source="m365", label=label)
        for item in database.synced_items(f"{prefix}{tid}:"):
            missing = item["rmm_device_id"] not in seen
            if missing != item["rmm_gone"]:
                database.mark_rmm_gone(item["id"], missing)
    return made


def sync(tenants: list, by_rmm_org: dict) -> dict:
    """Lay each tenant the RMM reads over its items at the right customer --
    made when there are none, taken over when typed before -- and say what
    changed."""
    seen: set = set()
    made = 0
    for tenant in tenants:
        org_id = by_rmm_org.get((tenant.get("org") or {}).get("id"))
        tid = (tenant.get("tenant_id") or "").strip().lower()
        if not org_id or not tid or not tenant.get("snapshot"):
            continue                       # a customer this side does not have, or not read yet
        key = PREFIX + tid
        seen.add(key)
        data = payload(tenant)
        name = (tenant.get("name") or data.get("tenant_name") or data.get("primary_domain") or tid).strip()
        item = database.item_by_rmm_device(key)
        if not item:
            item = database.unlinked_tenant(org_id, tid, name)
            if item:
                database.link_rmm(item["id"], key, data["holds"], source="m365")
                item = database.get_item(item["id"])
        if not item:
            item = database.create_item(org_id, "m365", name, {}, by=None, source="m365",
                                        rmm_device_id=key, rmm=data, label=_label("m365"))
            made += 1
        else:
            said = changes((item.get("rmm") or {}).get("roster") or {}, data["roster"])
            database.update_item(item["id"], rmm=data, rmm_keys=[k for k in _PLAIN_KEYS if k in data["holds"]],
                                 by=None, source="m365", label=_label("m365"))
            if said:
                database.record(item["id"], "updated",
                                [{"key": "m365", "label": "Microsoft 365", "said": "; ".join(said)}],
                                by=None, source="m365")
        made += _sync_children(tenant["snapshot"], tid, org_id, item["id"])
    # A tenant the RMM no longer reads keeps its page and says so -- and so
    # does everything that was in it.
    gone = 0
    for item in database.synced_items(PREFIX):
        missing = item["rmm_device_id"] not in seen
        if missing:
            tid = item["rmm_device_id"][len(PREFIX):]
            for _kind, prefix, *_ in _CHILDREN:
                for child in database.synced_items(f"{prefix}{tid}:"):
                    if not child["rmm_gone"]:
                        database.mark_rmm_gone(child["id"], True)
        if missing != item["rmm_gone"]:
            database.mark_rmm_gone(item["id"], missing)
        gone += missing
    return {"tenants": len(seen), "new": made, "gone": gone}


def retire_own_links() -> int:
    """Before the RMM read tenants, LeuffenDoc did, with a link of its own.
    Each such link is undone -- what it read stays on the page, typed -- so
    the RMM's reading takes the item over when the tenant is linked there."""
    undone = 0
    try:
        links = database.rows("SELECT item_id FROM m365_links")
    except Exception:
        return 0                            # no such table: nothing was ever linked here
    for link in links:
        database.unlink_rmm(link["item_id"], schema.M365_KEYS)
        undone += 1
    with database.write() as conn:
        conn.execute("DROP TABLE IF EXISTS m365_links")
    if undone:
        log.info("%d Microsoft 365 link(s) made here were undone; link the tenants in the RMM", undone)
    return undone


def changes(before: dict, after: dict) -> list:
    """What changed in a tenant, in words -- who joined and who left, a licence
    given or taken, a subscription with more or fewer seats, a new shared
    mailbox or group, a new app secret -- from the roster of two readings."""
    if not before:
        return []                                    # the first reading: nothing to compare with
    said = []
    old, new = before.get("users") or {}, after.get("users") or {}
    said += [f"Nieuwe gebruiker: {new[a]}" for a in new if a not in old]
    said += [f"Weg: {old[a]}" for a in old if a not in new]
    old_l, new_l = before.get("licences") or {}, after.get("licences") or {}
    said += [f"{new[a]}: {old_l.get(a) or 'geen licentie'} → {new_l.get(a) or 'geen licentie'}"
             for a in new if a in old and old_l.get(a) != new_l.get(a)]
    old, new = before.get("subscriptions") or {}, after.get("subscriptions") or {}
    said += [f"Nieuw abonnement: {p} ({new[p]})" for p in new if p not in old]
    said += [f"Abonnement weg: {p}" for p in old if p not in new]
    said += [f"{p}: {old[p]} → {new[p]} licenties" for p in new if p in old and old[p] != new[p]]
    for key, word in (("mailboxes", "mailbox"), ("groups", "groep")):
        old, new = set(before.get(key) or []), set(after.get(key) or [])
        said += [f"Nieuwe {word}: {n}" for n in sorted(new - old)]
        said += [f"{word.capitalize()} weg: {n}" for n in sorted(old - new)]
    for entry in sorted(set(after.get("apps") or []) - set(before.get("apps") or [])):
        app, kind, expires = (entry.split("|") + ["", ""])[:3]
        said.append(f"{app}: nieuw {'secret' if kind == 'secret' else 'certificaat'}"
                    f"{f', verloopt {expires}' if expires and expires != 'None' else ''}")
    return said[:60]
