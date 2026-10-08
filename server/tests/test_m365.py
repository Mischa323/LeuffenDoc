"""A customer's Microsoft 365 tenant, as the RMM reads it, documented here."""
import datetime
import json
import time

from app import database, m365tenants, rmm

SOON = (datetime.date.today() + datetime.timedelta(days=20)).isoformat()


def reading(users, seats=10, **extra):
    """What /api/v1/m365-tenants says about one tenant."""
    snapshot = {
        "tenant": {"id": "tid-1", "name": "Proef BV", "default_domain": "proef.nl",
                   "domains": [{"name": "proef.nl", "default": True, "initial": False},
                               {"name": "proefbv.onmicrosoft.com", "default": False, "initial": True}]},
        "subscriptions": [{"sku": "SPB", "product": "Microsoft 365 Business Premium", "seats": seats,
                           "used": len(users), "renews": SOON, "status": "Enabled"}],
        "users": [{"name": n, "upn": f"{n.lower()}@proef.nl", "licenses": ["Microsoft 365 Business Premium"],
                   "job": "Boekhouder", "enabled": True, "guest": False} for n in users],
        "mailboxes": [{"address": "info@proef.nl", "name": "Info", "kind": "shared"}],
        "groups": [{"name": "Projecten", "mail": "projecten@proef.nl", "kind": "team", "dynamic": False, "members": users}],
        "sites": [{"name": "Projecten", "url": "https://proef.sharepoint.com/sites/projecten"}],
        "apps": [{"app": "Backup", "app_id": "a1", "kind": "secret", "name": "backup", "key_id": "k1", "expires": SOON}],
        "security_defaults": False, "ca": [{"name": "MFA voor iedereen", "state": "enabled"}],
        "problems": [{"part": "sites", "permission": "Sites.Read.All", "error": "forbidden"}],
        "fetched_at": "2026-10-08T10:00:00+00:00", **extra}
    return {"id": "m365:tid-1", "tenant_id": "TID-1", "name": "Proef BV", "enabled": True,
            "last_poll": time.time(), "ok": True, "error": None, "snapshot": snapshot,
            "org": {"id": "org-365", "name": "Proef BV"}}


def test_a_tenant_the_rmm_reads_is_documented(admin, monkeypatch):
    org_id = database.upsert_org("Proef BV", rmm_org_id="org-365")
    # Typed by hand before, with its tenant id: taken over, not doubled.
    typed = admin.post(f"/api/orgs/{org_id}/items", json={"kind": "m365", "name": "Office van Proef", "fields": {
        "tenant_id": "tid-1", "partner": "Leuffen IT (GDAP)", "primary_domain": "oud.nl"}}).json()
    state = {"tenants": [reading(["Anna", "Bram"])]}
    monkeypatch.setattr(rmm, "fetch_devices", lambda: [])
    monkeypatch.setattr(rmm, "fetch_network_devices", lambda: [])
    monkeypatch.setattr(rmm, "fetch_m365_tenants", lambda: state["tenants"])
    assert rmm.sync_devices()["m365"] == 1

    items = [i for i in database.list_items(org_id) if i["kind"] == "m365"]
    assert [i["id"] for i in items] == [typed["id"]]
    item = admin.get(f"/api/items/{typed['id']}").json()
    assert item["source"] == "m365" and item["rmm_device_id"] == "m365:tid-1"
    got = item["rmm"]
    assert got["primary_domain"] == "proef.nl" and got["domains"][0] == {"label": "standaard", "value": "proef.nl"}
    assert got["subscriptions"] == [{"product": "Microsoft 365 Business Premium", "seats": "10", "used": "2",
                                     "renews": SOON, "status": "Actief"}]
    assert got["shared"] == [{"mailbox": "info@proef.nl", "name": "Info", "kind": "Gedeeld"}]
    assert got["groups"][0]["kind"] == "Team" and got["groups"][0]["members"] == "Anna, Bram"
    assert got["security_defaults"] == "Uit" and got["ca"] == [{"name": "MFA voor iedereen", "state": "Aan"}]
    assert got["problems"] == [{"part": "SharePoint", "permission": "Sites.Read.All", "error": "forbidden"}]
    # What only people know stays; what Microsoft 365 knows is not typed over.
    assert item["fields"]["partner"] == "Leuffen IT (GDAP)" and "primary_domain" not in item["fields"]
    admin.patch(f"/api/items/{typed['id']}", json={"fields": {"primary_domain": "anders.nl", "backup": "Acronis"}})
    item = admin.get(f"/api/items/{typed['id']}").json()
    assert "primary_domain" not in item["fields"] and item["fields"]["backup"] == "Acronis"
    told = {c["key"]: (c["from"], c["to"]) for r in reversed(admin.get(f"/api/items/{typed['id']}/revisions").json())
            for c in r["changes"] if "from" in c}
    assert told["primary_domain"] == ("oud.nl", "proef.nl")

    # The next reading says what changed, in words.
    state["tenants"] = [reading(["Anna", "Cas"], seats=12)]
    rmm.sync_devices()
    said = [c["said"] for r in admin.get(f"/api/items/{typed['id']}/revisions").json() for c in r["changes"] if c.get("said")]
    assert said and "Nieuwe gebruiker: Cas" in said[0] and "Weg: Bram" in said[0]
    assert "Microsoft 365 Business Premium: 10 → 12 licenties" in said[0]
    rmm.sync_devices()                                   # nothing new: no new line
    assert len([r for r in admin.get(f"/api/items/{typed['id']}/revisions").json()
                for c in r["changes"] if c.get("said")]) == 1

    # The bell: an app secret and a subscription that run out soon.
    bell = admin.get("/api/expiring").json()["items"]
    assert any(b["item_id"] == typed["id"] and "Backup" in b["field"] for b in bell), bell
    assert any(b["item_id"] == typed["id"] and "Business Premium" in b["field"] for b in bell)

    # An RMM too old to read tenants changes nothing; one that stopped says so.
    monkeypatch.setattr(rmm, "fetch_m365_tenants", lambda: None)
    rmm.sync_devices()
    assert database.get_item(typed["id"])["rmm_gone"] is False
    state["tenants"] = []
    monkeypatch.setattr(rmm, "fetch_m365_tenants", lambda: state["tenants"])
    rmm.sync_devices()
    assert database.get_item(typed["id"])["rmm_gone"] is True


def test_a_tenant_read_by_the_rmm_alone_gets_a_page(admin, monkeypatch):
    org_id = database.upsert_org("Nieuw BV", rmm_org_id="org-new")
    tenant = dict(reading(["Dirk"]), tenant_id="tid-new", id="m365:tid-new", name="Nieuw BV",
                  org={"id": "org-new", "name": "Nieuw BV"})
    monkeypatch.setattr(rmm, "fetch_devices", lambda: [])
    monkeypatch.setattr(rmm, "fetch_network_devices", lambda: [])
    monkeypatch.setattr(rmm, "fetch_m365_tenants", lambda: [tenant])
    rmm.sync_devices()
    made = [i for i in database.list_items(org_id) if i["kind"] == "m365"]
    assert len(made) == 1 and made[0]["name"] == "Nieuw BV" and made[0]["rmm"]["users"][0]["name"] == "Dirk"


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
