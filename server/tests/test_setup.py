"""The first start: the set-up screen, its code, and linking with the RMM by button."""
import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import auth, database, pairing, settings, setup
from app.main import app

TOUCHED = ("DOC_RMM_URL", "DOC_RMM_PUBLIC_URL", "DOC_RMM_API_KEY", "DOC_RMM_INSECURE_TLS",
           "DOC_TRUST_PROXY", "DOC_PROXY_IPS", "DOC_SECURE_COOKIES", "DOC_BOOTSTRAP_ADMIN",
           "DOC_M365_TENANT", "DOC_M365_CLIENT_ID", "DOC_M365_CLIENT_SECRET")


@pytest.fixture
def fresh(server):
    """A server that has not been set up yet -- and back to how it was after."""
    saved = {key: database.get_setting(key) for key in TOUCHED}
    database.set_setting(setup.DONE, "")
    setup.announce()
    yield TestClient(app, follow_redirects=False)
    for key, value in saved.items():
        database.set_setting(key, value or "")
    setup.mark_done()


def test_a_fresh_server_opens_on_the_set_up_screen(fresh):
    assert fresh.get("/").headers["location"] == "/setup"
    assert fresh.get("/auth/login").headers["location"] == "/setup"
    assert fresh.get("/setup").status_code == 200


def test_the_set_up_screen_wants_the_code_from_the_log(fresh):
    assert fresh.post("/api/setup/unlock", json={"code": "FOUT-FOUT"}).status_code == 403
    seen = fresh.post("/api/setup/unlock", json={"code": setup._code.lower().replace("-", "")})
    assert seen.status_code == 200 and "via_proxy" in seen.json()


def test_guessing_the_code_makes_a_new_one(fresh):
    first = setup._code
    for _ in range(setup.MAX_ATTEMPTS):
        fresh.post("/api/setup/unlock", json={"code": "AAAA-AAAA"})
    assert setup._code != first
    assert fresh.post("/api/setup/unlock", json={"code": first}).status_code == 403


def test_one_button_links_with_the_rmm_and_finishes_set_up(fresh, monkeypatch):
    calls = []

    def fake_exchange(url, code, verifier, insecure):
        calls.append((url, code, verifier, insecure))
        if len(calls) == 1:
            raise pairing.Unreachable(f"deze server krijgt geen verbinding met {url}")
        return {"api_key": "lrmm_api_uit-de-proef", "approved_by": "rmm-beheer@example.test", "orgs": 3}

    monkeypatch.setattr(pairing, "_exchange", fake_exchange)
    started = fresh.post("/api/setup/pair", json={
        "code": setup._code, "rmm_url": "https://rmm.example.test/",
        "public_url": "https://doc.example.test", "trust_proxy": True, "proxy_ips": "172.20.0.1"})
    assert started.status_code == 200
    target = urlparse(started.json()["redirect"])
    query = parse_qs(target.query)
    assert f"{target.scheme}://{target.netloc}{target.path}" == "https://rmm.example.test/pair"
    assert query["doc"] == ["https://doc.example.test"]
    state, challenge = query["state"][0], query["challenge"][0]

    back = fresh.get(f"/koppelen/terug?code=een-code&state={state}")
    assert back.status_code == 303 and back.headers["location"].startswith("/koppelen?state=")

    # The browser reached the RMM; this server does not, at that address.
    first = fresh.post("/api/koppelen/afronden", json={"state": state})
    assert first.status_code == 502 and first.json()["unreachable"] is True
    assert setup.needs()

    done = fresh.post("/api/koppelen/afronden", json={"state": state,
                                                     "server_url": "https://192.168.1.10:8000",
                                                     "insecure": True})
    assert done.status_code == 200 and done.json()["next"] == "/auth/rmm/start"
    url, code, verifier, insecure = calls[-1]
    assert (url, code, insecure) == ("https://192.168.1.10:8000", "een-code", True)
    # The secret only this server held matches what the browser carried to the RMM.
    assert base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=") == challenge

    assert not setup.needs()
    assert settings.get("DOC_RMM_URL") == "https://192.168.1.10:8000"
    assert settings.get("DOC_RMM_PUBLIC_URL") == "https://rmm.example.test"
    assert settings.secret("DOC_RMM_API_KEY") == "lrmm_api_uit-de-proef"
    assert "lrmm_api_uit-de-proef" not in (database.get_setting("DOC_RMM_API_KEY") or "")
    assert settings.get("DOC_TRUST_PROXY") is True and settings.get("DOC_PROXY_IPS") == "172.20.0.1"
    assert "rmm-beheer@example.test" in auth.bootstrap_admins()
    # A state is good for one exchange only.
    assert fresh.post("/api/koppelen/afronden", json={"state": state}).status_code == 400


def test_set_up_by_hand_needs_a_way_in_and_an_administrator(fresh):
    base = {"code": setup._code, "public_url": "https://doc.example.test"}
    assert fresh.post("/api/setup/manual", json=base).status_code == 400
    assert fresh.post("/api/setup/manual", json={**base, "admins": ["iemand@example.test"]}).status_code == 400
    done = fresh.post("/api/setup/manual", json={**base, "admins": ["iemand@example.test"],
                                                  "m365_tenant": "t", "m365_client_id": "c",
                                                  "m365_secret": "s"})
    assert done.status_code == 200 and not setup.needs()
    assert settings.secret("DOC_M365_CLIENT_SECRET") == "s"


def test_a_link_alone_never_starts_a_new_pairing(admin):
    """Whoever is the RMM decides who signs in here, so a link someone sends an
    administrator must not re-link by itself: the page asks first."""
    response = admin.get("/koppelen?rmm=https://nep-rmm.example", follow_redirects=False)
    assert response.status_code == 200 and "nep-rmm" not in response.headers.get("location", "")


def test_a_set_up_server_does_not_show_the_screen_again(admin):
    assert TestClient(app, follow_redirects=False).get("/setup").headers["location"] == "/"
    assert admin.post("/api/setup/unlock", json={"code": "x"}).status_code == 409


def test_a_saved_setting_is_not_mistaken_for_the_environment(admin):
    assert admin.put("/api/admin/settings", json={"DOC_SYNC_MINUTES": 7}).status_code == 200
    described = admin.get("/api/admin/settings").json()["settings"]["DOC_SYNC_MINUTES"]
    assert described["value"] == 7 and described["from_env"] is False


def _request(peer, forwarded=None, proto=None):
    headers = []
    if forwarded:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    if proto:
        headers.append((b"x-forwarded-proto", proto.encode()))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers,
                    "client": (peer, 5555), "scheme": "http", "server": ("doc", 80), "query_string": b""})


def test_only_the_named_proxy_says_who_the_visitor_is(server):
    before = {k: database.get_setting(k) for k in ("DOC_TRUST_PROXY", "DOC_PROXY_IPS")}
    try:
        settings.put("DOC_TRUST_PROXY", True)
        settings.put("DOC_PROXY_IPS", "172.16.0.0/12")
        assert auth.client_ip(_request("172.20.0.1", "203.0.113.9", "https")) == "203.0.113.9"
        assert auth.request_scheme(_request("172.20.0.1", "203.0.113.9", "https")) == "https"
        # Someone reaching the container directly cannot choose their address.
        assert auth.client_ip(_request("198.51.100.4", "203.0.113.9")) == "198.51.100.4"
        assert auth.request_scheme(_request("198.51.100.4", None, "https")) == "http"
        settings.put("DOC_TRUST_PROXY", False)
        assert auth.client_ip(_request("172.20.0.1", "203.0.113.9")) == "172.20.0.1"
    finally:
        for key, value in before.items():
            database.set_setting(key, value or "")
