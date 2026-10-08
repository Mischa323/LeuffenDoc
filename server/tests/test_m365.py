"""A customer's Microsoft 365, read from Graph -- against a Graph of our own."""
import datetime

import httpx

from app import database, m365graph

GOOD = "goed~Geheim.Secret-0123456789"
SOON = (datetime.date.today() + datetime.timedelta(days=20)).isoformat()


def fake_graph(state: dict):
    """A tenant: what Graph would answer, and what it refuses."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.replace("/v1.0", "")
        if path in state.get("refuse", ()):
            return httpx.Response(403, json={"error": {"message": "Insufficient privileges"}})
        if path == "/organization":
            return httpx.Response(200, json={"value": [{"id": "tid-1", "displayName": "Proef BV", "verifiedDomains": [
                {"name": "proef.nl", "isDefault": True}, {"name": "proefbv.onmicrosoft.com", "isInitial": True}]}]})
        if path == "/directory/subscriptions":
            return httpx.Response(200, json={"value": [{"skuId": "sku-bp", "nextLifecycleDateTime": SOON + "T00:00:00Z"}]})
        if path == "/subscribedSkus":
            return httpx.Response(200, json={"value": [
                {"skuId": "sku-bp", "skuPartNumber": "SPB", "prepaidUnits": {"enabled": state["seats"]},
                 "consumedUnits": len(state["users"]), "capabilityStatus": "Enabled"},
                {"skuId": "sku-free", "skuPartNumber": "FLOW_FREE", "prepaidUnits": {"enabled": 0}, "consumedUnits": 0}]})
        if path == "/users":
            return httpx.Response(200, json={"value": [
                *({"id": f"u-{n}", "displayName": n, "userPrincipalName": f"{n.lower()}@proef.nl", "mail": f"{n.lower()}@proef.nl",
                   "accountEnabled": True, "assignedLicenses": [{"skuId": "sku-bp"}], "jobTitle": "Boekhouder"}
                  for n in state["users"]),
                {"id": "u-info", "displayName": "Info", "userPrincipalName": "info@proef.nl", "mail": "info@proef.nl",
                 "accountEnabled": False, "assignedLicenses": []}]})
        if path == "/users/u-info/mailboxSettings":
            return httpx.Response(200, json={"userPurpose": "shared"})
        if path == "/groups":
            return httpx.Response(200, json={"value": [
                {"id": "g-1", "displayName": "Iedereen", "mail": "iedereen@proef.nl", "mailEnabled": True,
                 "securityEnabled": False, "groupTypes": []},
                {"id": "g-2", "displayName": "Projecten", "mail": "projecten@proef.nl", "mailEnabled": True,
                 "securityEnabled": False, "groupTypes": ["Unified"], "resourceProvisioningOptions": ["Team"]}]})
        if path.startswith("/groups/") and path.endswith("/members"):
            return httpx.Response(200, json={"value": [{"displayName": n} for n in state["users"]]})
        if path == "/sites":
            return httpx.Response(200, json={"value": [
                {"displayName": "Projecten", "webUrl": "https://proef.sharepoint.com/sites/projecten"},
                {"displayName": "Anna", "webUrl": "https://proef-my.sharepoint.com/personal/anna"}]})
        if path == "/applications":
            return httpx.Response(200, json={"value": [{"displayName": "LeuffenDoc", "appId": "app-1",
                                                        "passwordCredentials": [{"displayName": "doc", "endDateTime": SOON + "T10:00:00Z"}]}]})
        if path == "/policies/identitySecurityDefaultsEnforcementPolicy":
            return httpx.Response(200, json={"isEnabled": False})
        if path == "/identity/conditionalAccess/policies":
            return httpx.Response(200, json={"value": [{"displayName": "MFA voor iedereen", "state": "enabled"}]})
        return httpx.Response(404, json={"error": {"message": "unknown"}})
    return handler


def use_fake(monkeypatch, state):
    real = httpx.Client
    monkeypatch.setattr(m365graph, "token", lambda tenant, client, secret: "tok" if secret == GOOD else
                        (_ for _ in ()).throw(m365graph.GraphError("het client secret klopt niet (AADSTS7000215)")))
    monkeypatch.setattr(m365graph.httpx, "Client",
                        lambda **kw: real(transport=httpx.MockTransport(fake_graph(state)), **kw))


def test_collect_reads_a_tenant(monkeypatch):
    state = {"seats": 10, "users": ["Anna", "Bram"]}
    use_fake(monkeypatch, state)
    got = m365graph.collect("tid-1", "client", GOOD)
    assert got["problems"] == []
    assert got["primary_domain"] == "proef.nl" and got["domains"][0] == {"label": "standaard", "value": "proef.nl"}
    assert got["subscriptions"] == [{"product": "Microsoft 365 Business Premium", "seats": "10", "used": "2",
                                     "renews": SOON, "status": "Actief"}]
    assert [u["name"] for u in got["users"]] == ["Anna", "Bram"]
    assert got["users"][0]["licenses"] == "Microsoft 365 Business Premium"
    assert got["shared"] == [{"mailbox": "info@proef.nl", "name": "Info", "kind": "Gedeeld"}]
    assert {g["kind"] for g in got["groups"]} == {"Distributielijst", "Team"}
    assert got["groups"][0]["members"] == "Anna, Bram"
    assert got["sites"] == [{"name": "Projecten", "url": "https://proef.sharepoint.com/sites/projecten"}]
    assert got["apps"][0]["expires"] == SOON and got["security_defaults"] == "Uit"
    assert got["ca"] == [{"name": "MFA voor iedereen", "state": "Aan"}]

    # A permission that was not granted costs its own part, and says which.
    state["refuse"] = {"/applications", "/identity/conditionalAccess/policies"}
    got = m365graph.collect("tid-1", "client", GOOD)
    assert "apps" not in got and "users" in got
    assert any("Application.Read.All" in p for p in got["problems"])


def test_a_tenant_linked_to_its_item(admin, viewer, org, make, monkeypatch):
    state = {"seats": 10, "users": ["Anna", "Bram"]}
    use_fake(monkeypatch, state)
    tenant = make(admin, "m365", "Proef BV", {"partner": "Leuffen IT (GDAP)", "domains": [{"label": "", "value": "getypt.nl"}]})
    url = f"/api/items/{tenant['id']}/m365"
    assert admin.get(url).json()["linked"] is False

    wrong = admin.put(url, json={"tenant_id": "tid-1", "client_id": "client", "client_secret": "fout"})
    assert wrong.status_code == 400 and "client secret klopt niet" in wrong.json()["detail"]
    assert viewer.put(url, json={"tenant_id": "tid-1", "client_id": "client", "client_secret": GOOD}).status_code == 403

    linked = admin.put(url, json={"tenant_id": "tid-1", "client_id": "client", "client_secret": GOOD})
    assert linked.status_code == 200, linked.text
    status = linked.json()
    assert status["linked"] and status["last_ok"] and status["secret_hint"] == "6789"
    assert "Geheim" not in str(database.m365_link(tenant["id"]))          # sealed, never stored as it is

    item = admin.get(f"/api/items/{tenant['id']}").json()
    assert item["source"] == "m365" and item["rmm"]["primary_domain"] == "proef.nl"
    assert "domains" not in item["fields"] and item["fields"]["partner"] == "Leuffen IT (GDAP)"   # typed stays
    # What is fetched is not typed over.
    admin.patch(f"/api/items/{tenant['id']}", json={"fields": {"primary_domain": "anders.nl", "backup": "Acronis"}})
    item = admin.get(f"/api/items/{tenant['id']}").json()
    assert "primary_domain" not in item["fields"] and item["fields"]["backup"] == "Acronis"

    # The next round says what changed, in words.
    state["users"] = ["Anna", "Cas"]
    state["seats"] = 12
    assert admin.post(f"{url}/sync").status_code == 200
    said = [c["said"] for r in admin.get(f"/api/items/{tenant['id']}/revisions").json()
            for c in r["changes"] if c.get("said")]
    assert said and "Nieuwe gebruiker: Cas" in said[0] and "Weg: Bram" in said[0]
    assert "Microsoft 365 Business Premium: 10 → 12 licenties" in said[0]

    # The bell: an app secret and a subscription that run out soon.
    bell = admin.get("/api/expiring").json()["items"]
    assert any(b["item_id"] == tenant["id"] and "LeuffenDoc" in b["field"] for b in bell), bell
    assert any(b["item_id"] == tenant["id"] and "Business Premium" in b["field"] for b in bell)

    # Unlinked, what was fetched stays on the page -- typed from then on.
    assert admin.delete(url).status_code == 200
    item = admin.get(f"/api/items/{tenant['id']}").json()
    assert item["source"] == "manual" and item["fields"]["primary_domain"] == "proef.nl"
    assert [u["name"] for u in item["fields"]["users"]] == ["Anna", "Cas"]
    assert database.m365_link(tenant["id"]) is None
