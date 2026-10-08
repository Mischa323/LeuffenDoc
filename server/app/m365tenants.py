"""A customer's Microsoft 365 tenant, as the RMM reads it.

The RMM links a tenant -- an app registration in it -- reads it from Microsoft
Graph every few hours, and warns when something in it runs out. LeuffenDoc
documents what it read, on one item of the kind ``m365`` per tenant (see
schema.M365), the way UniFi equipment arrives: known by the tenant's id
(``m365:<tenant id>``), the fields Microsoft 365 knows shown from the reading
and not typed over, the fields only people know -- the partner, the backup, who
may reach which shared mailbox -- typed here and kept.

The RMM stores its reading language-neutral (``shared``, ``team``,
``True``); here it is worded the way the page reads.
"""
from __future__ import annotations

import logging

from . import database, schema

log = logging.getLogger("leuffendoc.m365")

PREFIX = "m365:"
# What is compared field by field for the history; the long lists are said in
# words instead (see changes).
_PLAIN_KEYS = ["tenant_name", "primary_domain", "security_defaults"]

_SUB_STATUS = {"Enabled": "Actief", "Warning": "Verloopt", "Suspended": "Opgeschort",
               "Deleted": "Opgezegd", "LockedOut": "Geblokkeerd"}
_MAILBOX = {"shared": "Gedeeld", "room": "Ruimte", "equipment": "Apparatuur"}
_GROUP = {"team": "Team", "m365": "Microsoft 365-groep", "distribution": "Distributielijst",
          "mail_security": "Beveiligingsgroep met mail", "security": "Beveiligingsgroep"}
_CA = {"enabled": "Aan", "disabled": "Uit", "report": "Alleen rapporteren"}
PARTS = {"tenant": "Tenant en domeinen", "subscriptions": "Abonnementen", "users": "Gebruikers",
         "mailboxes": "Gedeelde mailboxen", "groups": "Groepen", "sites": "SharePoint",
         "apps": "App-registraties", "security_defaults": "Security defaults",
         "conditional_access": "Conditional Access"}


def _label(key: str) -> str:
    return schema.label_of("m365", key)


def payload(tenant: dict) -> dict:
    """The RMM's reading of one tenant as the fields of an m365 item, plus how
    the reading went -- for the page to say."""
    snap = tenant.get("snapshot") or {}
    out: dict = {}
    if "tenant" in snap:
        t = snap["tenant"] or {}
        out["tenant_id"] = t.get("id") or tenant.get("tenant_id") or ""
        out["tenant_name"] = t.get("name") or ""
        out["primary_domain"] = t.get("default_domain") or ""
        out["domains"] = [{"label": "standaard" if d.get("default") else ("start" if d.get("initial") else ""),
                           "value": d.get("name") or ""} for d in t.get("domains") or [] if d.get("name")]
    if "subscriptions" in snap:
        out["subscriptions"] = [{"product": s.get("product") or "", "seats": str(s.get("seats") or 0),
                                 "used": str(s.get("used") or 0), "renews": s.get("renews") or "",
                                 "status": _SUB_STATUS.get(s.get("status") or "", s.get("status") or "")}
                                for s in snap["subscriptions"]]
    if "users" in snap:
        out["users"] = [{"name": u.get("name") or "", "account": u.get("upn") or "",
                         "licenses": ", ".join(u.get("licenses") or []), "job": u.get("job") or "",
                         "enabled": "Ja" if u.get("enabled") else "Nee", "kind": "Gast" if u.get("guest") else ""}
                        for u in snap["users"]]
    if "mailboxes" in snap:
        out["shared"] = [{"mailbox": m.get("address") or "", "name": m.get("name") or "",
                          "kind": _MAILBOX.get(m.get("kind"), m.get("kind") or "")} for m in snap["mailboxes"]]
    if "groups" in snap:
        out["groups"] = [{"name": g.get("name") or "", "mail": g.get("mail") or "",
                          "kind": _GROUP.get(g.get("kind"), g.get("kind") or ""),
                          "members": "dynamisch" if g.get("dynamic") else ", ".join(g.get("members") or [])[:600]}
                         for g in snap["groups"]]
    if "sites" in snap:
        out["sites"] = [{"name": s.get("name") or "", "url": s.get("url") or ""} for s in snap["sites"]]
    if "apps" in snap:
        out["apps"] = [{"app": a.get("app") or "", "kind": "Secret" if a.get("kind") == "secret" else "Certificaat",
                        "name": a.get("name") or "", "expires": a.get("expires") or ""} for a in snap["apps"]]
    if snap.get("security_defaults") is not None:
        out["security_defaults"] = "Aan" if snap["security_defaults"] else "Uit"
    if "ca" in snap:
        out["ca"] = [{"name": c.get("name") or "", "state": _CA.get(c.get("state"), c.get("state") or "")}
                     for c in snap["ca"]]
    holds = [k for k in schema.M365_KEYS if k in out]
    return {**out, "holds": holds, "source": "m365",
            "problems": [{"part": PARTS.get(p.get("part"), p.get("part") or ""), "permission": p.get("permission") or "",
                          "error": p.get("error") or ""} for p in snap.get("problems") or []],
            "read_at": tenant.get("last_poll"), "ok": bool(tenant.get("ok")), "error": tenant.get("error") or ""}


def sync(tenants: list, by_rmm_org: dict) -> dict:
    """Lay each tenant the RMM reads over its item at the right customer --
    made when there is none, taken over when one was typed with the same
    tenant id or name -- and say what changed."""
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
            database.create_item(org_id, "m365", name, {}, by=None, source="m365",
                                 rmm_device_id=key, rmm=data, label=_label)
            made += 1
            continue
        said = changes(item.get("rmm") or {}, data)
        database.update_item(item["id"], rmm=data, rmm_keys=[k for k in _PLAIN_KEYS if k in data["holds"]],
                             by=None, source="m365", label=_label)
        if said:
            database.record(item["id"], "updated",
                            [{"key": "m365", "label": "Microsoft 365", "said": "; ".join(said)}],
                            by=None, source="m365")
    # A tenant the RMM no longer reads keeps its page and says so.
    gone = 0
    for item in database.synced_items(PREFIX):
        missing = item["rmm_device_id"] not in seen
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
    """What changed in a tenant, in words -- who joined and who left, a
    subscription with more or fewer licences, a new shared mailbox -- rather
    than two copies of a list of fifty people."""
    if not any(k in before for k in ("users", "subscriptions", "shared", "groups", "apps")):
        return []                                    # the first reading: nothing to compare with
    said = []

    def keyed(rows, key):
        return {r.get(key): r for r in rows or [] if r.get(key)}

    old, new = keyed(before.get("users"), "account"), keyed(after.get("users"), "account")
    said += [f"Nieuwe gebruiker: {new[a]['name']}" for a in new if a not in old]
    said += [f"Weg: {old[a]['name']}" for a in old if a not in new]
    for a in new:
        if a in old and old[a].get("licenses") != new[a].get("licenses"):
            said.append(f"{new[a]['name']}: {old[a].get('licenses') or 'geen licentie'} → "
                        f"{new[a].get('licenses') or 'geen licentie'}")
        if a in old and old[a].get("enabled") != new[a].get("enabled"):
            said.append(f"{new[a]['name']}: {'kan weer aanmelden' if new[a].get('enabled') == 'Ja' else 'aanmelden geblokkeerd'}")

    old, new = keyed(before.get("subscriptions"), "product"), keyed(after.get("subscriptions"), "product")
    said += [f"Nieuw abonnement: {p} ({new[p].get('seats')})" for p in new if p not in old]
    said += [f"Abonnement weg: {p}" for p in old if p not in new]
    said += [f"{p}: {old[p].get('seats')} → {new[p].get('seats')} licenties"
             for p in new if p in old and old[p].get("seats") != new[p].get("seats")]

    for key, field, word in (("shared", "mailbox", "mailbox"), ("groups", "name", "groep")):
        old, new = keyed(before.get(key), field), keyed(after.get(key), field)
        said += [f"Nieuwe {word}: {n}" for n in new if n not in old]
        said += [f"{word.capitalize()} weg: {n}" for n in old if n not in new]

    def creds(rows):
        return {(r.get("app"), r.get("kind"), r.get("expires")) for r in rows or []}
    for app, kind, expires in sorted(creds(after.get("apps")) - creds(before.get("apps")), key=str):
        said.append(f"{app}: nieuw {kind.lower()}{f', verloopt {expires}' if expires else ''}")
    return said[:60]
