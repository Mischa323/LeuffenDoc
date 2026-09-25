"""Share links: for someone without an account, a few looks, and never more."""
from urllib.parse import urlparse

from fastapi.testclient import TestClient

from app import database
from app.main import app


def _link(client, item_id, views=1, hours=24):
    response = client.post(f"/api/items/{item_id}/shares", json={"hours": hours, "views": views})
    assert response.status_code == 200, response.text
    return urlparse(response.json()["url"]).path, response.json()["share"]


def test_a_link_hands_the_password_over_once(admin, make):
    pw = make(admin, "password", "Leverancier", {"username": "lev"}, password="Voor-Leverancier-1")
    path, share = _link(admin, pw["id"])
    stranger = TestClient(app)
    page = stranger.get(path)
    assert page.status_code == 200 and "Voor-Leverancier-1" not in page.text
    assert page.headers["cache-control"] == "no-store"
    opened = stranger.post(path)
    assert opened.status_code == 200 and opened.json()["password"] == "Voor-Leverancier-1"
    assert opened.json()["looks_left"] == 0
    assert stranger.post(path).status_code == 410
    # The copy it carried goes once the link can no longer be opened.
    assert database.get_share(share["id"])["sealed_json"] == ""


def test_opening_the_page_uses_up_nothing(admin, make):
    pw = make(admin, "password", "Voorvertoning", password="Niet-Opgebruikt-1")
    path, share = _link(admin, pw["id"])
    for _ in range(3):
        TestClient(app).get(path)
    assert database.get_share(share["id"])["views"] == 0


def test_changing_the_password_closes_its_links(admin, make):
    pw = make(admin, "password", "Gelekt", password="Oud-Gelekt-1")
    path, _ = _link(admin, pw["id"], views=3)
    admin.put(f"/api/items/{pw['id']}/secret", json={"password": "Nieuw-Veilig-2"})
    closed = TestClient(app).post(path)
    assert closed.status_code == 410 and "Nieuw-Veilig" not in closed.text


def test_only_a_hash_of_the_link_is_kept(admin, make):
    pw = make(admin, "password", "Hash", password="Hash-Test-1")
    path, share = _link(admin, pw["id"])
    token = path.rsplit("/", 1)[1]
    stored = database.get_share(share["id"])
    assert token not in stored["token_hash"] and "Hash-Test-1" not in stored["sealed_json"]


def test_a_viewer_cannot_share(admin, viewer, make):
    pw = make(admin, "password", "Niet delen", password="Niet-Delen-1")
    assert viewer.post(f"/api/items/{pw['id']}/shares", json={"hours": 1, "views": 1}).status_code == 403


def test_an_unknown_link_answers_like_a_used_one(server):
    assert TestClient(app).post("/deel/" + "x" * 43).status_code == 410
