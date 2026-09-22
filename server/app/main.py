"""LeuffenDoc -- IT documentation, per customer, alongside the Leuffen RMM.

Every HTTP endpoint lives here (as in the RMM server, so the two read alike).
The page itself is plain HTML/CSS/JS served from `static/` -- no build step.

This is the foundation: the database, sessions, customers and the shell of the
interface. Signing in through the RMM and with Microsoft 365, the documents
themselves, the customisable document types and the password vault are built on
top of it, each in its own step.
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import auth, database, m365, rmm

log = logging.getLogger("leuffendoc")

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


SYNC_MINUTES = int(os.environ.get("DOC_SYNC_MINUTES", "15"))


async def _sync_loop() -> None:
    """Keep accounts and customers in step with the RMM. A sign-in refreshes
    the person doing it; this is what catches everyone else -- someone who left,
    or a customer that was renamed."""
    while True:
        try:
            await asyncio.to_thread(rmm.sync)
        except Exception as exc:                  # never let the loop die
            log.warning("sync round failed: %r", exc)
        await asyncio.sleep(max(60, SYNC_MINUTES * 60))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database.init_db()
    task = asyncio.create_task(_sync_loop()) if rmm.configured() else None
    yield
    if task:
        task.cancel()


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
    return {"rmm": rmm.configured(), "m365": m365.configured(), "dev": dev_login_enabled()}


# --------------------------------------------------------------------------- #
# Signing in through the RMM
#
# The RMM knows who everyone is, so it does the identifying: it sends the
# browser back here with a single-use ticket, and this server redeems that
# ticket over its own connection, with its API key. A ticket picked out of a
# browser's history is therefore worth nothing on its own.
# --------------------------------------------------------------------------- #
@app.get("/auth/rmm/start")
def rmm_start(request: Request):
    if not rmm.configured():
        return JSONResponse({"detail": "De koppeling met de RMM is niet ingesteld"},
                            status_code=404)
    back = public_url("/auth/rmm/callback")
    if not back.startswith("http"):
        return JSONResponse({"detail": "DOC_PUBLIC_URL ontbreekt, dus de RMM weet niet "
                                       "waar hij je naartoe moet sturen"}, status_code=500)
    return RedirectResponse(rmm.handoff_url(back), status_code=303)


@app.get("/auth/rmm/callback")
def rmm_callback(request: Request, ticket: str = ""):
    if not ticket:
        return _sign_in_failed("Er kwam geen aanmeldbewijs terug van de RMM.")
    try:
        identity = rmm.exchange_ticket(ticket)
        user = rmm.apply_identity(identity)
    except PermissionError as exc:
        return _sign_in_failed(str(exc))
    except Exception as exc:
        log.warning("RMM sign-in failed: %r", exc)
        return _sign_in_failed("De RMM is nu niet bereikbaar. Probeer het zo nog eens, "
                               "of meld je aan met Microsoft 365.")
    response = RedirectResponse("/", status_code=303)
    auth.sign_in(response, user["email"])
    database.audit("sign-in", user_email=user["email"], detail="via de RMM",
                   ip=auth.client_ip(request))
    return response


# --------------------------------------------------------------------------- #
# Signing in with Microsoft 365 (the fallback)
# --------------------------------------------------------------------------- #
@app.get("/auth/m365/start")
def m365_start(request: Request):
    if not m365.configured():
        return JSONResponse({"detail": "Microsoft 365 is niet ingesteld"}, status_code=404)
    state = secrets.token_urlsafe(16)
    response = RedirectResponse(m365.login_url(state), status_code=303)
    response.set_cookie("m365_state", state, httponly=True, max_age=600,
                        samesite="lax", secure=auth.cookie_kwargs()["secure"])
    return response


@app.get("/auth/m365/callback")
def m365_callback(request: Request, code: str = "", state: str = ""):
    if not state or request.cookies.get("m365_state") != state:
        return _sign_in_failed("De aanmelding hoorde niet bij dit venster. Probeer opnieuw.")
    try:
        email = m365.exchange_code(code)
    except Exception as exc:
        return _sign_in_failed(str(exc))
    if not m365.permitted(email):
        return _sign_in_failed(f"{email} mag hier niet bij.")
    existing = database.get_user(email)
    # Someone Microsoft knows but the RMM does not gets in without customers;
    # what they may see is granted here, since Microsoft 365 knows nothing about
    # our customers. An existing account keeps the rights it already has.
    user = database.upsert_user(email, display_name=existing.get("display_name") if existing else None,
                                source=existing.get("source") if existing else "m365")
    response = RedirectResponse("/", status_code=303)
    auth.sign_in(response, user["email"])
    response.delete_cookie("m365_state", path="/")
    database.audit("sign-in", user_email=user["email"], detail="via Microsoft 365",
                   ip=auth.client_ip(request))
    return response


def _sign_in_failed(message: str) -> HTMLResponse:
    """Say what went wrong on the sign-in page itself, rather than dropping
    someone on a bare error."""
    from html import escape
    html = open(os.path.join(STATIC_DIR, "login.html"), encoding="utf-8").read()
    html = html.replace('<div id="msg"></div>',
                        f'<div id="msg" data-error="{escape(message, quote=True)}"></div>')
    for ext in (".js", ".css"):
        html = html.replace(f'{ext}"', f'{ext}?v={VERSION}"')
    return HTMLResponse(html, status_code=400)


@app.post("/auth/dev-login")
async def dev_login(request: Request):
    if not dev_login_enabled():
        return JSONResponse({"detail": "Development sign-in is off"}, status_code=404)
    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return JSONResponse({"detail": "An email address is required"}, status_code=400)
    # The first account to arrive administers the place; everyone after is not
    # an administrator until someone makes them one -- unless they are named in
    # DOC_BOOTSTRAP_ADMIN. Note the None: passing False here would strip the
    # administrator of their rights on their *second* sign-in, since upsert_user
    # reads False as "set it to no".
    admin = database.user_count() == 0 or email in auth.bootstrap_admins()
    database.upsert_user(email, display_name=email.split("@")[0],
                         is_admin=True if admin else None, source="local")
    response = JSONResponse({"status": "ok", "email": email, "is_admin": admin})
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


@app.get("/api/rmm/status")
def rmm_status(user: dict = Depends(auth.current_user)):
    """Whether the RMM link is set up, and how the last sync went."""
    auth.require_admin(user)
    return {"configured": rmm.configured(), "url": rmm.base_url() or None,
            "every_minutes": SYNC_MINUTES, **rmm.last_sync}


@app.post("/api/rmm/sync")
async def rmm_sync_now(request: Request, user: dict = Depends(auth.current_user)):
    """Sync on demand -- for right after someone's access changed in the RMM,
    rather than waiting for the next round."""
    auth.require_admin(user)
    if not rmm.configured():
        return JSONResponse({"detail": "De koppeling met de RMM is niet ingesteld"},
                            status_code=400)
    result = await asyncio.to_thread(rmm.sync)
    database.audit("rmm.sync.manual", user_email=user["email"], ip=auth.client_ip(request))
    return result


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
