"""What leaves this server: a customer's export, and the summaries sent to the RMM."""
import io
import json
import zipfile

from app import database, docpush


def _unzip(response):
    z = zipfile.ZipFile(io.BytesIO(response.content))
    return {name.split("/", 1)[1]: z.read(name) for name in z.namelist()}


def test_an_export_has_a_page_the_data_and_a_sheet_per_kind(admin, member, org, make):
    make(admin, "location", "Hoofdkantoor", {"city": "Deventer"})
    make(admin, "password", "Exportwachtwoord", password="Niet-In-De-Export-1")
    response = member.post(f"/api/orgs/{org['id']}/export", json={})
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
    files = _unzip(response)
    assert {"documentatie.html", "data.json"} <= set(files)
    assert any(name.startswith("csv/") for name in files)
    page = files["documentatie.html"].decode()
    assert "Hoofdkantoor" in page and "Deventer" in page
    assert "Niet-In-De-Export-1" not in page and "Niet-In-De-Export-1" not in files["data.json"].decode()


def test_passwords_go_along_only_when_asked_and_allowed(admin, member, viewer, org, make):
    make(admin, "password", "Meenemen", password="Wel-In-De-Export-1")
    assert viewer.post(f"/api/orgs/{org['id']}/export", json={"passwords": True}).status_code == 403
    files = _unzip(member.post(f"/api/orgs/{org['id']}/export", json={"passwords": True}))
    assert "Wel-In-De-Export-1" in files["documentatie.html"].decode()
    log = admin.get("/api/audit").json()
    assert any(e["action"] == "secret.export" and e["target"] == "Meenemen" for e in log)


def test_an_export_leaves_out_what_is_shut_off(admin, member, org, make):
    pw = make(admin, "password", "Niet voor het lid", password="Afgeschermd-Export-1")
    admin.put(f"/api/items/{pw['id']}/access", json={"people": ["admin@example.test"]})
    files = _unzip(member.post(f"/api/orgs/{org['id']}/export", json={}))
    assert "Niet voor het lid" not in files["data.json"].decode()


def test_the_rmm_gets_what_is_documented_but_never_a_password(admin, org, make):
    machine = database.create_item(org["id"], "computer", "WS-DOCS", {"installed_by": "Iemand",
                                   "notes": "Eerste regel\nTweede regel"}, by=None, source="rmm",
                                   rmm_device_id="dev-docs", rmm={"cpu": "Een processor"})
    visible = make(admin, "password", "Lokale beheerder", password="Nooit-Naar-De-RMM-1")
    hidden = make(admin, "password", "Afgeschermd voor de RMM", password="Ook-Niet-1")
    for other in (visible, hidden):
        admin.post(f"/api/items/{machine['id']}/relations", json={"item_id": other["id"]})
    admin.put(f"/api/items/{hidden['id']}/access", json={"people": ["admin@example.test"]})

    docs = docpush.wanted()
    doc = docs["dev-docs"]
    labels = {f["label"]: f for f in doc["fields"]}
    assert labels["Geïnstalleerd door"]["value"] == "Iemand"
    assert labels["Notities"]["multiline"] is True
    assert "Processor" not in labels                     # the RMM shows that itself
    names = {r["name"] for r in doc["related"]}
    assert "Lokale beheerder" in names and "Afgeschermd voor de RMM" not in names
    assert "Nooit-Naar-De-RMM" not in json.dumps(docs) and "Ook-Niet" not in json.dumps(docs)
    assert doc["url"].startswith("http://testserver/#/klant/")

    admin.put(f"/api/items/{machine['id']}/access", json={"people": ["admin@example.test"]})
    assert "dev-docs" not in docpush.wanted()
