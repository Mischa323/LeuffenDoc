"""A patch cabinet: what hangs in it, where, and what the server refuses."""
from app import database


def test_a_cabinet_holds_equipment_and_passive_parts(admin, viewer, org, make):
    cabinet = make(admin, "rack", "Kast kelder", {"units": 12, "placement": "Kelder"})
    switch = make(admin, "network", "SW-RACK", {"role": "Switch", "ports": 24})
    server = make(admin, "computer", "SRV-RACK", {"role": "Server"})
    pc = make(admin, "computer", "WS-RACK", {"role": "Desktop"})
    adapter = admin.post(f"/api/items/{pc['id']}/adapters", json={"name": "Ethernet", "mac": "aa:bb:cc:00:00:01"}).json()
    assert admin.post(f"/api/adapters/{adapter['id']}/connect",
                      json={"switch_id": switch["id"], "port": 3}).status_code == 200

    url = f"/api/items/{cabinet['id']}/rack"
    empty = admin.get(url).json()
    assert empty["units"] == 12 and empty["slots"] == [] and "patch" in empty["passive"]

    slots = [{"kind": "patch", "at": 12, "height": 1, "ports": 24},
             {"kind": "item", "item": switch["id"], "at": 11, "height": 1},
             {"kind": "cable", "at": 10, "height": 1},
             {"kind": "item", "item": server["id"], "at": 2, "height": 2},
             {"kind": "ups", "at": 0 + 1 + 3, "height": 2, "label": "APC 1500"}]
    saved = admin.put(url, json={"slots": slots})
    assert saved.status_code == 200, saved.text
    got = saved.json()
    assert [s["at"] for s in got["slots"]] == [12, 11, 10, 4, 2]          # top down
    sw = got["devices"][switch["id"]]
    port3 = next(p for p in sw["ports"] if p["number"] == 3)
    assert port3["used"] and "WS-RACK" in port3["who"]
    assert not next(p for p in sw["ports"] if p["number"] == 4)["used"]
    assert viewer.get(url).status_code == 200
    assert viewer.put(url, json={"slots": []}).status_code == 403

    # Where a machine hangs, on its own page.
    hangs = admin.get(f"/api/items/{server['id']}/racks").json()
    assert hangs == [{"rack_id": cabinet["id"], "rack_name": "Kast kelder", "org_id": org["id"],
                      "at": 2, "height": 2, "on": ""}]

    # The history says what changed -- and a run of changes is one line.
    moved = [dict(s, at=9) if s.get("item") == switch["id"] else s for s in got["slots"]]
    assert admin.put(url, json={"slots": moved}).status_code == 200
    lines = [c for r in admin.get(f"/api/items/{cabinet['id']}/revisions").json()
             for c in r["changes"] if c["key"] == "kast"]
    assert len(lines) == 1, lines
    assert "SW-RACK op U11 geplaatst" in lines[0]["said"] and "SW-RACK U11 → U9" in lines[0]["said"]
    assert "APC 1500 op U4–U5 geplaatst" in lines[0]["said"]


def test_what_the_server_refuses(admin, org, make):
    cabinet = make(admin, "rack", "Wandkast", {"units": 6})
    nas = make(admin, "computer", "NAS-RACK", {"role": "NAS"})
    url = f"/api/items/{cabinet['id']}/rack"
    overlap = admin.put(url, json={"slots": [{"kind": "blank", "at": 2, "height": 2},
                                             {"kind": "shelf", "at": 3, "height": 2}]})
    assert overlap.status_code == 400 and "U3" in overlap.json()["detail"]
    sticks_out = admin.put(url, json={"slots": [{"kind": "ups", "at": 6, "height": 2}]})
    assert sticks_out.status_code == 400 and "6U" in sticks_out.json()["detail"]
    twice = admin.put(url, json={"slots": [{"kind": "item", "item": nas["id"], "at": 1, "height": 1},
                                           {"kind": "item", "item": nas["id"], "at": 3, "height": 1}]})
    assert twice.status_code == 400 and "al in deze kast" in twice.json()["detail"]
    elsewhere = database.create_item(database.upsert_org("Andere Kast BV"), "computer", "VREEMD", {}, by=None)
    foreign = admin.put(url, json={"slots": [{"kind": "item", "item": elsewhere["id"], "at": 1, "height": 1}]})
    assert foreign.status_code == 400
    assert admin.put(url, json={"slots": [{"kind": "rocket", "at": 1, "height": 1}]}).status_code == 400
    not_a_rack = admin.get(f"/api/items/{nas['id']}/rack")
    assert not_a_rack.status_code == 400

    # Deleting the cabinet takes its layout with it; the NAS stays.
    assert admin.put(url, json={"slots": [{"kind": "item", "item": nas["id"], "at": 1, "height": 2}]}).status_code == 200
    assert admin.delete(f"/api/items/{cabinet['id']}").status_code == 200
    assert database.rack_slots(cabinet["id"]) == [] and admin.get(f"/api/items/{nas['id']}/racks").json() == []


def test_what_is_not_19_inch_stands_on_a_shelf_or_the_bottom(admin, org, make):
    cabinet = make(admin, "rack", "Meterkast", {"units": 12})
    modem = make(admin, "network", "Ziggo modem", {"role": "Modem"})
    nas = make(admin, "computer", "NAS-STAND", {"role": "NAS"})
    switch = make(admin, "network", "SW-STAND", {"role": "Switch"})
    vm = make(admin, "computer", "VM-STAND", {"role": "Virtuele machine"})
    url = f"/api/items/{cabinet['id']}/rack"

    # What it is, until somebody says: a modem and a NAS stand, a switch hangs.
    found = {c["name"]: c for c in admin.get(url).json()["candidates"]}
    assert not found["Ziggo modem"]["rack"] and found["Ziggo modem"]["guessed"]
    assert not found["NAS-STAND"]["rack"]
    assert found["SW-STAND"]["rack"] and found["SW-STAND"]["units"] == 1
    assert "VM-STAND" not in found and "Meterkast" not in found
    # Said on its page, it is what was said.
    admin.patch(f"/api/items/{nas['id']}", json={"fields": {"rackmount": "19 inch (U)", "rack_units": 2}})
    nas_now = next(c for c in admin.get(url).json()["candidates"] if c["id"] == nas["id"])
    assert nas_now["rack"] and nas_now["units"] == 2 and not nas_now["guessed"]

    slots = [{"kind": "floor", "at": 1, "height": 4,
              "items": [{"item": modem["id"]}, {"kind": "ups_box", "label": "APC Back-UPS"}]},
             {"kind": "shelf", "at": 6, "height": 2, "items": [{"item": switch["id"]}]}]
    saved = admin.put(url, json={"slots": slots})
    assert saved.status_code == 200, saved.text
    got = saved.json()
    floor = next(s for s in got["slots"] if s["kind"] == "floor")
    assert [t.get("item") or t.get("label") for t in floor["items"]] == [modem["id"], "APC Back-UPS"]
    assert modem["id"] in got["devices"] and modem["id"] not in {c["id"] for c in got["candidates"]}
    assert admin.get(f"/api/items/{modem['id']}/racks").json()[0]["on"] == "bodem"
    assert admin.get(f"/api/items/{switch['id']}/racks").json()[0]["on"] == "plank"

    # The bottom is the bottom; nothing stands in two places.
    high = admin.put(url, json={"slots": [{"kind": "floor", "at": 3, "height": 2, "items": []}]})
    assert high.status_code == 400 and "onderin" in high.json()["detail"]
    twice = admin.put(url, json={"slots": [{"kind": "item", "item": switch["id"], "at": 10, "height": 1},
                                           {"kind": "shelf", "at": 6, "height": 2, "items": [{"item": switch["id"]}]}]})
    assert twice.status_code == 400 and "al in deze kast" in twice.json()["detail"]
    odd = admin.put(url, json={"slots": [{"kind": "shelf", "at": 6, "height": 2, "items": [{"kind": "rocket"}]}]})
    assert odd.status_code == 400

    # The export says what stands where.
    import io as _io, zipfile
    data = admin.post(f"/api/orgs/{org['id']}/export", json={"passwords": False}).content
    with zipfile.ZipFile(_io.BytesIO(data)) as z:
        page = z.read(next(n for n in z.namelist() if n.endswith("documentatie.html"))).decode()
    assert "Bodem, met Ziggo modem, APC Back-UPS" in page
