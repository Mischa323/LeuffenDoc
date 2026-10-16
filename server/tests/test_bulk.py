"""Several things at once: archived, put back, moved to another customer, or
deleted -- each checked on its own, and what could not be done named."""
from app import database


def _new(client, org_id, kind, name, fields=None):
    r = client.post(f"/api/orgs/{org_id}/items", json={"kind": kind, "name": name, "fields": fields or {}})
    assert r.status_code == 200, r.text
    return r.json()


def _bulk(client, org_id, action, ids, **extra):
    return client.post(f"/api/orgs/{org_id}/items/bulk", json={"action": action, "ids": ids, **extra})


def test_moving_to_another_customer_takes_what_is_its_own(admin):
    a = database.upsert_org("Verhuizer BV")
    b = database.upsert_org("Nieuw Thuis BV")
    office = _new(admin, a, "location", "Kantoor Venlo")
    pc = _new(admin, a, "computer", "WS-VERHUIS", {"role": "Desktop", "location": office["id"]})
    other = _new(admin, a, "computer", "WS-BLIJFT", {"role": "Desktop"})
    switch = _new(admin, a, "network", "SW-BLIJFT", {"role": "Switch", "ports": 8})
    pw = _new(admin, a, "password", "Admin WS-VERHUIS", {"device": pc["id"]})
    assert admin.put(f"/api/items/{pw['id']}/secret", json={"password": "Gaat-Mee-1"}).status_code == 200
    assert admin.post(f"/api/items/{pc['id']}/notes", json={"body": "Gaat naar het nieuwe pand"}).status_code == 200
    assert admin.post(f"/api/items/{pc['id']}/relations", json={"item_id": other["id"]}).status_code == 200
    adapter = admin.post(f"/api/items/{pc['id']}/adapters", json={"name": "LAN", "mac": "aa:bb:cc:dd:ee:01"}).json()
    assert admin.post(f"/api/adapters/{adapter['id']}/connect", json={"switch_id": switch["id"], "port": 2}).status_code == 200
    rack = _new(admin, a, "rack", "Kast", {"units": 12})
    assert admin.put(f"/api/items/{rack['id']}/rack", json={"slots": [
        {"kind": "item", "item": pc["id"], "at": 2, "height": 1}]}).status_code == 200

    # The machine and its password go together; the location and the switch stay.
    r = _bulk(admin, a, "move", [pc["id"], pw["id"]], to_org=b)
    assert r.status_code == 200, r.text
    assert r.json()["done"] == 2 and r.json()["to"]["name"] == "Nieuw Thuis BV"
    moved = admin.get(f"/api/items/{pc['id']}").json()
    assert moved["org_id"] == b and "location" not in moved["fields"]          # Kantoor Venlo stayed
    assert admin.get(f"/api/items/{pw['id']}").json()["fields"]["device"] == pc["id"]   # moved together
    assert admin.get(f"/api/items/{pw['id']}/secret").json()["password"] == "Gaat-Mee-1"
    assert admin.get(f"/api/items/{pc['id']}/notes").json()[0]["body"] == "Gaat naar het nieuwe pand"
    assert not moved["relations"]                                              # the link with WS-BLIJFT
    assert database.ports_of(switch["id"], 8)[1]["adapter"] is None           # the cable in SW-BLIJFT
    assert database.rack_slots(rack["id"]) == []                              # and its place in the cabinet
    told = admin.get(f"/api/items/{pc['id']}/revisions").json()[0]["changes"]
    assert told[0]["from"] == "Verhuizer BV" and told[0]["to"] == "Nieuw Thuis BV"
    assert "Kantoor Venlo" in told[1]["said"] and "WS-BLIJFT" in told[1]["said"] and "SW-BLIJFT poort 2" in told[1]["said"]

    # Not to a customer one may not change, not to the same one.
    assert _bulk(admin, a, "move", [other["id"]], to_org=a).status_code == 400
    assert _bulk(admin, a, "move", [other["id"]], to_org="bestaat-niet").status_code == 404


def test_what_points_from_elsewhere_lets_go_and_says_so(admin):
    a = database.upsert_org("Wijzer BV")
    b = database.upsert_org("Elders BV")
    office = _new(admin, a, "location", "Hoofdkantoor")
    pc = _new(admin, a, "computer", "WS-HIER", {"location": office["id"]})
    assert _bulk(admin, a, "move", [office["id"]], to_org=b).json()["done"] == 1
    assert "location" not in database.get_item(pc["id"])["fields"]
    said = admin.get(f"/api/items/{pc['id']}/revisions").json()[0]["changes"][0]["said"]
    assert "Hoofdkantoor" in said and "Elders BV" in said


def test_archive_restore_and_delete_several(admin, member, org, make):
    one = make(admin, "computer", "BULK-1")
    two = make(admin, "computer", "BULK-2")
    r = _bulk(admin, org["id"], "archive", [one["id"], two["id"]]).json()
    assert r["done"] == 2 and database.get_item(one["id"])["archived"] and database.get_item(two["id"])["archived"]
    assert _bulk(admin, org["id"], "restore", [one["id"]]).json()["done"] == 1
    assert not database.get_item(one["id"])["archived"]

    # Deleting is an administrator's.
    assert _bulk(member, org["id"], "delete", [one["id"]]).status_code == 403
    # What something else still points at stays -- unless that goes too.
    pointer = make(admin, "password", "Wijst naar BULK-1", {"device": one["id"]})
    r = _bulk(admin, org["id"], "delete", [one["id"], two["id"]]).json()
    assert r["done"] == 1 and r["failed"][0]["name"] == "BULK-1" and "Wijst naar BULK-1" in r["failed"][0]["reason"]
    assert database.get_item(two["id"]) is None and database.get_item(one["id"])
    r = _bulk(admin, org["id"], "delete", [one["id"], pointer["id"]]).json()
    assert r["done"] == 2 and not r["failed"]

    # Something from another customer, or that does not exist, is named and skipped.
    other = database.upsert_org("Ander BV")
    foreign = _new(admin, other, "computer", "VAN-EEN-ANDER")
    r = _bulk(admin, org["id"], "archive", [foreign["id"]]).json()
    assert r["done"] == 0 and r["failed"][0]["reason"].startswith("Bestaat niet")
    assert not database.get_item(foreign["id"])["archived"]


def test_what_the_rmm_keeps_is_neither_deleted_nor_moved_here(admin):
    a = database.upsert_org("Gesynct BV")
    b = database.upsert_org("Doel BV")
    item = _new(admin, a, "computer", "UIT-DE-RMM")
    with database.write() as conn:
        conn.execute("UPDATE items SET source='rmm', rmm_device_id='dev-bulk', rmm_json=? WHERE id=?",
                     ('{"cpu": "i7", "os": "Windows 11"}', item["id"]))
    r = _bulk(admin, a, "delete", [item["id"]]).json()
    assert r["done"] == 0 and "volgende synchronisatie" in r["failed"][0]["reason"]
    assert admin.delete(f"/api/items/{item['id']}").status_code == 409
    r = _bulk(admin, a, "move", [item["id"]], to_org=b).json()
    assert r["done"] == 0 and "verplaats het daar" in r["failed"][0]["reason"]
    # Once it has left the RMM it is documentation like any other: it moves,
    # and what the RMM reported stays on it, typed.
    database.mark_rmm_gone(item["id"], True)
    assert _bulk(admin, a, "move", [item["id"]], to_org=b).json()["done"] == 1
    moved = database.get_item(item["id"])
    assert moved["org_id"] == b and moved["source"] == "manual" and moved["fields"]["cpu"] == "i7"
