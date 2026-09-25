"""Back-ups: a snapshot while running, carried away encrypted, put back in place."""
import os
import shutil
import sqlite3
from urllib.parse import quote

from app import backup

PASS = "Een wachtwoordzin voor de proef €"


def _names(client, org):
    return {i["name"] for i in client.get(f"/api/orgs/{org['id']}/items?kind=location").json()}


def test_only_an_administrator_touches_back_ups(member):
    assert member.get("/api/admin/backups").status_code == 403
    assert member.post("/api/admin/backups").status_code == 403


def test_a_snapshot_opens_and_says_what_is_in_it(admin, make):
    make(admin, "password", "In de snapshot", password="Snapshot-1")
    made = admin.post("/api/admin/backups").json()
    assert made["kind"] == "handmatig" and made["passwords"] >= 1
    conn = sqlite3.connect(backup.path_of(made["name"]))
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()


def test_a_download_is_encrypted_and_needs_a_real_passphrase(admin):
    made = admin.post("/api/admin/backups").json()
    assert admin.post(f"/api/admin/backups/{made['name']}/download",
                      json={"passphrase": "kort"}).status_code == 400
    sealed = admin.post(f"/api/admin/backups/{made['name']}/download", json={"passphrase": PASS})
    assert sealed.status_code == 200
    assert sealed.content.startswith(backup.MAGIC) and b"SQLite format" not in sealed.content


def test_putting_back_replaces_everything_and_can_be_undone(admin, org, make):
    make(admin, "location", "Voor de back-up")
    made = admin.post("/api/admin/backups").json()
    sealed = admin.post(f"/api/admin/backups/{made['name']}/download", json={"passphrase": PASS}).content
    make(admin, "location", "Na de back-up")

    wrong = admin.post("/api/admin/backups/upload", content=sealed,
                       headers={"X-Backup-Passphrase": quote("een verkeerde zin")})
    assert wrong.status_code == 400 and "wachtwoordzin" in wrong.json()["detail"]
    got = admin.post("/api/admin/backups/upload", content=sealed,
                     headers={"X-Backup-Passphrase": quote(PASS)}).json()
    assert admin.post(f"/api/admin/backups/{got['name']}/restore", json={}).status_code == 400
    done = admin.post(f"/api/admin/backups/{got['name']}/restore", json={"confirm": got["name"]})
    assert done.status_code == 200
    assert "Voor de back-up" in _names(admin, org) and "Na de back-up" not in _names(admin, org)

    before = done.json()["before"]["name"]
    admin.post(f"/api/admin/backups/{before}/restore", json={"confirm": before})
    assert "Na de back-up" in _names(admin, org)


def test_a_back_up_whose_passwords_would_not_open_is_refused(admin, make):
    make(admin, "password", "Andere sleutel", password="Andere-Sleutel-1")
    made = admin.post("/api/admin/backups").json()
    copy = os.path.join(os.path.dirname(backup.path_of(made["name"])), "proef-kopie.sqlite")
    shutil.copy(backup.path_of(made["name"]), copy)
    conn = sqlite3.connect(copy)
    conn.execute("UPDATE secrets SET wrapped_key = randomblob(length(wrapped_key))")
    conn.commit()
    conn.close()
    with open(copy, "rb") as fh:
        refused = admin.post("/api/admin/backups/upload", content=fh.read())
    os.remove(copy)
    assert refused.status_code == 400 and "niet open" in refused.json()["detail"]


def test_something_else_is_not_a_back_up(admin):
    refused = admin.post("/api/admin/backups/upload", content=b"zomaar wat bytes")
    assert refused.status_code == 400
    assert admin.delete("/api/admin/backups/..%2Fleuffendoc.db").status_code in (400, 404, 405)


def test_only_so_many_automatic_ones_are_kept(server):
    for _ in range(3):
        backup.snapshot("auto")
    backup.prune(2)
    assert len([b for b in backup.list_backups() if b["kind"] == "auto"]) == 2
