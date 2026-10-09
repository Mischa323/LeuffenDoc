"""The networks a UniFi console has become Netwerk items here: subnet,
gateway, VLAN and DHCP from UniFi, linked to the gateway that routes them."""
from app import database, rmm

ORG = {"id": "org-net", "name": "Netwerk BV"}
CONSOLE = "con-1:123"


def _gateway():
    return {"id": "unifi:aabbcc000a01", "source": "unifi", "mac": "aa:bb:cc:00:0a:01", "name": "UDM-Pro",
            "model": "UDM-Pro", "type": "gateway", "state": "online", "firmware": "4.0.6", "ip": "192.168.1.1",
            "console": "UDM-Pro kantoor", "account": "Kantoor", "seen_at": 1_700_000_000, "org": ORG}


def _net(nid, name, **extra):
    net = {"id": nid, "key": f"unifi-net:{CONSOLE}:{nid}", "console_id": CONSOLE, "console": "UDM-Pro kantoor",
           "site": "Default", "name": name, "vlan": 1, "management": "gateway", "enabled": True, "default": False,
           "isolated": False, "internet": True, "gateway": "192.168.1.1", "prefix": 24, "subnet": "192.168.1.0/24",
           "extra_subnets": [], "dhcp": "server", "dhcp_start": "192.168.1.100", "dhcp_stop": "192.168.1.200",
           "lease_seconds": 86400, "dns": [], "domain": "kantoor.lan", "relay_servers": [],
           "router_mac": "aabbcc000a01", "account": "Kantoor", "seen_at": 1_700_000_000, "org": ORG}
    net.update(extra)
    return net


def test_unifi_networks_are_documented(admin, monkeypatch):
    org_id = database.upsert_org("Netwerk BV", rmm_org_id="org-net")
    # Typed by hand before: the office network, written its own way.
    typed = admin.post(f"/api/orgs/{org_id}/items", json={"kind": "subnet", "name": "Kantoornetwerk", "fields": {
        "network": "192.168.1.1 /24", "purpose": "Kantoor", "dhcp_range": "oud",
        "reservations": [{"label": "printer", "value": "192.168.1.20"}]}}).json()
    state = {"networks": [_net("n-lan", "Default", default=True),
                          _net("n-guest", "Gasten", vlan=20, gateway="192.168.20.1", subnet="192.168.20.0/24",
                               dhcp_start="192.168.20.10", dhcp_stop="192.168.20.250", lease_seconds=28800,
                               dns=["1.1.1.1", "8.8.8.8"], domain="", isolated=True),
                          _net("n-cam", "Camera's", vlan=30, management="vlan", gateway="", subnet="", dhcp=None,
                               router_mac="")],
             "consoles": [{"id": CONSOLE, "name": "UDM-Pro kantoor", "read": True, "org": ORG}]}
    monkeypatch.setattr(rmm, "fetch_devices", lambda: [])
    monkeypatch.setattr(rmm, "fetch_network_devices", lambda: [_gateway()])
    monkeypatch.setattr(rmm, "fetch_networks", lambda: state)
    result = rmm.sync_devices()
    assert result["subnets"] == 3

    nets = {i["name"]: i for i in database.list_items(org_id, kind="subnet")}
    assert set(nets) == {"Kantoornetwerk", "Gasten", "Camera's"}            # the office network not doubled
    gateway = next(i for i in database.list_items(org_id, kind="network") if i["name"] == "UDM-Pro")

    lan = admin.get(f"/api/items/{typed['id']}").json()
    r = lan["rmm"]
    assert lan["source"] == "rmm" and r["network"] == "192.168.1.0/24" and r["vlan"] == "1"
    assert r["gateway"] == "192.168.1.1" and r["gateway_device"] == gateway["id"] and r["dhcp_server"] == gateway["id"]
    assert r["dhcp"] == "Aan" and r["dhcp_range"] == "192.168.1.100 – 192.168.1.200" and r["lease"] == "1 dag"
    assert r["dns"] == "192.168.1.1 (automatisch)" and r["domain"] == "kantoor.lan"
    # What UniFi does not know stays: what it is for, the fixed addresses.
    assert lan["fields"]["purpose"] == "Kantoor" and lan["fields"]["reservations"][0]["value"] == "192.168.1.20"
    assert "dhcp_range" not in lan["fields"] and "network" not in lan["fields"]

    guest = nets["Gasten"]["rmm"]
    assert guest["vlan"] == "20" and guest["lease"] == "8 uur" and guest["dns"] == "1.1.1.1, 8.8.8.8"
    assert "domain" not in guest["holds"] and guest["isolated"] is True
    assert nets["Gasten"]["fields"]["purpose"] == "Gasten"                   # a first guess from its name
    # A network that is only a VLAN: the VLAN from UniFi, the rest typed.
    cam = nets["Camera's"]
    assert cam["rmm"]["holds"] == ["vlan"] and cam["fields"]["purpose"] == "Camera's"
    assert admin.patch(f"/api/items/{cam['id']}", json={"fields": {
        "network": "192.168.30.0/24", "vlan": "99"}}).status_code == 200
    cam = database.get_item(cam["id"])
    assert cam["fields"]["network"] == "192.168.30.0/24" and "vlan" not in cam["fields"]

    # The gateway's page says which networks it routes.
    pointing = admin.get(f"/api/items/{gateway['id']}").json()["referred_by"]
    assert {p["name"] for p in pointing if p["field"] == "gateway_device"} == {"Kantoornetwerk", "Gasten"}

    # A changed DHCP range is history.
    state["networks"][0]["dhcp_stop"] = "192.168.1.250"
    rmm.sync_devices()
    told = [c for rev in admin.get(f"/api/items/{typed['id']}/revisions").json() for c in rev["changes"]
            if c["key"] == "dhcp_range"]
    assert told[0]["to"] == "192.168.1.100 – 192.168.1.250"

    # A console that could not be read this time says nothing; one read without
    # a network says it is gone; the page stays.
    state["consoles"][0]["read"] = False
    state["networks"] = []
    rmm.sync_devices()
    assert database.get_item(nets["Gasten"]["id"])["rmm_gone"] is False
    state["consoles"][0]["read"] = True
    state["networks"] = [_net("n-lan", "Default")]
    rmm.sync_devices()
    assert database.get_item(nets["Gasten"]["id"])["rmm_gone"] is True
    assert database.get_item(typed["id"])["rmm_gone"] is False
    # An RMM that does not read networks changes nothing.
    monkeypatch.setattr(rmm, "fetch_networks", lambda: None)
    assert rmm.sync_devices()["subnets"] is None
    assert database.get_item(typed["id"])["rmm_gone"] is False


def test_two_consoles_with_a_network_of_the_same_name(admin, monkeypatch):
    org_id = database.upsert_org("Twee Panden BV", rmm_org_id="org-two")
    here = {"id": "org-two", "name": "Twee Panden BV"}
    nets = [_net("a", "Default", org=here, console="UDM Venlo", key="unifi-net:c1:a", console_id="c1", router_mac=""),
            _net("b", "Default", org=here, console="UCG Tegelen", key="unifi-net:c2:b", console_id="c2",
                 subnet="192.168.2.0/24", gateway="192.168.2.1", router_mac="")]
    monkeypatch.setattr(rmm, "fetch_devices", lambda: [])
    monkeypatch.setattr(rmm, "fetch_network_devices", lambda: [])
    monkeypatch.setattr(rmm, "fetch_networks", lambda: {"networks": nets, "consoles": []})
    rmm.sync_devices()
    names = {i["name"] for i in database.list_items(org_id, kind="subnet")}
    assert names == {"Default (UDM Venlo)", "Default (UCG Tegelen)"}
