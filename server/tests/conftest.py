"""One LeuffenDoc for the whole test run, on a database of its own.

The environment is set before the app is imported: the database path and the
vault's key are read when their modules load. Everyone signs in through the
development sign-in; what they may do at the test customer is given to them
here the way a sync from the RMM would.
"""
import os
import sys
import tempfile

import pytest

DATA = tempfile.mkdtemp(prefix="leuffendoc-test-")
os.environ.update({
    "DOC_DB_PATH": os.path.join(DATA, "leuffendoc.db"),
    "DOC_DEV_LOGIN": "1",
    "DOC_SECURE_COOKIES": "0",
    "DOC_BOOTSTRAP_ADMIN": "admin@example.test",
    "DOC_SECRET_KEY": "een-vaste-sleutel-alleen-voor-de-tests",
    "DOC_PUBLIC_URL": "http://testserver",
})
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app import database  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def server():
    # Entering the client runs start-up: the database, and the loops beside it.
    with TestClient(app) as client:
        yield client


def sign_in(email: str) -> TestClient:
    client = TestClient(app)
    response = client.post("/auth/dev-login", json={"email": email})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture(scope="session")
def admin(server):
    response = server.post("/auth/dev-login", json={"email": "admin@example.test"})
    assert response.json()["is_admin"] is True
    return server


@pytest.fixture(scope="session")
def org(admin):
    assert admin.post("/api/orgs", json={"name": "Proefklant BV"}).status_code == 200
    return next(o for o in admin.get("/api/orgs").json() if o["name"] == "Proefklant BV")


def _person(email: str, org_id: str | None, role: str | None) -> TestClient:
    client = sign_in(email)
    database.set_user_orgs(email, [(org_id, role)] if org_id else [])
    return client


@pytest.fixture(scope="session")
def member(org):
    return _person("lid@example.test", org["id"], "member")


@pytest.fixture(scope="session")
def viewer(org):
    return _person("kijker@example.test", org["id"], "viewer")


@pytest.fixture(scope="session")
def outsider(org):
    return _person("buiten@example.test", None, None)


@pytest.fixture
def make(org):
    """Document something at the test customer, as whoever is given."""
    def _make(client, kind, name, fields=None, password=None):
        body = {"kind": kind, "name": name, "fields": fields or {}}
        if password:
            body["password"] = password
        response = client.post(f"/api/orgs/{org['id']}/items", json=body)
        assert response.status_code == 200, response.text
        return response.json()
    return _make
