"""Laying out a type: blocks, which fields go where, fields added and hidden --
for built-in kinds as well as for types made here."""
import datetime

from app import schema


def groups_of(client, kind):
    spec = client.get("/api/kinds").json()[kind]
    return [(g["label"], g.get("width", "full"), [f["key"] for f in g["fields"]]) for g in spec["groups"]]


def field(client, kind, key):
    spec = client.get("/api/kinds").json()[kind]
    return next(f for g in spec["groups"] for f in g["fields"] if f["key"] == key)


def blocks(client, kind):
    """The layout as the editor would send it back, unchanged."""
    spec = next(t for t in client.get("/api/types").json()["built_in"] if t["id"] == kind)
    return [{"key": g["key"], "label": g["label"], "width": g.get("width", "full"),
             "fields": [dict(f) for f in g["fields"]]} for g in spec["groups"]]


def test_a_built_in_kind_is_laid_out_anew(admin, org, make):
    layout = blocks(admin, "computer")
    wat, hardware, beheer = layout
    # Serial number up front, next to what it is.
    serial = next(f for f in hardware["fields"] if f["key"] == "serial")
    hardware["fields"].remove(serial)
    wat["fields"].insert(1, serial)
    # Beheer becomes Onderhoud and goes first; "Aangeschaft op" is not used here.
    beheer["label"] = "Onderhoud"
    for f in beheer["fields"]:
        if f["key"] == "purchased_at":
            f["hidden"] = True
        if f["key"] == "installed_by":
            f["label"] = "Opgeleverd door"
    # A block of its own, half wide, with two fields that were never in the code.
    licences = {"label": "Licenties", "width": "half", "fields": [
        {"label": "Licentiecode", "type": "text"},
        {"label": "BIOS-wachtwoord", "type": "secret"},
    ]}
    body = {"groups": [beheer, wat, hardware, licences],
            "columns": ["role", "serial", "Licentiecode"]}
    response = admin.put("/api/types/computer/layout", json=body)
    assert response.status_code == 200, response.text

    got = groups_of(admin, "computer")
    assert [g[0] for g in got] == ["Onderhoud", "Wat het is", "Hardware", "Licenties"]
    assert got[1][2][:2] == ["role", "serial"]
    assert "serial" not in got[2][2]
    assert got[3][1] == "half" and got[3][2] == ["x_licentiecode", "x_bios_wachtwoord"]
    assert field(admin, "computer", "purchased_at")["hidden"] is True
    assert field(admin, "computer", "installed_by")["label"] == "Opgeleverd door"
    assert admin.get("/api/kinds").json()["computer"]["columns"] == ["role", "serial", "x_licentiecode"]
    assert schema.secret_fields_of("computer") == ["x_bios_wachtwoord"]

    # The new fields work like any other; a hidden one keeps what it held.
    item = make(admin, "computer", "WS-LAYOUT", {"role": "Desktop", "x_licentiecode": "ABC-123",
                                                  "purchased_at": "2024-01-02"})
    assert item["fields"]["x_licentiecode"] == "ABC-123"
    saved = admin.patch(f"/api/items/{item['id']}", json={"fields": {"x_licentiecode": "DEF-456"}}).json()
    assert saved["fields"]["purchased_at"] == "2024-01-02"
    assert admin.put(f"/api/items/{item['id']}/secret?field=x_bios_wachtwoord",
                     json={"password": "Bios!2024"}).status_code == 200
    assert admin.get(f"/api/items/{item['id']}/secret?field=x_bios_wachtwoord").json()["password"] == "Bios!2024"


def test_built_in_fields_stay_what_they_are(admin):
    layout = blocks(admin, "computer")
    hardware = next(g for g in layout if g["key"] == "hardware")
    hardware["fields"] = [f for f in hardware["fields"] if f["key"] != "cpu"]     # "removed"
    wat = next(g for g in layout if g["key"] == "wat")
    for f in wat["fields"]:
        if f["key"] == "role":
            f["hidden"] = True                     # the type of a configuration: always shown
            f["type"] = "text"                     # and not something else
    assert admin.put("/api/types/computer/layout", json={"groups": layout}).status_code == 200
    assert "cpu" in [k for _, _, keys in groups_of(admin, "computer") for k in keys]
    role = field(admin, "computer", "role")
    assert not role.get("hidden") and role["type"] == "select"


def test_a_hidden_date_does_not_warn(admin, org, make):
    soon = (datetime.date.today() + datetime.timedelta(days=5)).isoformat()
    make(admin, "network", "SW-WARN", {"role": "Switch", "warranty_until": soon})
    warns = lambda: [e for e in admin.get("/api/expiring").json()["items"] if e["item_name"] == "SW-WARN"]
    assert warns()
    layout = blocks(admin, "network")
    for g in layout:
        for f in g["fields"]:
            if f["key"] == "warranty_until":
                f["hidden"] = True
    assert admin.put("/api/types/network/layout", json={"groups": layout}).status_code == 200
    assert not warns()
    assert admin.delete("/api/types/network/layout").status_code == 200
    assert warns()


def test_removing_what_was_filled_in_is_said_first(admin, org, make):
    layout = blocks(admin, "printer")
    layout.append({"label": "Contract", "fields": [{"label": "Leasenummer", "type": "text"}]})
    assert admin.put("/api/types/printer/layout", json={"groups": layout}).status_code == 200
    make(admin, "printer", "PR-LEASE", {"role": "Printer", "x_leasenummer": "L-77"})

    without = blocks(admin, "printer")
    without = [g for g in without if g["label"] != "Contract"]
    refused = admin.put("/api/types/printer/layout", json={"groups": without})
    assert refused.status_code == 409 and "Leasenummer" in refused.json()["detail"]
    assert admin.delete("/api/types/printer/layout").status_code == 409
    assert admin.delete("/api/types/printer/layout?confirm=true").status_code == 200
    assert "x_leasenummer" not in [k for _, _, keys in groups_of(admin, "printer") for k in keys]


def test_only_administrators_lay_out_types(member, viewer, admin):
    layout = blocks(admin, "location")
    for client in (member, viewer):
        assert client.put("/api/types/location/layout", json={"groups": layout}).status_code == 403
        assert client.delete("/api/types/location/layout").status_code == 403
    assert admin.put("/api/types/nonsense/layout", json={"groups": layout}).status_code == 404


def test_a_type_made_here_has_blocks_too(admin):
    made = admin.post("/api/types", json={
        "label": "Firewallregel", "plural": "Firewallregels", "groups": [
            {"label": "Regel", "fields": [{"label": "Bron", "type": "text"},
                                          {"label": "Doel", "type": "text"}]},
            {"label": "Waarom", "width": "half", "fields": [{"label": "Aangevraagd door", "type": "text"}]},
        ], "columns": ["Bron"]})
    assert made.status_code == 200, made.text
    type_id = made.json()["id"]
    assert groups_of(admin, type_id) == [("Regel", "full", ["bron", "doel"]),
                                         ("Waarom", "half", ["aangevraagd_door"])]
    # Moved across, and the old way of saving (one plain list) still works.
    spec = next(t for t in admin.get("/api/types").json()["custom"] if t["id"] == type_id)
    regel, waarom = spec["groups"]
    waarom["fields"].append(regel["fields"].pop())
    assert admin.patch(f"/api/types/{type_id}", json={**spec, "groups": [regel, waarom]}).status_code == 200
    assert groups_of(admin, type_id)[1][2] == ["aangevraagd_door", "doel"]
    flat = admin.patch(f"/api/types/{type_id}", json={"label": "Firewallregel", "fields": [
        {"key": "bron", "label": "Bron", "type": "text"}, {"key": "doel", "label": "Doel", "type": "text"},
        {"key": "aangevraagd_door", "label": "Aangevraagd door", "type": "text"}]})
    assert flat.status_code == 200
    assert groups_of(admin, type_id) == [("Gegevens", "full", ["bron", "doel", "aangevraagd_door"])]
