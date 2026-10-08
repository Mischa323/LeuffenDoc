"""The UniFi equipment the RMM watches becomes network devices here."""
from app import database, docpush, rmm


def _device(mac, name, model, kind, **extra):
    return {"id": f"unifi:{mac.replace(':', '')}", "source": "unifi", "mac": mac, "name": name,
            "model": model, "type": kind, "state": "online", "firmware": "4.0.6",
            "ip": "", "console": "UDM-Pro kantoor", "account": "Kantoor", "seen_at": 1_700_000_000,
            "org": {"id": "org-unifi", "name": "UniFi BV"}, **extra}


def test_unifi_equipment_is_documented(admin, monkeypatch):
    org_id = database.upsert_org("UniFi BV", rmm_org_id="org-unifi")
    # Documented by hand before the link existed -- and without an RMM, the
    # make, model and serial number are typed like any other field.
    hand = admin.post(f"/api/orgs/{org_id}/items", json={
        "kind": "network", "name": "USW-Kelder",
        "fields": {"role": "Switch", "serial": "SN-123", "model": "getypt", "firmware": "oud"}}).json()
    assert hand["fields"] == {"role": "Switch", "serial": "SN-123", "model": "getypt", "firmware": "oud"}

    gateway = _device("aa:bb:cc:00:00:01", "UDM-Pro", "UDM-Pro", "gateway", ip="192.168.1.1")
    switch = _device("aa:bb:cc:00:00:02", "usw-kelder", "USW-24-PoE", "switch",
                     uplink_mac="aa:bb:cc:00:00:01", clients=14)
    ap = _device("aa:bb:cc:00:00:03", "AP Kantine", "U6-Lite", "ap", state="offline")
    monkeypatch.setattr(rmm, "fetch_devices", lambda: [])
    monkeypatch.setattr(rmm, "fetch_network_devices", lambda: [gateway, switch, ap])
    result = rmm.sync_devices()
    assert result["network"] == 3 and result["new"] == 2

    items = {i["name"]: i for i in database.list_items(org_id)}
    assert set(items) == {"UDM-Pro", "USW-Kelder", "AP Kantine"}          # the switch is not doubled
    assert items["UDM-Pro"]["fields"]["role"] == "Router"
    assert items["AP Kantine"]["fields"]["role"] == "Wifi-punt"
    taken_over = items["USW-Kelder"]
    assert taken_over["id"] == hand["id"] and taken_over["rmm_device_id"] == "unifi:aabbcc000002"
    assert taken_over["rmm"]["model"] == "USW-24-PoE" and taken_over["rmm"]["manufacturer"] == "Ubiquiti"
    assert taken_over["rmm"]["uplink_mac"] == "aa:bb:cc:00:00:01" and taken_over["rmm"]["clients"] == 14
    # What was typed where UniFi now reports is not left underneath, unseen:
    # the history says what replaced it.
    assert taken_over["fields"] == {"role": "Switch", "serial": "SN-123"}
    told = {c["key"]: (c["from"], c["to"])                     # oldest first, so the newest line wins
            for r in reversed(admin.get(f"/api/items/{hand['id']}/revisions").json()) for c in r["changes"]}
    assert told["model"] == ("getypt", "USW-24-PoE") and told["firmware"] == ("oud", "4.0.6")

    # What UniFi knows comes from UniFi; what it does not stays yours.
    assert admin.patch(f"/api/items/{hand['id']}",
                       json={"fields": {"serial": "SN-456", "model": "overschreven"}}).status_code == 200
    now = database.get_item(hand["id"])
    assert now["fields"]["serial"] == "SN-456" and "model" not in now["fields"]

    # The management address is an adapter: the MAC is searchable, and an
    # access point can be patched into a switch port.
    adapters = database.list_adapters(items["UDM-Pro"]["id"])
    assert [(a["mac"], a["ipv4"]) for a in adapters] == [("aa:bb:cc:00:00:01", "192.168.1.1")]
    found = admin.get("/api/search", params={"q": "aa:bb:cc:00:00:01", "org": org_id}).json()
    assert any(hit.get("id") == items["UDM-Pro"]["id"] or hit.get("item_id") == items["UDM-Pro"]["id"]
               for hit in (found if isinstance(found, list) else found.get("results", [])))

    # A firmware update is history; a sync that changes nothing is not.
    gateway["firmware"] = "4.1.0"
    rmm.sync_devices()
    rmm.sync_devices()
    lines = [c for r in admin.get(f"/api/items/{items['UDM-Pro']['id']}/revisions").json()
             for c in r["changes"] if c["key"] == "firmware"]
    assert [(c["from"], c["to"]) for c in lines] == [("4.0.6", "4.1.0")]

    # They have no Docs tab in the RMM, so nothing is sent there for them.
    assert not any(k.startswith(rmm.NET_PREFIX) for k in docpush.wanted())

    # An RMM too old to list them says nothing about them: nothing is gone.
    monkeypatch.setattr(rmm, "fetch_network_devices", lambda: None)
    assert rmm.sync_devices()["network"] is None
    assert database.get_item(items["AP Kantine"]["id"])["rmm_gone"] is False
    # One that is no longer there keeps its page and says so.
    monkeypatch.setattr(rmm, "fetch_network_devices", lambda: [gateway, switch])
    rmm.sync_devices()
    assert database.get_item(items["AP Kantine"]["id"])["rmm_gone"] is True
    assert database.get_item(items["UDM-Pro"]["id"])["rmm_gone"] is False
