"""Notes: left on any item without editing it, by whoever may change it."""
import io
import zipfile

from app import database


def test_notes_on_any_item(admin, member, viewer, org, make):
    item = make(admin, "computer", "WS-NOTITIE", {"role": "Desktop"})
    url = f"/api/items/{item['id']}/notes"
    assert admin.post(url, json={"body": "   "}).status_code == 400
    first = admin.post(url, json={"body": "Schijf vervangen op 3 oktober.\nGarantie via Dell."})
    assert first.status_code == 200, first.text
    mine = member.post(url, json={"body": "Gebruiker belt vaak over de printer"}).json()
    assert viewer.post(url, json={"body": "mag niet"}).status_code == 403          # reads, does not write
    notes = viewer.get(url).json()
    assert [n["body"].split("\n")[0] for n in notes] == ["Gebruiker belt vaak over de printer",
                                                       "Schijf vervangen op 3 oktober."]
    assert notes[0]["created_by"] == "lid@example.test"

    # A note is changed by whoever wrote it, or an administrator.
    assert member.patch(f"/api/notes/{first.json()['id']}", json={"body": "anders"}).status_code == 403
    assert member.patch(f"/api/notes/{mine['id']}", json={"body": "Belt vaak over de printer op de 2e"}).status_code == 200
    assert admin.delete(f"/api/notes/{mine['id']}").status_code == 200
    assert len(admin.get(url).json()) == 1

    # The history says so; search and the export find it.
    said = [c["said"] for r in admin.get(f"/api/items/{item['id']}/revisions").json()
            for c in r["changes"] if c["key"] == "note"]
    assert said[-1] == "toegevoegd: Schijf vervangen op 3 oktober." and any(s.startswith("verwijderd") for s in said)
    found = admin.get("/api/search", params={"q": "garantie via dell", "org": org["id"]}).json()
    hits = found if isinstance(found, list) else found.get("results", [])
    assert any(h["id"] == item["id"] for h in hits)
    data = admin.post(f"/api/orgs/{org['id']}/export", json={"passwords": False}).content
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        page = z.read(next(n for n in z.namelist() if n.endswith("documentatie.html"))).decode()
    assert "Schijf vervangen op 3 oktober." in page

    # On what the RMM keeps up just the same; and gone with the item.
    admin.delete(f"/api/items/{item['id']}")
    assert database.list_notes(item["id"]) == []
