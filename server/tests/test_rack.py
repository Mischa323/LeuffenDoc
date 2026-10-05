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
    assert hangs == [{"rack_id": cabinet["id"], "rack_name": "Kast kelder", "org_id": org["id"], "at": 2, "height": 2}]

    # The history says the layout changed.
    assert any(c["key"] == "kast" for r in admin.get(f"/api/items/{cabinet['id']}/revisions").json()
               for c in r["changes"])


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
