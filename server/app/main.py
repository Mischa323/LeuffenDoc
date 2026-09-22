"""LeuffenDoc -- IT documentation, per customer, alongside the Leuffen RMM.

Every HTTP endpoint lives here (as in the RMM server, so the two read alike).
The page itself is plain HTML/CSS/JS served from `static/` -- no build step.

This is the foundation: the database, sessions, customers and the shell of the
interface. Signing in through the RMM and with Microsoft 365, the documents
themselves, the customisable document types and the password vault are built on
top of it, each in its own step.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import auth, database

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def _version() -> str:
    for path in ("/app/VERSION", os.path.join(os.path.dirname(__file__), "..", "..", "VERSION")):
        try:
            with open(path) as fh:
                return fh.read().strip()
        except OSError:
            continue
    return "0.0.0"


VERSION = _version()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database.init_db()
    yield


app = FastAPI(title="LeuffenDoc", version=VERSION, lifespan=lifespan)


def _serve_html(filename: str) -> HTMLResponse:
    """Serve a page with `?v=<version>` stamped onto its own CSS/JS, so an
    upgrade never leaves a browser running yesterday's files."""
    with open(os.path.join(STATIC_DIR, filename), encoding="utf-8") as fh:
        html = fh.read()
    for ext in (".js", ".css"):
        html = html.replace(f'{ext}"', f'{ext}?v={VERSION}"')
    return HTMLResponse(html)


# --------------------------------------------------------------------------- #
# Health and version
# --------------------------------------------------------------------------- #
@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok", "version": VERSION}


@app.get("/api/version")
def version():
    return {"version": VERSION}


def public_url(path: str = "") -> str:
    """An absolute URL back to this server.

    Built from `DOC_PUBLIC_URL`, never from the incoming request: behind a
    reverse proxy the request arrives as plain HTTP on an internal name, so
    anything built from it would send people to an address that doesn't work --
    which is exactly what breaks a sign-in redirect.
    """
    base = (os.environ.get("DOC_PUBLIC_URL") or database.get_setting("DOC_PUBLIC_URL") or "").rstrip("/")
    return f"{base}{path}" if base else path


@app.get("/api/diagnostics")
def diagnostics(request: Request, user: dict = Depends(auth.current_user)):
    """What the server sees of the connection -- the quickest way to tell
    whether the reverse proxy in front of it is passing its headers on."""
    auth.require_admin(user)
    hops = auth.forwarded_hops(request)
    return {
        "version": VERSION,
        "public_url": public_url() or None,
        "trust_proxy": auth.trust_proxy(),
        "proxy_ips": os.environ.get("DOC_PROXY_IPS", "*"),
        # Who we think you are, and the raw material that answer came from.
        "client_ip": auth.client_ip(request),
        "forwarded_for": ", ".join(hops) or None,
        # More than one hop means the proxy appends rather than replaces, and
        # the oldest entry came from the visitor's own browser.
        "forwarded_hops": len(hops),
        "forwarded_proto": request.headers.get("x-forwarded-proto"),
        "scheme": request.url.scheme,
        "host": request.headers.get("host"),
        "secure_cookies": os.environ.get("DOC_SECURE_COOKIES", "1") not in ("0", "false", "no"),
    }


# --------------------------------------------------------------------------- #
# Signing in
# --------------------------------------------------------------------------- #
def dev_login_enabled() -> bool:
    """A password-free sign-in for local development. Off unless asked for, and
    never something to enable on a server people can reach."""
    return os.environ.get("DOC_DEV_LOGIN", "0") in ("1", "true", "yes")


@app.get("/auth/login")
def login_page(request: Request):
    if auth.optional_user(request):
        return RedirectResponse("/", status_code=303)
    return _serve_html("login.html")


@app.get("/api/auth/methods")
def auth_methods():
    """What the sign-in page should offer. The RMM path needs an address and an
    API key; Microsoft 365 needs an app registration."""
    return {
        "rmm": bool(os.environ.get("DOC_RMM_URL") or database.get_setting("DOC_RMM_URL")),
        "m365": bool(os.environ.get("DOC_M365_CLIENT_ID") or database.get_setting("DOC_M365_CLIENT_ID")),
        "dev": dev_login_enabled(),
    }


@app.post("/auth/dev-login")
async def dev_login(request: Request):
    if not dev_login_enabled():
        return JSONResponse({"detail": "Development sign-in is off"}, status_code=404)
    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return JSONResponse({"detail": "An email address is required"}, status_code=400)
    # The first account to arrive administers the place; everyone after is not
    # an administrator until someone makes them one. Note the None: passing
    # False here would strip the administrator of their rights on their *second*
    # sign-in, since upsert_user reads False as "set it to no".
    first = database.user_count() == 0
    database.upsert_user(email, display_name=email.split("@")[0],
                         is_admin=True if first else None, source="local")
    response = JSONResponse({"status": "ok", "email": email, "is_admin": first})
    auth.sign_in(response, email)
    database.audit("sign-in", user_email=email, detail="development sign-in",
                   ip=auth.client_ip(request))
    return response


@app.get("/auth/logout")
def logout(request: Request):
    user = auth.optional_user(request)
    response = RedirectResponse("/auth/login", status_code=303)
    auth.sign_out(response)
    if user:
        database.audit("sign-out", user_email=user["email"], ip=auth.client_ip(request))
    return response


# --------------------------------------------------------------------------- #
# The signed-in person and their customers
# --------------------------------------------------------------------------- #
@app.get("/api/me")
def me(user: dict = Depends(auth.current_user)):
    return {"email": user["email"], "display_name": user.get("display_name"),
            "is_admin": bool(user.get("is_admin")), "source": user.get("source"),
            "version": VERSION}


@app.get("/api/orgs")
def orgs(user: dict = Depends(auth.current_user)):
    """The customers this person may see: everything for an administrator, and
    otherwise the ones they have been given."""
    if user.get("is_admin"):
        return database.list_orgs()
    return database.user_orgs(user["email"])


@app.post("/api/orgs")
async def create_org(request: Request, user: dict = Depends(auth.current_user)):
    auth.require_admin(user)
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"detail": "A name is required"}, status_code=400)
    org_id = database.upsert_org(name, rmm_org_id=(body.get("rmm_org_id") or None))
    database.audit("org.create", user_email=user["email"], org_id=org_id, target=name,
                   ip=auth.client_ip(request))
    return database.get_org(org_id)


@app.get("/api/audit")
def audit_log(org_id: str | None = None, user: dict = Depends(auth.current_user)):
    auth.require_admin(user)
    return database.list_audit(org_id)


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
@app.get("/")
def index(request: Request):
    if not auth.optional_user(request):
        return RedirectResponse("/auth/login", status_code=303)
    return _serve_html("index.html")


@app.get("/favicon.svg")
def favicon():
    return FileResponse(os.path.join(STATIC_DIR, "favicon.svg"))


# Everything else is a static file (styles, scripts, icons).
app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")
