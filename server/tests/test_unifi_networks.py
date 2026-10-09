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


def _switch(**extra):
    return {"id": "unifi:aabbcc000a02", "source": "unifi", "mac": "aa:bb:cc:00:0a:02", "name": "USW-Kelder",
            "model": "USW-24-PoE", "type": "switch", "state": "online", "firmware": "7.1", "ip": "192.168.1.2",
            "console": "UDM-Pro kantoor", "account": "Kantoor", "seen_at": 1_700_000_000, "org": ORG,
            "ports_vlans": True, "ports": [
                {"idx": 1, "up": True, "speed": 10000, "uplink": True, "name": "Uplink UDM", "native": "Default (1)",
                 "tagged": "all", "clients": [], "device_mac": ""},
                {"idx": 3, "up": True, "speed": 1000, "poe_on": True, "poe_watts": 4.2, "name": "Werkplek 3",
                 "native": "Default (1)", "tagged": ["Gasten (20)"], "device_mac": "",
                 "clients": [{"mac": "00:11:22:33:44:55", "name": "PC-012", "ip": "192.168.1.50"}]},
                {"idx": 5, "up": False, "speed": None, "name": "Port 5", "native": "Camera's (30)", "tagged": [],
                 "clients": [], "device_mac": ""},
                {"idx": 8, "up": True, "speed": 1000, "name": "Port 8", "native": "Default (1)", "tagged": "all",
                 "clients": [], "device_mac": "aabbcc000a03"},
                {"idx": 24, "up": False, "name": "Port 24", "native": "Default (1)", "tagged": "all", "clients": [],
                 "device_mac": ""}], **extra}


def _ap():
    return {"id": "unifi:aabbcc000a03", "source": "unifi", "mac": "aa:bb:cc:00:0a:03", "name": "AP Kantine",
            "model": "U6-Lite", "type": "ap", "state": "online", "firmware": "6.6", "ip": "192.168.1.30",
            "console": "UDM-Pro kantoor", "account": "Kantoor", "seen_at": 1_700_000_000, "org": ORG}


def _vpn(vid, name, **extra):
    vpn = {"id": vid, "key": f"unifi-vpn:{CONSOLE}:{vid}", "console_id": CONSOLE, "console": "UDM-Pro kantoor",
           "name": name, "kind": "site-to-site", "protocol": "ipsec", "enabled": True, "peer": "203.0.113.50",
           "local_ip": "198.51.100.7", "local_nets": [], "remote_nets": ["10.50.0.0/16"], "client_pool": "",
           "port": None, "settings": "IKEv2 · IKE AES256/SHA256, DH 14", "interface": "wan", "detail": True,
           "router_mac": "aabbcc000a01", "account": "Kantoor", "seen_at": 1_700_000_000, "org": ORG}
    vpn.update(extra)
    return vpn


def test_unifi_ports_and_vpns(admin, monkeypatch):
    org_id = database.upsert_org("Netwerk BV", rmm_org_id="org-net")
    # A machine documented here, with the adapter UniFi sees on port 3.
    pc = admin.post(f"/api/orgs/{org_id}/items", json={"kind": "computer", "name": "PC-012", "fields": {}}).json()
    database.add_adapter(pc["id"], {"name": "Ethernet", "mac": "00-11-22-33-44-55"})
    # A VPN typed before, with the same other end.
    typed = admin.post(f"/api/orgs/{org_id}/items", json={"kind": "vpn", "name": "VPN naar het DC", "fields": {
        "peer": "203.0.113.50", "remote_nets": "oud", "users": "Iedereen"}}).json()
    state = {"networks": [], "consoles": [{"id": CONSOLE, "name": "UDM-Pro kantoor", "read": True, "vpn_read": True,
                                           "org": ORG}],
             "vpns": [_vpn("v-s2s", "Datacenter"),
                      _vpn("v-wg", "Thuiswerkers", kind="remote-access", protocol="wireguard", peer="",
                           remote_nets=[], client_pool="192.168.3.0/24", port=51820, settings=""),
                      _vpn("v-uid", "Kantoor UID", kind="remote-access", protocol="uid", peer="", remote_nets=[],
                           settings="", detail=False, interface="")]}
    monkeypatch.setattr(rmm, "fetch_devices", lambda: [])
    monkeypatch.setattr(rmm, "fetch_network_devices", lambda: [_gateway(), _switch(), _ap()])
    monkeypatch.setattr(rmm, "fetch_networks", lambda: state)
    assert rmm.sync_devices()["vpns"] == 3

    switch = next(i for i in database.list_items(org_id, kind="network") if i["name"] == "USW-Kelder")
    page = admin.get(f"/api/items/{switch['id']}").json()
    # The port count is UniFi's; every port is listed, with what UniFi sees.
    assert page["rmm"]["port_count"] == 24 and len(page["ports"]) == 24
    ports = {p["number"]: p for p in page["ports"]}
    assert ports[3]["live"]["up"] and ports[3]["live"]["speed"] == 1000 and ports[3]["live"]["poe_watts"] == 4.2
    assert ports[3]["live"]["native"] == "Default (1)" and ports[3]["live"]["tagged"] == ["Gasten (20)"]
    assert ports[5]["live"]["up"] is False and ports[5]["live"]["native"] == "Camera's (30)"
    assert "live" not in ports[2]                                             # UniFi said nothing of it
    # What UniFi sees plugged in, documented here, is patched in.
    assert ports[3]["adapter"]["item_id"] == pc["id"]
    ap = next(i for i in database.list_items(org_id, kind="network") if i["name"] == "AP Kantine")
    assert ports[8]["adapter"]["item_id"] == ap["id"] and ports[8]["live"]["device"]["id"] == ap["id"]
    told = [c["to"] for r in admin.get(f"/api/items/{pc['id']}/revisions").json() for c in r["changes"]
            if c["key"] == "port"]
    assert told == ["USW-Kelder poort 3 (gezien door UniFi)"]
    # ... but never over what somebody patched by hand.
    admin.patch(f"/api/items/{switch['id']}/ports/3", json={"adapter_id": None})
    other = admin.post(f"/api/orgs/{org_id}/items", json={"kind": "computer", "name": "Printer", "fields": {}}).json()
    adapter = database.add_adapter(other["id"], {"name": "LAN", "mac": "aa:aa:aa:aa:aa:01"})
    database.set_port(switch["id"], 3, adapter_id=adapter["id"], by="admin@example.test")
    rmm.sync_devices()
    assert database.ports_of(switch["id"], 24)[2]["adapter"]["item_id"] == other["id"]

    vpns = {i["name"]: i for i in database.list_items(org_id, kind="vpn")}
    assert set(vpns) == {"VPN naar het DC", "Thuiswerkers", "Kantoor UID"}       # the typed one taken over
    gateway = next(i for i in database.list_items(org_id, kind="network") if i["name"] == "UDM-Pro")
    dc = admin.get(f"/api/items/{typed['id']}").json()
    r = dc["rmm"]
    assert r["vpn_type"] == "Site-to-site" and r["protocol"] == "IPsec" and r["device"] == gateway["id"]
    assert r["remote_nets"] == "10.50.0.0/16" and r["settings"].startswith("IKEv2")
    assert dc["fields"]["users"] == "Iedereen" and "remote_nets" not in dc["fields"]
    wg = vpns["Thuiswerkers"]["rmm"]
    assert wg["vpn_type"] == "Thuiswerkers (client)" and wg["protocol"] == "WireGuard"
    assert wg["client_pool"] == "192.168.3.0/24" and wg["port"] == "51820"
    uid = vpns["Kantoor UID"]["rmm"]
    assert uid["protocol"] == "UniFi Identity" and uid["detail"] is False and "peer" not in uid["holds"]
    # Its key is typed here, encrypted, and never comes from UniFi.
    assert "psk" not in r["holds"]

    # A console whose VPNs could not be read says nothing; one read without it, gone.
    state["consoles"][0]["vpn_read"] = False
    state["vpns"] = []
    rmm.sync_devices()
    assert database.get_item(vpns["Thuiswerkers"]["id"])["rmm_gone"] is False
    state["consoles"][0]["vpn_read"] = True
    state["vpns"] = [_vpn("v-s2s", "Datacenter")]
    rmm.sync_devices()
    assert database.get_item(vpns["Thuiswerkers"]["id"])["rmm_gone"] is True
    assert database.get_item(typed["id"])["rmm_gone"] is False
