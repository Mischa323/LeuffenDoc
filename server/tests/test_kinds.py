"""Networks, VPNs, applications, licences and suppliers; and the tables on a
firewall -- what is forwarded to the inside, and the rules."""
import io
import zipfile


def test_the_new_kinds_are_built_in(admin, org, make):
    kinds = admin.get("/api/kinds").json()
    for name in ("subnet", "vpn", "application", "license", "vendor"):
        assert name in kinds, name

    vendor = make(admin, "vendor", "Exact", {"category": "Software", "account_number": "K-1234",
                                             "support_phone": "015 711 50 00"})
    server = make(admin, "computer", "SRV-APP", {"role": "Server"})
    app = make(admin, "application", "Exact Globe", {"category": "Boekhouding", "vendor": vendor["id"],
                                                     "runs_on": server["id"], "version": "2024.1"})
    assert app["fields"]["vendor"] == vendor["id"] and app["fields"]["runs_on"] == server["id"]
    licence = make(admin, "license", "Exact Globe licentie", {"product": "Exact Globe+", "seats": "5",
                                                              "expires_at": "2027-01-01", "auto_renew": True})
    assert licence["fields"]["seats"] == 5 and licence["fields"]["auto_renew"] is True

    # A licence key and a VPN's pre-shared key are kept in the vault.
    for item, field in ((licence, "license_key"), (make(admin, "vpn", "VPN Venlo", {"vpn_type": "Site-to-site"}), "psk")):
        assert admin.put(f"/api/items/{item['id']}/secret", params={"field": field},
                         json={"password": "Geheim-123-abc"}).status_code == 200
        assert "Geheim-123-abc" not in str(admin.get(f"/api/items/{item['id']}").json())
        assert admin.get(f"/api/items/{item['id']}/secret", params={"field": field}).json()["password"] == "Geheim-123-abc"

    subnet = make(admin, "subnet", "Kantoor LAN", {
        "network": "192.168.10.0/24", "vlan": "10", "dhcp": "Aan",
        "reservations": [{"label": "Printer", "value": "192.168.10.20"}]})
    assert subnet["fields"]["vlan"] == 10 and subnet["fields"]["reservations"][0]["value"] == "192.168.10.20"


def test_a_firewall_keeps_its_nat_and_rules_as_tables(admin, org, make):
    fw = make(admin, "network", "FW-NAT", {"role": "Firewall", "nat": [
        {"name": "Webserver", "proto": "TCP", "ext": "443", "to": "192.168.10.5", "to_port": "443"},
        {"name": "", "proto": "", "ext": ""},                                 # an empty row is no row
        {"name": "Mail", "proto": "TCP", "ext": "25", "to": "192.168.10.6", "bogus": "weg"},
    ]})
    assert fw["fields"]["nat"] == [
        {"name": "Webserver", "proto": "TCP", "ext": "443", "to": "192.168.10.5", "to_port": "443"},
        {"name": "Mail", "proto": "TCP", "ext": "25", "to": "192.168.10.6"}]

    # A change is history, as it reads.
    rules = [{"name": "RDP dicht", "action": "Blokkeren", "source": "WAN", "dest": "LAN", "service": "3389"}]
    assert admin.patch(f"/api/items/{fw['id']}", json={"fields": {"rules": rules}}).status_code == 200
    told = [c for r in admin.get(f"/api/items/{fw['id']}/revisions").json() for c in r["changes"]
            if c["key"] == "rules"]
    assert told and told[0]["to"] == "RDP dicht · Blokkeren · WAN · LAN · 3389"

    # Searchable by what is in it, and readable in the export.
    found = admin.get("/api/search", params={"q": "192.168.10.6", "org": org["id"]}).json()
    hits = found if isinstance(found, list) else found.get("results", [])
    assert any(h.get("id") == fw["id"] for h in hits)
    data = admin.post(f"/api/orgs/{org['id']}/export", json={"passwords": False}).content
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        page = z.read(next(n for n in z.namelist() if n.endswith("documentatie.html"))).decode()
    assert "Poortdoorverwijzingen (NAT)" in page and "Webserver · TCP · 443 · 192.168.10.5 · 443" in page
