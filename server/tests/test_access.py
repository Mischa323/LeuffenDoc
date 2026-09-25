"""Who may see, change and read what."""
import json

from app import database


def test_a_viewer_reads_but_cannot_read_passwords(admin, viewer, make):
    pw = make(admin, "password", "Router beheer", password="Router-Geheim-1")
    assert viewer.get(f"/api/items/{pw['id']}").status_code == 200
    assert viewer.get(f"/api/items/{pw['id']}/secret").status_code == 403


def test_a_viewer_cannot_change_anything(admin, viewer, make):
    place = make(admin, "location", "Magazijn")
    assert viewer.patch(f"/api/items/{place['id']}", json={"fields": {"city": "Elders"}}).status_code == 403


def test_a_member_reads_a_password_and_it_is_logged(admin, member, make):
    pw = make(admin, "password", "Wifi kantoor", password="Wifi-Kantoor-7")
    response = member.get(f"/api/items/{pw['id']}/secret")
    assert response.status_code == 200 and response.json()["password"] == "Wifi-Kantoor-7"
    log = admin.get("/api/audit").json()
    assert any(e["action"] == "secret.read" and e["user_email"] == "lid@example.test"
               and e["target"] == "Wifi kantoor" for e in log)


def test_someone_without_the_customer_does_not_see_it_exists(org, outsider):
    assert outsider.get(f"/api/orgs/{org['id']}/items").status_code == 404
    assert not any(o["id"] == org["id"] for o in outsider.get("/api/orgs").json())


def test_something_shut_off_disappears_for_everyone_else(admin, member, org, make):
    pw = make(admin, "password", "Alleen voor de beheerder", password="Afgeschermd-1")
    assert admin.put(f"/api/items/{pw['id']}/access",
                     json={"people": ["admin@example.test"]}).status_code == 200
    assert member.get(f"/api/items/{pw['id']}").status_code == 404
    listed = member.get(f"/api/orgs/{org['id']}/items?kind=password").json()
    assert all(i["id"] != pw["id"] for i in listed)
    assert "Alleen voor de beheerder" not in json.dumps(member.get("/api/search?q=beheerder").json())
    assert admin.get(f"/api/items/{pw['id']}").status_code == 200


def test_the_history_says_a_password_changed_never_what_it_was(admin, make):
    pw = make(admin, "password", "Historie", password="Eerste-Waarde-1")
    admin.put(f"/api/items/{pw['id']}/secret", json={"password": "Tweede-Waarde-2"})
    history = json.dumps(admin.get(f"/api/items/{pw['id']}/revisions").json())
    assert "Eerste-Waarde" not in history and "Tweede-Waarde" not in history
    assert "gewijzigd" in history


def test_a_field_can_be_emptied(admin, make):
    place = make(admin, "location", "Filiaal", {"city": "Zwolle"})
    admin.patch(f"/api/items/{place['id']}", json={"fields": {"city": ""}})
    assert "city" not in admin.get(f"/api/items/{place['id']}").json()["fields"]


def test_a_sync_that_finds_nothing_new_changes_nothing(admin, org):
    item = database.create_item(org["id"], "computer", "WS-ONVERANDERD", {}, by=None,
                                source="rmm", rmm_device_id="dev-onveranderd", rmm={"cpu": "X"})
    before = database.get_item(item["id"])["updated_at"]
    database.update_item(item["id"], rmm={"cpu": "X"}, rmm_keys=["cpu"], source="rmm")
    assert database.get_item(item["id"])["updated_at"] == before
    database.update_item(item["id"], rmm={"cpu": "Y"}, rmm_keys=["cpu"], source="rmm")
    assert database.get_item(item["id"])["updated_at"] > before
