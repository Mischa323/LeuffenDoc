"""A copy is an ordinary new item; the log says what it was copied from."""
from app import database


def test_the_log_names_the_original(admin, org, make):
    original = make(admin, "network", "SW-ORIG", {"role": "Switch", "ports": 24})
    copy = admin.post(f"/api/orgs/{org['id']}/items", json={
        "kind": "network", "name": "SW-KOPIE", "fields": {"role": "Switch", "ports": 24},
        "copy_of": original["id"]})
    assert copy.status_code == 200, copy.text
    assert copy.json()["fields"]["ports"] == 24
    line = next(e for e in database.list_audit(org["id"]) if e["target"] == "SW-KOPIE")
    assert line["action"] == "item.create" and "kopie van SW-ORIG" in line["detail"]


def test_a_copy_of_something_elsewhere_is_not_named(admin, org, make):
    elsewhere = database.upsert_org("Ergens Anders BV")
    secret_name = database.create_item(elsewhere, "network", "SW-GEHEIM", {}, by=None)
    copy = admin.post(f"/api/orgs/{org['id']}/items", json={
        "kind": "network", "name": "SW-NIET-GENOEMD", "fields": {}, "copy_of": secret_name["id"]})
    assert copy.status_code == 200
    line = next(e for e in database.list_audit(org["id"]) if e["target"] == "SW-NIET-GENOEMD")
    assert "SW-GEHEIM" not in (line["detail"] or "")
