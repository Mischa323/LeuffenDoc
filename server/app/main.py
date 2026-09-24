"""LeuffenDoc -- IT documentation, per customer, alongside the Leuffen RMM.

Every HTTP endpoint lives here (as in the RMM server, so the two read alike).
The page itself is plain HTML/CSS/JS served from `static/` -- no build step.

Built up in steps: the database, sessions and customers; signing in through the
RMM and with Microsoft 365; and now what is actually documented -- configurations
and the customer's own parts, with their history and what they are related to.
Types people define themselves and the password vault come on top of the same
foundation.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import auth, database, m365, rmm, schema, settings, vault

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


async def _sync_loop() -> None:
    """Keep accounts and customers in step with the RMM. A sign-in refreshes
    the person doing it; this is what catches everyone else -- someone who left,
    or a customer that was renamed.

    It runs whether or not the link is set up yet, and reads the interval each
    round: both can now change on the settings page, and neither should need a
    restart to take effect.
    """
    while True:
        if rmm.configured():
            try:
                await asyncio.to_thread(rmm.sync)
            except Exception as exc:              # never let the loop die
                log.warning("sync round failed: %r", exc)
        await asyncio.sleep(max(60, int(settings.get("DOC_SYNC_MINUTES")) * 60))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database.init_db()
    # While this container's own image can still be looked up, note what it
    # set -- an update needs that to carry over only what was chosen here.
    from . import docker_update
    asyncio.create_task(asyncio.to_thread(docker_update.remember_own_image))
    task = asyncio.create_task(_sync_loop())
    yield
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
    base = (settings.get("DOC_PUBLIC_URL") or "").rstrip("/")
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
            "every_minutes": settings.get("DOC_SYNC_MINUTES"), **rmm.last_sync}


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
# What is documented: configurations and the customer's own parts
#
# One set of endpoints for every kind, because the difference between a switch
# and an internet connection is a list of fields (see schema.py) and not a
# different way of storing, reading or recording it. The interface builds its
# forms from the same catalogue, so a field added there needs nothing here.
# --------------------------------------------------------------------------- #
def _may_see(user: dict, org_id: str) -> dict:
    """The customer, if this person may see it.

    An administrator sees every customer; everyone else sees the ones the RMM
    gave them. A customer they may not see is reported as missing rather than
    forbidden -- "you may not see X" already tells them X exists.
    """
    org = database.get_org(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Deze klant bestaat niet")
    if user.get("is_admin"):
        return org
    if not any(o["id"] == org_id for o in database.user_orgs(user["email"])):
        raise HTTPException(status_code=404, detail="Deze klant bestaat niet")
    return org


def _item_for(user: dict, item_id: str) -> tuple[dict, dict]:
    item = database.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Dit item bestaat niet")
    return item, _may_see(user, item["org_id"])


def _labeller(kind: str):
    return lambda key: schema.label_of(kind, key)


def _referred_by(item: dict) -> list:
    """Everything in this customer that points at this item.

    A reference is written on one side -- a computer names its location -- but
    it is worth reading from both: standing on a location, what you want is the
    list of what is there. Nobody should have to write that down twice.
    """
    refs = schema.ref_fields()
    out = []
    for other in database.list_items(item["org_id"], include_archived=True):
        if other["id"] == item["id"]:
            continue
        for field in refs.get(other["kind"], []):
            if other["fields"].get(field["key"]) == item["id"]:
                out.append({"id": other["id"], "kind": other["kind"],
                            "name": other["name"], "archived": other["archived"],
                            "field": field["key"], "field_label": field["label"]})
    return out


def _decorate(item: dict) -> dict:
    """An item as the interface wants it: its own fields, what the RMM knows,
    what it is related to, its network adapters, and -- for a switch -- the
    patch list of its ports."""
    item = dict(item)
    item["relations"] = database.relations_of(item["id"])
    item["referred_by"] = _referred_by(item)
    if item["kind"] == "password":
        item.update(database.secret_state(item["id"]))
    if schema.secret_fields_of(item["kind"]):
        item["secrets"] = database.secret_fields(item["id"])
    if item["kind"] in schema.adapter_kinds():
        item["adapters"] = database.list_adapters(item["id"])
    if has_ports(item):
        item["ports"] = database.ports_of(item["id"], port_count(item))
    return item


@app.get("/api/kinds")
def kinds(user: dict = Depends(auth.current_user)):
    """Everything that can be documented, and the fields each kind has."""
    return schema.catalogue()


@app.get("/api/orgs/{org_id}/items")
def org_items(org_id: str, kind: str | None = None, archived: bool = False,
              user: dict = Depends(auth.current_user)):
    _may_see(user, org_id)
    if kind and not schema.kind(kind):
        raise HTTPException(status_code=400, detail=f"Onbekend soort: {kind}")
    return database.list_items(org_id, kind, include_archived=archived)


@app.get("/api/orgs/{org_id}/summary")
def org_summary(org_id: str, user: dict = Depends(auth.current_user)):
    """How much of each kind this customer has -- what the overview shows."""
    org = _may_see(user, org_id)
    return {"org": org, "counts": database.count_items(org_id)}


@app.post("/api/orgs/{org_id}/items")
async def create_org_item(org_id: str, request: Request,
                          user: dict = Depends(auth.current_user)):
    _may_see(user, org_id)
    body = await request.json()
    kind = (body.get("kind") or "").strip()
    if not schema.kind(kind):
        raise HTTPException(status_code=400, detail=f"Onbekend soort: {kind or '(leeg)'}")
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Een naam is verplicht")
    item = database.create_item(org_id, kind, name,
                                schema.clean(kind, body.get("fields") or {}),
                                by=user["email"], label=_labeller(kind))
    if kind == "password" and body.get("password"):
        database.put_secret(item["id"], vault.seal(body["password"]), by=user["email"])
        # The history should say a password was set here, the same as when one
        # is changed later -- otherwise the first one is the only change to a
        # vault entry that leaves no trace.
        database.record(item["id"], "updated",
                        [{"key": "secret", "label": "Wachtwoord", "from": "", "to": "ingesteld"}],
                        by=user["email"])
        database.audit("secret.write", user_email=user["email"], org_id=org_id,
                       target=name, ip=auth.client_ip(request))
        item = database.get_item(item["id"])
    database.audit("item.create", user_email=user["email"], org_id=org_id,
                   target=name, detail=schema.kind(kind)["label"],
                   ip=auth.client_ip(request))
    return _decorate(item)


@app.get("/api/items/{item_id}")
def read_item(item_id: str, user: dict = Depends(auth.current_user)):
    item, _ = _item_for(user, item_id)
    return _decorate(item)


@app.patch("/api/items/{item_id}")
async def edit_item(item_id: str, request: Request,
                    user: dict = Depends(auth.current_user)):
    item, _ = _item_for(user, item_id)
    body = await request.json()
    name = body.get("name")
    if name is not None and not str(name).strip():
        raise HTTPException(status_code=400, detail="Een naam is verplicht")
    fields = body.get("fields")
    updated = database.update_item(
        item_id, name=name,
        fields=schema.clean_form(item["kind"], fields) if fields is not None else None,
        by=user["email"], label=_labeller(item["kind"]))
    database.audit("item.update", user_email=user["email"], org_id=item["org_id"],
                   target=updated["name"], ip=auth.client_ip(request))
    return _decorate(updated)


@app.post("/api/items/{item_id}/archive")
async def archive_item(item_id: str, request: Request,
                       user: dict = Depends(auth.current_user)):
    """Out of the way, not gone. Documentation hangs off these things, and a
    machine that left the building is often exactly what you need to look up a
    year later."""
    item, _ = _item_for(user, item_id)
    body = await request.json() if await request.body() else {}
    archived = bool(body.get("archived", True))
    updated = database.set_archived(item_id, archived, by=user["email"])
    database.audit("item.archive" if archived else "item.restore",
                   user_email=user["email"], org_id=item["org_id"],
                   target=item["name"], ip=auth.client_ip(request))
    return _decorate(updated)


@app.delete("/api/items/{item_id}")
def remove_item(item_id: str, request: Request,
                user: dict = Depends(auth.current_user)):
    """Really gone, with its history and its links. Administrators only --
    archiving is what everyone else has, and it is what you want anyway."""
    item, _ = _item_for(user, item_id)
    auth.require_admin(user)
    pointing = _referred_by(item)
    if pointing:
        names = ", ".join(sorted({p["name"] for p in pointing})[:3])
        more = f" en nog {len(pointing) - 3}" if len(pointing) > 3 else ""
        raise HTTPException(
            status_code=409,
            detail=f"Hier wordt nog naar verwezen door {names}{more}. "
                   "Haal die verwijzing weg, of kies Afvoeren in plaats van verwijderen.")
    database.delete_item(item_id)
    database.audit("item.delete", user_email=user["email"], org_id=item["org_id"],
                   target=item["name"], ip=auth.client_ip(request))
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #
@app.get("/api/items/{item_id}/revisions")
def item_revisions(item_id: str, user: dict = Depends(auth.current_user)):
    _item_for(user, item_id)
    return database.list_revisions(item_id)


@app.post("/api/revisions/{revision_id}/revert")
def revert_revision(revision_id: int, request: Request,
                    user: dict = Depends(auth.current_user)):
    """Undo one recorded change, putting back what stood there before it.

    Undoing is itself a change, so it is recorded like any other -- the history
    shows what happened, never a rewritten version of it.
    """
    revision = database.get_revision(revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail="Deze wijziging bestaat niet")
    item, _ = _item_for(user, revision["item_id"])
    if not revision["changes"]:
        raise HTTPException(status_code=400,
                            detail="Bij deze regel staan geen veldwijzigingen om terug te draaien")
    # A cable moved to another port, or an adapter added, is not undone by
    # writing an old value back into a field -- so it is refused here rather
    # than quietly doing nothing.
    own = set(schema.fields_of(item["kind"])) | {"naam"}
    outside = [c["label"] for c in revision["changes"] if c["key"] not in own]
    if outside:
        raise HTTPException(status_code=400,
                            detail=f"Dit is geen veldwijziging: {outside[0]}. "
                                   "Draai dat terug waar het gebeurde.")
    name = None
    fields = {}
    for change in revision["changes"]:
        if change["key"] == "naam":
            name = change["from"] or None
        else:
            fields[change["key"]] = change["from"] or ""
    updated = database.update_item(item["id"], name=name,
                                   fields=schema.clean_form(item["kind"], fields),
                                   by=user["email"], label=_labeller(item["kind"]))
    database.audit("item.revert", user_email=user["email"], org_id=item["org_id"],
                   target=item["name"], detail=f"wijziging {revision_id}",
                   ip=auth.client_ip(request))
    return _decorate(updated)


# --------------------------------------------------------------------------- #
# Relations
# --------------------------------------------------------------------------- #
@app.post("/api/items/{item_id}/relations")
async def add_relation(item_id: str, request: Request,
                       user: dict = Depends(auth.current_user)):
    item, _ = _item_for(user, item_id)
    body = await request.json()
    other_id = (body.get("item_id") or "").strip()
    other, _ = _item_for(user, other_id)
    # Both sides have to belong to the same customer: a link across customers
    # would carry one customer's information into another's page.
    if other["org_id"] != item["org_id"]:
        raise HTTPException(status_code=400,
                            detail="Koppelen kan alleen binnen dezelfde klant")
    try:
        relation_id = database.relate(item_id, other_id,
                                      (body.get("label") or "").strip() or None,
                                      by=user["email"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    database.audit("item.relate", user_email=user["email"], org_id=item["org_id"],
                   target=item["name"], detail=other["name"], ip=auth.client_ip(request))
    return {"relation_id": relation_id, "relations": database.relations_of(item_id)}


@app.delete("/api/relations/{relation_id}")
def drop_relation(relation_id: str, request: Request,
                  user: dict = Depends(auth.current_user)):
    relation = database.get_relation(relation_id)
    if not relation:
        raise HTTPException(status_code=404, detail="Deze koppeling bestaat niet")
    item, _ = _item_for(user, relation["a_id"])
    database.unrelate(relation_id)
    database.audit("item.unrelate", user_email=user["email"], org_id=item["org_id"],
                   target=item["name"], ip=auth.client_ip(request))
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# Network adapters and switch ports
#
# A machine gets its adapters, each with the MAC that is actually on the end of
# the cable, and an adapter is patched into a port of a switch that is itself a
# configuration here. One place holds that connection, so the machine's page and
# the switch's patch list can never tell two different stories.
# --------------------------------------------------------------------------- #
# What the RMM fills in on an adapter it reported; the rest stays yours.
RMM_ADAPTER_FIELDS = {"name", "mac", "ipv4", "ipv6"}


def port_count(item: dict) -> int:
    try:
        return int(item["fields"].get("ports") or 0)
    except (TypeError, ValueError):
        return 0


def has_ports(item: dict) -> bool:
    return item["kind"] == "network" and (item["fields"].get("role") == "Switch"
                                          or port_count(item) > 0)


def _adapter_for(user: dict, adapter_id: str) -> tuple:
    adapter = database.get_adapter(adapter_id)
    if not adapter:
        raise HTTPException(status_code=404, detail="Deze netwerkadapter bestaat niet")
    item, _ = _item_for(user, adapter["item_id"])
    return adapter, item


@app.get("/api/items/{item_id}/adapters")
def item_adapters(item_id: str, user: dict = Depends(auth.current_user)):
    _item_for(user, item_id)
    return database.list_adapters(item_id)


@app.post("/api/items/{item_id}/adapters")
async def add_adapter(item_id: str, request: Request,
                      user: dict = Depends(auth.current_user)):
    item, _ = _item_for(user, item_id)
    if item["kind"] not in schema.adapter_kinds():
        raise HTTPException(status_code=400,
                            detail=f"Een {schema.kind(item['kind'])['label'].lower()} "
                                   "heeft geen netwerkadapters")
    body = await request.json()
    values = {k: (str(body.get(k) or "").strip()) for k in database.ADAPTER_FIELDS}
    if not values["name"] and not values["mac"]:
        raise HTTPException(status_code=400, detail="Geef de adapter een naam of een MAC-adres")
    adapter = database.add_adapter(item_id, values)
    database.record(item_id, "updated",
                    [{"key": "adapter", "label": "Netwerkadapter toegevoegd",
                      "from": "", "to": values["name"] or values["mac"]}],
                    by=user["email"])
    database.audit("adapter.add", user_email=user["email"], org_id=item["org_id"],
                   target=item["name"], detail=values["name"] or values["mac"],
                   ip=auth.client_ip(request))
    return adapter


@app.patch("/api/adapters/{adapter_id}")
async def edit_adapter(adapter_id: str, request: Request,
                       user: dict = Depends(auth.current_user)):
    adapter, item = _adapter_for(user, adapter_id)
    body = await request.json()
    values = {k: str(body.get(k) or "").strip() for k in database.ADAPTER_FIELDS if k in body}
    if adapter["source"] == "rmm":
        # Name, MAC and addresses come from the machine itself. Accepting a new
        # value here would mean showing it until the next sync quietly replaced
        # it again, which is worse than saying no.
        values = {k: v for k, v in values.items() if k not in RMM_ADAPTER_FIELDS}
    updated, changes = database.update_adapter(adapter_id, values)
    if changes:
        database.record(item["id"], "updated", changes, by=user["email"])
    return updated


@app.delete("/api/adapters/{adapter_id}")
def remove_adapter(adapter_id: str, request: Request,
                   user: dict = Depends(auth.current_user)):
    adapter, item = _adapter_for(user, adapter_id)
    if adapter["source"] == "rmm":
        raise HTTPException(status_code=400,
                            detail="Deze adapter komt uit de RMM en verdwijnt vanzelf "
                                   "zodra de machine hem niet meer heeft")
    database.delete_adapter(adapter_id)
    database.record(item["id"], "updated",
                    [{"key": "adapter", "label": "Netwerkadapter verwijderd",
                      "from": adapter["name"] or adapter["mac"] or "", "to": ""}],
                    by=user["email"])
    database.audit("adapter.delete", user_email=user["email"], org_id=item["org_id"],
                   target=item["name"], ip=auth.client_ip(request))
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# Patching
# --------------------------------------------------------------------------- #
def _where(adapter: dict, item: dict) -> str:
    return f"{item['name']} – {adapter['name'] or adapter['mac'] or 'adapter'}"


@app.post("/api/adapters/{adapter_id}/connect")
async def connect_adapter(adapter_id: str, request: Request,
                          user: dict = Depends(auth.current_user)):
    adapter, item = _adapter_for(user, adapter_id)
    body = await request.json()
    switch, _ = _item_for(user, (body.get("switch_id") or "").strip())
    if switch["org_id"] != item["org_id"]:
        raise HTTPException(status_code=400, detail="Die switch hoort bij een andere klant")
    if not has_ports(switch):
        raise HTTPException(status_code=400,
                            detail=f"{switch['name']} is geen switch met poorten")
    try:
        number = int(body.get("port"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Kies een poortnummer")
    count = port_count(switch)
    if number < 1 or (count and number > count):
        raise HTTPException(status_code=400,
                            detail=f"{switch['name']} heeft poort 1 tot en met {count}")
    holder = database.port_holder(switch["id"], number)
    if holder and holder["id"] != adapter_id:
        raise HTTPException(status_code=409,
                            detail=f"Poort {number} is al bezet door {holder['item_name']} "
                                   f"({holder['name'] or 'adapter'})")

    was = database.port_of_adapter(adapter_id)
    database.set_port(switch["id"], number, label=body.get("label"),
                      vlan=body.get("vlan"), adapter_id=adapter_id, by=user["email"])
    moved = [{"key": "port", "label": f"{adapter['name'] or 'Adapter'} aangesloten op",
              "from": f"{was['switch_name']} poort {was['number']}" if was else "",
              "to": f"{switch['name']} poort {number}"}]
    database.record(item["id"], "updated", moved, by=user["email"])
    # The switch's own history should show it too: its patch list changed.
    database.record(switch["id"], "updated",
                    [{"key": "port", "label": f"Poort {number}",
                      "from": "", "to": _where(adapter, item)}], by=user["email"])
    database.audit("port.connect", user_email=user["email"], org_id=item["org_id"],
                   target=f"{switch['name']} poort {number}", detail=_where(adapter, item),
                   ip=auth.client_ip(request))
    return database.list_adapters(item["id"])


@app.post("/api/adapters/{adapter_id}/disconnect")
def disconnect_adapter(adapter_id: str, request: Request,
                       user: dict = Depends(auth.current_user)):
    adapter, item = _adapter_for(user, adapter_id)
    was = database.port_of_adapter(adapter_id)
    if not was:
        return database.list_adapters(item["id"])
    database.set_port(was["switch_id"], was["number"], clear_adapter=True, by=user["email"])
    database.record(item["id"], "updated",
                    [{"key": "port", "label": f"{adapter['name'] or 'Adapter'} losgekoppeld van",
                      "from": f"{was['switch_name']} poort {was['number']}", "to": ""}],
                    by=user["email"])
    database.record(was["switch_id"], "updated",
                    [{"key": "port", "label": f"Poort {was['number']}",
                      "from": _where(adapter, item), "to": ""}], by=user["email"])
    database.audit("port.disconnect", user_email=user["email"], org_id=item["org_id"],
                   target=f"{was['switch_name']} poort {was['number']}",
                   ip=auth.client_ip(request))
    return database.list_adapters(item["id"])


@app.get("/api/items/{item_id}/ports")
def switch_ports(item_id: str, user: dict = Depends(auth.current_user)):
    item, _ = _item_for(user, item_id)
    if not has_ports(item):
        raise HTTPException(status_code=400, detail="Dit apparaat heeft geen poortenlijst")
    return database.ports_of(item_id, port_count(item))


@app.patch("/api/items/{item_id}/ports/{number}")
async def edit_port(item_id: str, number: int, request: Request,
                    user: dict = Depends(auth.current_user)):
    """A port's own label and VLAN, and unpatching from the switch's side."""
    item, _ = _item_for(user, item_id)
    if not has_ports(item):
        raise HTTPException(status_code=400, detail="Dit apparaat heeft geen poortenlijst")
    body = await request.json()
    clear = body.get("adapter_id", "keep") is None
    if clear:
        holder = database.port_holder(item_id, number)
        if holder:
            database.record(item_id, "updated",
                            [{"key": "port", "label": f"Poort {number}",
                              "from": f"{holder['item_name']} – {holder['name'] or 'adapter'}",
                              "to": ""}], by=user["email"])
    database.set_port(item_id, number, label=body.get("label"), vlan=body.get("vlan"),
                      clear_adapter=clear, by=user["email"])
    return database.ports_of(item_id, port_count(item))


# --------------------------------------------------------------------------- #
# The vault
#
# A password is an item like any other -- same history, same access, same links
# -- except for the password itself, which lives encrypted in its own table and
# leaves it one at a time, on purpose, with a line in the log each time.
# --------------------------------------------------------------------------- #
def _secret_field(user: dict, item_id: str, field: str) -> tuple:
    """The item and the field a secret belongs to.

    A vault entry keeps its password under "main"; a type defined here can have
    several, each under its own field. Anything else has none at all, and says
    so rather than quietly storing something nobody will find again.
    """
    item, org = _item_for(user, item_id)
    if field == "main":
        if item["kind"] != "password":
            raise HTTPException(status_code=400, detail="Dit item is geen wachtwoord")
    elif field not in schema.secret_fields_of(item["kind"]):
        raise HTTPException(status_code=400,
                            detail=f"Dit item heeft geen wachtwoordveld “{field}”")
    return item, org


@app.get("/api/vault")
def vault_state(user: dict = Depends(auth.current_user)):
    """Where the master key lives. An operator should know whether a backup of
    the database also contains the key that opens it."""
    auth.require_admin(user)
    return vault.state()


@app.put("/api/items/{item_id}/secret")
async def set_secret(item_id: str, request: Request, field: str = "main",
                     user: dict = Depends(auth.current_user)):
    item, _ = _secret_field(user, item_id, field)
    body = await request.json()
    password = body.get("password") or ""
    if not password:
        raise HTTPException(status_code=400, detail="Er is geen wachtwoord opgegeven")
    had = database.secret_state(item_id, field)["has_secret"]
    database.put_secret(item_id, vault.seal(password), by=user["email"], field=field)
    # The history says that it changed and when -- never what it was, and not
    # even how long it is, which is more than a bystander should learn.
    database.record(item_id, "updated",
                    [{"key": "secret", "label": _secret_label(item, field),
                      "from": "ingesteld" if had else "", "to": "gewijzigd" if had else "ingesteld"}],
                    by=user["email"])
    database.audit("secret.write", user_email=user["email"], org_id=item["org_id"],
                   target=item["name"], detail=_secret_label(item, field),
                   ip=auth.client_ip(request))
    return database.secret_state(item_id, field)


def _secret_label(item: dict, field: str) -> str:
    return "Wachtwoord" if field == "main" else schema.label_of(item["kind"], field)


@app.get("/api/items/{item_id}/secret")
def read_secret(item_id: str, request: Request, field: str = "main",
                user: dict = Depends(auth.current_user)):
    """Hand over one password, and write down that it happened.

    This is the only way a secret leaves the server, which is what makes the
    log worth anything: every reading of every password is one line, with who
    and from where.
    """
    item, _ = _secret_field(user, item_id, field)
    record = database.get_secret(item_id, field)
    if not record:
        raise HTTPException(status_code=404, detail="Er staat nog geen wachtwoord in")
    try:
        password = vault.unseal(record)
    except Exception:
        # A wrong master key, or a record that was tampered with. Both mean the
        # same thing to the person looking at it: this cannot be opened here.
        log.warning("could not open the secret of %s", item_id)
        raise HTTPException(
            status_code=500,
            detail="Dit wachtwoord kan niet geopend worden. Klopt DOC_SECRET_KEY nog?")
    database.audit("secret.read", user_email=user["email"], org_id=item["org_id"],
                   target=item["name"], detail=_secret_label(item, field),
                   ip=auth.client_ip(request))
    return JSONResponse({"password": password}, headers={"Cache-Control": "no-store"})


# --------------------------------------------------------------------------- #
# Search
#
# Across every customer you may see, because the question is usually the other
# way round: you have a serial number, an IP or a MAC address in front of you
# and you want to know *whose* it is. Passwords are searchable by name and by
# what they are for -- never by their contents, which the server does not read
# for this and could not hand over here anyway.
# --------------------------------------------------------------------------- #
SEARCH_LIMIT = 60


def _snippet(text: str, needle: str, width: int = 90) -> str:
    """The matching bit with a little around it, so a hit explains itself."""
    at = text.lower().find(needle)
    if at < 0:
        return text[:width]
    start = max(0, at - width // 3)
    end = min(len(text), at + len(needle) + width)
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


@app.get("/api/search")
def search(q: str = "", user: dict = Depends(auth.current_user)):
    needle = (q or "").strip().lower()
    if len(needle) < 2:
        return {"query": q, "results": [], "short": True}

    orgs = database.list_orgs() if user.get("is_admin") else database.user_orgs(user["email"])
    results = []
    for org in orgs:
        for item in database.list_items(org["id"], include_archived=True):
            fields = schema.fields_of(item["kind"])
            hits = []
            if needle in item["name"].lower():
                hits.append({"where": "Naam", "text": item["name"]})
            for key, value in item["fields"].items():
                text = str(value)
                if needle in text.lower():
                    hits.append({"where": schema.label_of(item["kind"], key),
                                 "text": _snippet(text, needle)})
            # What the RMM knows counts too: a serial number is exactly the kind
            # of thing you arrive with.
            for key, value in (item["rmm"] or {}).items():
                spec = next((f for f in fields.values() if f.get("rmm") == key), None)
                if spec and isinstance(value, str) and needle in value.lower():
                    hits.append({"where": spec["label"], "text": value})
            if item["kind"] in schema.adapter_kinds():
                for adapter in database.list_adapters(item["id"]):
                    for key in ("mac", "ipv4", "ipv6", "name"):
                        value = adapter.get(key) or ""
                        if needle in value.lower():
                            hits.append({"where": f"{adapter['name'] or 'Adapter'} "
                                                  f"({database.ADAPTER_FIELDS[key]})",
                                         "text": value})
            if hits:
                results.append({
                    "id": item["id"], "kind": item["kind"], "name": item["name"],
                    "archived": item["archived"],
                    "org_id": org["id"], "org_name": org["name"],
                    "hits": hits[:3],
                })
    # A name match is what you meant more often than a match halfway down a
    # document, so those come first.
    results.sort(key=lambda r: (r["hits"][0]["where"] != "Naam", r["name"].lower()))
    return {"query": q, "results": results[:SEARCH_LIMIT],
            "total": len(results), "short": False}


# --------------------------------------------------------------------------- #
# Types you define yourself
#
# The built-in kinds cover equipment and the customer's own parts. Everything
# else an MSP writes down -- a Microsoft 365 tenant, a backup job, a certificate
# -- differs per shop, so it is defined here rather than guessed at. A type is
# a label and a list of fields; the things made from it live in the same table
# as everything else, which is why they get the history, the links, the search
# and the access rules without a line of new code.
# --------------------------------------------------------------------------- #
RESERVED_KEYS = {"naam", "id", "kind", "org_id", "secret", "port", "adapter"}


def _clean_type(body: dict, existing: dict | None) -> dict:
    label = (body.get("label") or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="Geef het type een naam")
    plural = (body.get("plural") or "").strip() or f"{label}en"

    fields, seen = [], set()
    for raw in body.get("fields") or []:
        flabel = (raw.get("label") or "").strip()
        if not flabel:
            continue
        ftype = raw.get("type") or "text"
        if ftype not in schema.CUSTOM_FIELD_TYPES:
            raise HTTPException(status_code=400, detail=f"Onbekend soort veld: {ftype}")
        key = (raw.get("key") or "").strip() or schema.slug(flabel).replace("-", "_")
        if key in RESERVED_KEYS:
            key = f"f_{key}"
        # Two fields with one key would overwrite each other on save, silently.
        base, n = key, 2
        while key in seen:
            key, n = f"{base}_{n}", n + 1
        seen.add(key)
        field = {"key": key, "label": flabel, "type": ftype}
        if ftype == "select":
            options = [o.strip() for o in (raw.get("options") or []) if str(o).strip()]
            if not options:
                raise HTTPException(status_code=400,
                                    detail=f"Geef keuzes op voor het veld “{flabel}”")
            field["options"] = options
        if ftype == "ref":
            target = raw.get("ref")
            if not schema.kind(target):
                raise HTTPException(status_code=400,
                                    detail=f"Het veld “{flabel}” verwijst naar een "
                                           "soort die niet bestaat")
            field["ref"] = target
        if ftype == "list" and raw.get("labels"):
            field["labels"] = [str(o).strip() for o in raw["labels"] if str(o).strip()]
        if raw.get("hint"):
            field["hint"] = str(raw["hint"]).strip()
        if raw.get("icon"):
            field["icon"] = str(raw["icon"]).strip()
        if raw.get("long"):
            field["long"] = True
        if raw.get("expiry") and ftype == "date":
            field["expiry"] = True
        fields.append(field)

    if not fields:
        raise HTTPException(status_code=400, detail="Een type zonder velden legt niets vast")

    # A field that is new has no key yet, so the form names its column by
    # label; either spelling is accepted and stored as the key.
    # A secret has no value on the item, so as a column it would only ever be
    # empty -- and a list is exactly where a secret must never appear.
    keys = {f["key"] for f in fields if f["type"] != "secret"}
    by_label = {f["label"]: f["key"] for f in fields if f["type"] != "secret"}
    columns = []
    for want in body.get("columns") or []:
        key = want if want in keys else by_label.get(want)
        if key and key not in columns:
            columns.append(key)
    columns = columns[:4]
    return {"label": label, "plural": plural,
            "icon": (body.get("icon") or "layers").strip(),
            "sub": (body.get("sub") or "").strip(),
            "backref": (body.get("backref") or "").strip() or "Wat hiernaar verwijst",
            "adapters": bool(body.get("adapters")),
            "columns": columns, "fields": fields}


@app.get("/api/types")
def list_types(user: dict = Depends(auth.current_user)):
    """Everything that can be documented: the built-in kinds, marked as such,
    and the ones defined here."""
    return {"built_in": [{"id": name, **spec} for name, spec in schema.BUILT_IN.items()],
            "custom": [{**database.get_item_type(t["id"]), **schema.custom()[t["id"]],
                        "id": t["id"], "count": database.items_of_kind(t["id"])}
                       for t in database.list_item_types()],
            "field_types": schema.CUSTOM_FIELD_TYPES}


@app.post("/api/types")
async def create_type(request: Request, user: dict = Depends(auth.current_user)):
    auth.require_admin(user)
    body = await request.json()
    spec = _clean_type(body, None)
    type_id = schema.slug(body.get("id") or spec["label"])
    if schema.kind(type_id):
        raise HTTPException(status_code=409,
                            detail=f"Er is al een soort met de naam “{spec['label']}”")
    database.save_item_type(type_id, spec, by=user["email"], creating=True)
    schema.forget_custom()
    database.audit("type.create", user_email=user["email"], target=spec["label"],
                   detail=f"{len(spec['fields'])} velden", ip=auth.client_ip(request))
    return {"id": type_id, **schema.custom()[type_id]}


@app.patch("/api/types/{type_id}")
async def edit_type(type_id: str, request: Request,
                    user: dict = Depends(auth.current_user)):
    auth.require_admin(user)
    existing = database.get_item_type(type_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Dit type bestaat niet")
    body = await request.json()
    spec = _clean_type(body, existing)
    # A field that disappears takes what was filled in with it, so say which
    # ones and how much rather than letting it be found out later.
    gone = {f["key"] for f in existing["fields"]} - {f["key"] for f in spec["fields"]}
    if gone and not body.get("confirm_removals"):
        filled = {}
        for item in database.rows("SELECT fields_json FROM items WHERE kind=?", (type_id,)):
            stored = json.loads(item["fields_json"] or "{}")
            for key in gone:
                if stored.get(key):
                    filled[key] = filled.get(key, 0) + 1
        if filled:
            names = ", ".join(f"“{f['label']}” ({filled[f['key']]}×)"
                              for f in existing["fields"] if f["key"] in filled)
            raise HTTPException(status_code=409,
                                detail=f"Deze velden zijn ingevuld en gaan verloren: {names}")
    database.save_item_type(type_id, spec, by=user["email"], creating=False)
    schema.forget_custom()
    database.audit("type.update", user_email=user["email"], target=spec["label"],
                   ip=auth.client_ip(request))
    return {"id": type_id, **schema.custom()[type_id]}


@app.delete("/api/types/{type_id}")
def remove_type(type_id: str, request: Request,
                user: dict = Depends(auth.current_user)):
    auth.require_admin(user)
    existing = database.get_item_type(type_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Dit type bestaat niet")
    count = database.items_of_kind(type_id)
    if count:
        raise HTTPException(
            status_code=409,
            detail=f"Er {'is' if count == 1 else 'zijn'} nog {count} "
                   f"{'item' if count == 1 else 'items'} van dit type. Voer die eerst af "
                   "of verwijder ze.")
    database.delete_item_type(type_id)
    schema.forget_custom()
    database.audit("type.delete", user_email=user["email"], target=existing["label"],
                   ip=auth.client_ip(request))
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# Settings, and updating this server
#
# What an administrator can change without touching the container: the link
# with the RMM, Microsoft 365, the public address, how passwords are generated
# and how long one stays on screen, and when a date starts to warn. What decides
# whether anyone can reach this page at all -- the proxy, cookies, the port, the
# bootstrap administrators -- stays in the environment and is only shown here,
# because changing it from here could lock the door behind you.
# --------------------------------------------------------------------------- #
@app.get("/api/config")
def ui_config(user: dict = Depends(auth.current_user)):
    """What every signed-in browser needs to know: how to make a password, how
    long to show one, and when a date starts to warn."""
    return settings.public()


def _environment() -> dict:
    """The settings that stay in the container's hands, for display only."""
    return {
        "DOC_TRUST_PROXY": auth.trust_proxy(),
        "DOC_PROXY_IPS": os.environ.get("DOC_PROXY_IPS", "*"),
        "DOC_SECURE_COOKIES": os.environ.get("DOC_SECURE_COOKIES", "1") not in ("0", "false", "no"),
        "DOC_DEV_LOGIN": dev_login_enabled(),
        "DOC_BOOTSTRAP_ADMIN": sorted(auth.bootstrap_admins()),
        "DOC_SESSION_DAYS": auth.SESSION_DAYS,
    }


@app.get("/api/admin/settings")
def admin_settings(user: dict = Depends(auth.current_user)):
    auth.require_admin(user)
    return {"settings": settings.describe(), "environment": _environment(),
            "vault": vault.state(), "version": VERSION,
            "m365_redirect": m365.redirect_uri()}


def _check_settings(pending: dict) -> None:
    """Refuse a combination that would leave something broken, before any of
    it is written."""
    for key, value in pending.items():
        spec = settings.SPEC[key]
        if spec["type"] == "url" and value and not str(value).startswith(("http://", "https://")):
            raise HTTPException(status_code=400,
                                detail=f"{key} moet met http:// of https:// beginnen")
        if spec["type"] == "int":
            try:
                number = int(str(value).strip())
            except ValueError:
                raise HTTPException(status_code=400, detail=f"{key} moet een getal zijn")
            if not spec.get("min", number) <= number <= spec.get("max", number):
                raise HTTPException(status_code=400,
                                    detail=f"{key} moet tussen {spec['min']} en {spec['max']} liggen")

    # The generator as a whole, with what is being saved laid over what is set.
    merged = {k: settings.get(k) for k in settings.SPEC if k.startswith("PW_")}
    merged.update({k: settings._coerce(k, v) for k, v in pending.items() if k.startswith("PW_")})
    classes = [k for k in ("PW_LOWER", "PW_UPPER", "PW_DIGITS", "PW_SYMBOLS") if merged[k]]
    if not classes:
        raise HTTPException(status_code=400,
                            detail="Kies minstens één soort teken voor de generator")
    if merged["PW_SYMBOLS"] and not str(merged["PW_SYMBOL_SET"]).strip():
        raise HTTPException(status_code=400,
                            detail="Leestekens staan aan, maar er zijn er geen opgegeven")
    if merged["PW_EACH_CLASS"] and merged["PW_LENGTH"] < len(classes):
        raise HTTPException(status_code=400,
                            detail=f"Met {len(classes)} verplichte soorten tekens moet een "
                                   f"wachtwoord minstens {len(classes)} lang zijn")


@app.put("/api/admin/settings")
async def save_admin_settings(request: Request, user: dict = Depends(auth.current_user)):
    auth.require_admin(user)
    body = await request.json()
    clear = set(body.pop("clear", None) or [])
    unknown = [k for k in list(body) + list(clear) if k not in settings.SPEC]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Onbekende instelling: {unknown[0]}")
    fixed = [k for k in list(body) + list(clear) if settings.from_environment(k)]
    if fixed:
        raise HTTPException(status_code=409,
                            detail=f"{fixed[0]} staat vast in de omgeving van de container "
                                   "en kan hier niet worden gewijzigd")
    # An empty secret in the form means "leave it", not "wipe it": the page
    # never receives the value, so it cannot send it back.
    pending = {k: v for k, v in body.items()
               if not (settings.SPEC[k]["type"] == "secret" and not v)}
    _check_settings(pending)

    for key, value in pending.items():
        settings.put(key, value)
    for key in clear:
        settings.put(key, "")
    changed = sorted(set(pending) | clear)
    if changed:
        database.audit("settings.update", user_email=user["email"],
                       detail=", ".join(changed), ip=auth.client_ip(request))
    # A freshly configured link should show that it works, not in a quarter of
    # an hour.
    if any(k.startswith("DOC_RMM_") for k in changed) and rmm.configured():
        asyncio.create_task(asyncio.to_thread(rmm.sync))
    return {"saved": changed, "settings": settings.describe()}


@app.post("/api/admin/rmm-test")
def test_rmm(user: dict = Depends(auth.current_user)):
    """Try the link with what is saved now, and say plainly which part fails."""
    auth.require_admin(user)
    if not rmm.configured():
        return {"ok": False, "detail": "Vul eerst het adres en de API-sleutel in"}
    try:
        orgs = rmm.fetch_orgs()
    except Exception as exc:
        return {"ok": False, "detail": rmm._explain(exc)}
    return {"ok": True, "detail": f"Verbonden: de RMM kent {len(orgs)} "
                                  f"{'klant' if len(orgs) == 1 else 'klanten'}"}


@app.get("/api/admin/update")
def update_status(user: dict = Depends(auth.current_user)):
    auth.require_admin(user)
    from . import docker_update
    return {"version": VERSION, **docker_update.status()}


@app.post("/api/admin/update/check")
def update_check(request: Request, user: dict = Depends(auth.current_user)):
    auth.require_admin(user)
    from . import docker_update
    try:
        return {"version": VERSION, **docker_update.check()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Controleren lukte niet: {exc}")


@app.post("/api/admin/update/apply")
def update_apply(request: Request, user: dict = Depends(auth.current_user)):
    auth.require_admin(user)
    from . import docker_update
    if not docker_update.available():
        raise HTTPException(status_code=409,
                            detail="Bijwerken vanuit de pagina kan hier niet: de Docker-socket "
                                   "is niet aan deze container gekoppeld")
    try:
        result = docker_update.start()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bijwerken lukte niet: {exc}")
    database.audit("server.update", user_email=user["email"],
                   detail=f"van {VERSION}", ip=auth.client_ip(request))
    return {"version": VERSION, **result}


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
