"""A customer's Microsoft 365, as the RMM reads it: the tenant, and every
account, shared mailbox, group, app registration and subscription in it as an
item of its own."""
import datetime
import json
import time

from app import database, m365tenants, rmm

SOON = (datetime.date.today() + datetime.timedelta(days=20)).isoformat()
LIC = "Microsoft 365 Business Premium"


def user(uid, name, **extra):
    upn = f"{name.split()[0].lower()}@proef.nl"
    return {"id": uid, "name": name, "upn": upn, "mail": upn, "aliases": [f"{name.split()[0].lower()}@proef.be"],
            "licenses": [LIC], "job": "Boekhouder", "department": "Financiën", "company": "Proef BV",
            "office": "Venlo", "phones": [{"label": "mobile", "value": "06-12345678"}], "city": "Venlo",
            "country": "NL", "employee_id": "", "created": "2024-01-02", "password_changed": "2026-09-01",
            "synced": False, "enabled": True, "guest": False,
            "manager": {"name": "Directeur", "upn": "dir@proef.nl"},
            "last_sign_in": "2026-10-08T12:30:00Z", "last_sign_in_background": "",
            "mfa": {"registered": True, "capable": True, "methods": ["microsoftAuthenticatorPush"], "default": "push"},
            "roles": [], "groups": ["Projecten"],
            "devices": [{"name": "LT-ANNA", "os": "Windows", "os_version": "10.0.22631", "compliance": "compliant",
                         "last_sync": "2026-10-08", "model": "Latitude 5440", "manufacturer": "Dell", "serial": "ABC123"}],
            "mailbox": {"size": 2_254_857_830, "items": 12000, "quota": 53_687_091_200, "last_activity": "2026-10-08"},
            **extra}


def reading(users, seats=10, **extra):
    """What /api/v1/m365-tenants says about one tenant."""
    snapshot = {
        "tenant": {"id": "tid-1", "name": "Proef BV", "default_domain": "proef.nl",
                   "domains": [{"name": "proef.nl", "default": True, "initial": False}]},
        "subscriptions": [{"sku_id": "sku-bp", "sku": "SPB", "product": LIC, "seats": seats,
                           "used": len(users), "renews": SOON, "status": "Enabled"}],
        "users": users,
        "mailboxes": [{"id": "mb-info", "address": "info@proef.nl", "name": "Info", "kind": "shared", "aliases": [],
                       "mailbox": {"size": 1024 ** 3, "items": 500, "quota": None, "last_activity": "2026-10-07"}}],
        "groups": [{"id": "g-proj", "name": "Projecten", "mail": "projecten@proef.nl", "kind": "team", "dynamic": False,
                    "description": "Alle projecten", "visibility": "Private", "created": "2025-01-01",
                    "members": [u["name"] for u in users], "member_upns": [u["upn"] for u in users], "owners": ["Anna"]}],
        "sites": [{"name": "Projecten", "url": "https://proef.sharepoint.com/sites/projecten"}],
        "apps": [{"app": "Backup", "app_id": "a1", "kind": "secret", "name": "backup", "key_id": "k1", "expires": SOON}],
        "applications": [{"id": "o1", "app_id": "a1", "name": "Backup", "created": "2025-03-01",
                          "audience": "AzureADMyOrg",
                          "credentials": [{"kind": "secret", "name": "backup", "key_id": "k1", "expires": SOON}]}],
        "security_defaults": False, "ca": [{"name": "MFA voor iedereen", "state": "enabled"}],
        "problems": [{"part": "devices", "permission": "DeviceManagementManagedDevices.Read.All", "error": "forbidden"}],
        "fetched_at": "2026-10-08T10:00:00+00:00", **extra}
    return {"id": "m365:tid-1", "tenant_id": "TID-1", "name": "Proef BV", "enabled": True,
            "last_poll": time.time(), "ok": True, "error": None, "snapshot": snapshot,
            "org": {"id": "org-365", "name": "Proef BV"}}


def items_of(org_id, kind):
    return {i["name"]: i for i in database.list_items(org_id, include_archived=True) if i["kind"] == kind}


def test_a_tenant_and_everything_in_it_become_items(admin, monkeypatch):
    org_id = database.upsert_org("Proef BV", rmm_org_id="org-365")
    # Typed by hand before: the tenant with its id, an account with its address.
    typed = admin.post(f"/api/orgs/{org_id}/items", json={"kind": "m365", "name": "Office van Proef", "fields": {
        "tenant_id": "tid-1", "partner": "Leuffen IT (GDAP)", "primary_domain": "oud.nl"}}).json()
    typed_anna = admin.post(f"/api/orgs/{org_id}/items", json={"kind": "m365user", "name": "Anna (getypt)", "fields": {
        "upn": "anna@proef.nl", "department": "oud"}}).json()
    state = {"tenants": [reading([user("u-anna", "Anna de Vries"), user("u-bram", "Bram Jansen", enabled=False)])]}
    monkeypatch.setattr(rmm, "fetch_devices", lambda: [])
    monkeypatch.setattr(rmm, "fetch_network_devices", lambda: [])
    monkeypatch.setattr(rmm, "fetch_m365_tenants", lambda: state["tenants"])
    assert rmm.sync_devices()["m365"] == 1

    tenants = items_of(org_id, "m365")
    assert list(tenants) == ["Office van Proef"] and tenants["Office van Proef"]["id"] == typed["id"]
    tenant = admin.get(f"/api/items/{typed['id']}").json()
    assert tenant["rmm"]["primary_domain"] == "proef.nl" and tenant["fields"]["partner"] == "Leuffen IT (GDAP)"
    assert tenant["rmm"]["ca"] == [{"name": "MFA voor iedereen", "state": "Aan"}]
    assert tenant["rmm"]["problems"][0]["part"] == "Apparaten in Intune"

    # Every account an item of its own; the typed one taken over by its address.
    accounts = items_of(org_id, "m365user")
    assert set(accounts) == {"Anna (getypt)", "Bram Jansen"} and accounts["Anna (getypt)"]["id"] == typed_anna["id"]
    anna = admin.get(f"/api/items/{typed_anna['id']}").json()
    r = anna["rmm"]
    assert anna["source"] == "m365" and r["role"] == "Gebruiker" and r["tenant"] == typed["id"]
    assert r["licenses"] == [{"label": "", "value": LIC}] and r["department"] == "Financiën"
    assert r["phones"] == [{"label": "Mobiel", "value": "06-12345678"}] and r["manager"] == "Directeur (dir@proef.nl)"
    assert r["mfa"] == "Ja — Authenticator-app" and r["last_sign_in"].startswith("8-10-2026")
    assert r["mailbox_size"] == "2,1 GB van 50 GB" and r["groups"] == [{"label": "", "value": "Projecten"}]
    assert r["devices"][0]["name"] == "LT-ANNA" and r["devices"][0]["compliance"] == "Ja"
    assert accounts["Bram Jansen"]["rmm"]["role"] == "Geblokkeerd"
    # What is read is not typed over; what is typed stays.
    admin.patch(f"/api/items/{typed_anna['id']}", json={"fields": {"department": "anders", "notes": "VIP"}})
    anna = admin.get(f"/api/items/{typed_anna['id']}").json()
    assert "department" not in anna["fields"] and anna["fields"]["notes"] == "VIP"

    mailbox = items_of(org_id, "m365mailbox")["Info"]
    assert mailbox["rmm"]["role"] == "Gedeeld" and mailbox["rmm"]["mailbox_size"] == "1 GB"
    group = items_of(org_id, "m365group")["Projecten"]
    assert group["rmm"]["role"] == "Team" and group["rmm"]["member_count"] == "2"
    assert group["rmm"]["visibility"] == "Privé" and group["rmm"]["owners"] == [{"label": "", "value": "Anna"}]
    app = items_of(org_id, "m365app")["Backup"]
    assert app["rmm"]["next_expiry"] == SOON and app["rmm"]["audience"] == "Alleen deze tenant"
    licence = items_of(org_id, "license")[LIC]
    assert licence["rmm"]["seats"] == 10 and licence["rmm"]["seats_used"] == 2 and licence["rmm"]["status"] == "Actief"

    # The customer's sidebar counts them by type, like configurations.
    roles = admin.get(f"/api/orgs/{org_id}/summary").json()["roles"]
    assert roles["m365user"] == {"Gebruiker": 1, "Geblokkeerd": 1} and roles["m365group"] == {"Team": 1}

    # The bell: an app secret and a subscription that run out soon.
    bell = admin.get("/api/expiring").json()["items"]
    assert any(b["item_id"] == app["id"] for b in bell) and any(b["item_id"] == licence["id"] for b in bell)

    # The next reading: who joined and left on the tenant; licences on the account.
    state["tenants"] = [reading([user("u-anna", "Anna de Vries", licenses=[]), user("u-cas", "Cas Peters")], seats=12)]
    rmm.sync_devices()
    said = [c["said"] for r in admin.get(f"/api/items/{typed['id']}/revisions").json() for c in r["changes"] if c.get("said")]
    assert said and "Nieuwe gebruiker: Cas Peters" in said[0] and "Weg: Bram Jansen" in said[0]
    assert f"{LIC}: 10 → 12 licenties" in said[0]
    told = [c for r in admin.get(f"/api/items/{typed_anna['id']}/revisions").json() for c in r["changes"]
            if c["key"] == "licenses"]
    assert told and told[0]["from"] == LIC and told[0]["to"] == ""
    accounts = items_of(org_id, "m365user")
    assert accounts["Bram Jansen"]["rmm_gone"] is True and "Cas Peters" in accounts
    assert items_of(org_id, "license")[LIC]["rmm"]["seats"] == 12

    # A part that could not be read this time is left as it was.
    snap = reading([user("u-anna", "Anna de Vries"), user("u-cas", "Cas Peters")])
    del snap["snapshot"]["groups"]
    state["tenants"] = [snap]
    rmm.sync_devices()
    assert items_of(org_id, "m365group")["Projecten"]["rmm_gone"] is False

    # A tenant the RMM stops reading keeps its page and says so; an older RMM changes nothing.
    monkeypatch.setattr(rmm, "fetch_m365_tenants", lambda: None)
    rmm.sync_devices()
    assert database.get_item(typed["id"])["rmm_gone"] is False
    monkeypatch.setattr(rmm, "fetch_m365_tenants", lambda: [])
    rmm.sync_devices()
    assert database.get_item(typed["id"])["rmm_gone"] is True
    assert items_of(org_id, "m365user")["Cas Peters"]["rmm_gone"] is True          # and what was in it


def test_links_made_here_before_are_undone(admin, org, make):
    """Before the RMM read tenants, LeuffenDoc linked them itself; such a link
    is undone at start-up, keeping what was read."""
    item = make(admin, "m365", "Oud gekoppeld", {})
    with database.write() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS m365_links (item_id TEXT PRIMARY KEY, tenant_id TEXT)")
        conn.execute("INSERT INTO m365_links VALUES (?, ?)", (item["id"], "tid-old"))
        conn.execute("UPDATE items SET source='m365', rmm_device_id='m365:tid-old', rmm_json=? WHERE id=?",
                     (json.dumps({"tenant_id": "tid-old", "primary_domain": "oud.nl",
                                  "holds": ["tenant_id", "primary_domain"]}), item["id"]))
    assert m365tenants.retire_own_links() == 1
    after = database.get_item(item["id"])
    assert after["source"] == "manual" and after["fields"]["tenant_id"] == "tid-old"
    assert after["fields"]["primary_domain"] == "oud.nl"
    assert not database.rows("SELECT name FROM sqlite_master WHERE name='m365_links'")
