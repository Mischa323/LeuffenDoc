"""The vault's key in the interface: shown to keep a copy elsewhere, and
replaced by another -- without anything in the vault becoming unreadable."""
import os

from app import backup, database, settings, vault


def _key_in_database(monkeypatch):
    """Run this test as an installation without DOC_SECRET_KEY: the same key,
    kept in the database, so what the other tests stored still opens."""
    original = os.environ[vault.KEY_SETTING]
    database.set_setting(vault.KEY_SETTING, original)
    monkeypatch.delenv(vault.KEY_SETTING)
    vault._cached = None
    return original


def _back_to_the_environment(original):
    vault.rekey(original)
    with database.write() as conn:
        conn.execute("DELETE FROM settings WHERE key IN (?, ?)", (vault.KEY_SETTING, vault.SAVED_SETTING))
    vault._cached = None


def test_the_key_is_shown_kept_and_replaced(admin, member, make, monkeypatch):
    item = make(admin, "password", "Sleutelwissel", {"username": "beheer"}, password="Oud-Geheim-Wachtwoord-1")
    share = admin.post(f"/api/items/{item['id']}/shares", json={"hours": 24, "views": 1}).json()
    token = share["url"].rsplit("/", 1)[-1]
    settings.put("DOC_M365_CLIENT_SECRET", "client-geheim-123")
    original = _key_in_database(monkeypatch)
    try:
        st = admin.get("/api/admin/settings").json()["vault"]
        assert st["in_database"] and st["saved"] is None

        # Shown to an administrator, and written down; not to anybody else.
        assert member.post("/api/admin/vault/key/reveal").status_code == 403
        shown = admin.post("/api/admin/vault/key/reveal").json()["key"]
        assert shown == original
        assert database.rows("SELECT action FROM audit WHERE action='vault.key.reveal'")
        st = admin.post("/api/admin/vault/key/saved").json()
        assert st["saved"]["by"] == "admin@example.test"

        # A key of one's own must be long enough.
        assert admin.post("/api/admin/vault/key", json={"key": "te-kort"}).status_code == 400

        # A new key: everything moves with it.
        before_fp = database.get_secret(item["id"], "main")["fingerprint"]
        r = admin.post("/api/admin/vault/key", json={"key": "een-eigen-lange-wachtwoordzin-voor-de-kluis"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["key"] == "een-eigen-lange-wachtwoordzin-voor-de-kluis" and body["counts"]["passwords"] >= 1
        assert body["counts"]["shares"] >= 1 and body["counts"]["settings"] >= 1
        assert body["state"]["saved"] is None                     # the new one is not kept anywhere yet
        assert body["backup"].startswith("voor-sleutel-")
        assert any(b["name"] == body["backup"] for b in backup.list_backups())

        assert admin.get(f"/api/items/{item['id']}/secret").json()["password"] == "Oud-Geheim-Wachtwoord-1"
        fp = database.get_secret(item["id"], "main")["fingerprint"]
        assert fp != before_fp and fp == vault.fingerprint("Oud-Geheim-Wachtwoord-1")
        assert settings.secret("DOC_M365_CLIENT_SECRET") == "client-geheim-123"
        opened = admin.post(f"/deel/{token}")
        assert opened.status_code == 200 and opened.json()["password"] == "Oud-Geheim-Wachtwoord-1"
        # The old key does not open it any more.
        record = database.get_secret(item["id"], "main")
        vault._cached = vault._decode(original)
        try:
            vault.unseal(record)
            assert False, "the old key should not open the vault any more"
        except Exception:
            pass
        vault._cached = None
        assert vault.unseal(record) == "Oud-Geheim-Wachtwoord-1"

        # One made here: a strong key, shown once.
        made = admin.post("/api/admin/vault/key", json={}).json()
        assert len(made["key"]) >= 43 and made["key"] != body["key"]
        assert admin.get(f"/api/items/{item['id']}/secret").json()["password"] == "Oud-Geheim-Wachtwoord-1"
    finally:
        _back_to_the_environment(original)


def test_a_key_from_the_environment_is_not_handled_here(admin):
    assert admin.post("/api/admin/vault/key/reveal").status_code == 400
    assert admin.post("/api/admin/vault/key", json={}).status_code == 400
    st = admin.get("/api/admin/settings").json()["vault"]
    assert st["from_environment"] and not st["copy_in_database"]
    # An old copy of the same key in the database can go; the key itself stays in force.
    database.set_setting(vault.KEY_SETTING, os.environ[vault.KEY_SETTING])
    st = admin.get("/api/admin/settings").json()["vault"]
    assert st["copy_in_database"] and st["copy_matches"]
    assert admin.delete("/api/admin/vault/key/copy").json()["copy_in_database"] is False
    assert database.get_setting(vault.KEY_SETTING) is None
    # A different one stays, until it is clear which key opens the passwords.
    database.set_setting(vault.KEY_SETTING, "een-andere-sleutel-dan-in-de-omgeving")
    assert admin.delete("/api/admin/vault/key/copy").status_code == 400
    with database.write() as conn:
        conn.execute("DELETE FROM settings WHERE key=?", (vault.KEY_SETTING,))
