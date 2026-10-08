"""A customer's Microsoft 365, read from Microsoft Graph.

Each customer's tenant is documented on one item of the kind ``m365`` (see
schema.M365): what somebody types there -- who the partner is, how the tenant
is backed up, who may reach which shared mailbox -- and what Microsoft 365
itself knows, which is fetched rather than typed: the domains, the
subscriptions and when they renew, every user with their licences, the shared
mailboxes, the groups and Teams, the SharePoint sites, the app registrations
with the date their secrets run out, and whether security defaults or
Conditional Access are on.

It is read with an app registration in the customer's own tenant -- the same
way the App Secret Monitor reads it -- with read-only *application*
permissions and admin consent: a tenant id, a client id and a client secret.
Nothing is ever written to the tenant. Each part is fetched on its own, so a
permission that was not granted costs that part only, and the page says which
permission it needs.
"""
from __future__ import annotations

import datetime
import logging
import os
import sqlite3
import time

import httpx

from . import database, schema, vault

log = logging.getLogger("leuffendoc.m365")

# Microsoft's addresses; the environment can point them elsewhere, which is
# what the end-to-end tests do with a Graph of their own.
GRAPH = os.environ.get("DOC_M365_GRAPH_URL") or "https://graph.microsoft.com/v1.0"
LOGIN = os.environ.get("DOC_M365_LOGIN_URL") or "https://login.microsoftonline.com"
_TIMEOUT = 20.0
_MAX_MAILBOX_CHECKS = 300          # mailboxSettings is one call per mailbox
_MAX_MEMBER_LISTS = 80             # members are one call per group

# What the app registration needs, and what for -- shown when connecting.
PERMISSIONS = [
    ("Organization.Read.All", "de tenant, de domeinen en de abonnementen"),
    ("User.Read.All", "de gebruikers en hun licenties"),
    ("GroupMember.Read.All", "groepen, Teams en distributielijsten met hun leden"),
    ("MailboxSettings.Read", "welke mailboxen gedeeld zijn"),
    ("Application.Read.All", "de app-registraties en wanneer hun secrets verlopen"),
    ("Policy.Read.All", "security defaults en Conditional Access"),
    ("Sites.Read.All", "de SharePoint-sites (mag ontbreken)"),
]

# The names on the invoice for the subscriptions an MSP meets every day; any
# other is shown by its part number.
SKUS = {
    "SPB": "Microsoft 365 Business Premium",
    "O365_BUSINESS_PREMIUM": "Microsoft 365 Business Standard",
    "O365_BUSINESS_ESSENTIALS": "Microsoft 365 Business Basic",
    "O365_BUSINESS": "Microsoft 365 Apps for business",
    "OFFICESUBSCRIPTION": "Microsoft 365 Apps for enterprise",
    "SPE_E3": "Microsoft 365 E3", "SPE_E5": "Microsoft 365 E5",
    "SPE_F1": "Microsoft 365 F3", "M365_F1": "Microsoft 365 F1",
    "ENTERPRISEPACK": "Office 365 E3", "ENTERPRISEPREMIUM": "Office 365 E5",
    "STANDARDPACK": "Office 365 E1", "DESKLESSPACK": "Office 365 F3",
    "EXCHANGESTANDARD": "Exchange Online (Plan 1)", "EXCHANGEENTERPRISE": "Exchange Online (Plan 2)",
    "EXCHANGEDESKLESS": "Exchange Online Kiosk", "EXCHANGEARCHIVE_ADDON": "Exchange Online Archiving",
    "EMS": "Enterprise Mobility + Security E3", "EMSPREMIUM": "Enterprise Mobility + Security E5",
    "AAD_PREMIUM": "Microsoft Entra ID P1", "AAD_PREMIUM_P2": "Microsoft Entra ID P2",
    "INTUNE_A": "Microsoft Intune Plan 1", "ATP_ENTERPRISE": "Microsoft Defender for Office 365 (Plan 1)",
    "THREAT_INTELLIGENCE": "Microsoft Defender for Office 365 (Plan 2)",
    "DEFENDER_ENDPOINT_P1": "Microsoft Defender for Endpoint P1",
    "MDATP_XPLAT": "Microsoft Defender for Endpoint P2",
    "Microsoft_Teams_Exploratory_Dept": "Microsoft Teams Exploratory",
    "TEAMS_EXPLORATORY": "Microsoft Teams Exploratory", "Teams_Ess": "Microsoft Teams Essentials",
    "MCOEV": "Teams Phone Standard", "MCOPSTN1": "Teams Calling Plan (domestic)",
    "PHONESYSTEM_VIRTUALUSER": "Teams Phone Resource Account",
    "MCOMEETADV": "Microsoft 365 Audio Conferencing",
    "POWER_BI_STANDARD": "Power BI (free)", "POWER_BI_PRO": "Power BI Pro",
    "FLOW_FREE": "Power Automate (free)", "POWERAPPS_VIRAL": "Power Apps (trial)",
    "PROJECTPROFESSIONAL": "Project Plan 3", "VISIOCLIENT": "Visio Plan 2",
    "WIN_DEF_ATP": "Microsoft Defender for Endpoint", "WIN10_VDA_E3": "Windows 10/11 Enterprise E3",
    "STREAM": "Microsoft Stream", "RIGHTSMANAGEMENT": "Azure Information Protection P1",
}


class GraphError(Exception):
    """Graph or the sign-in refused, said in a sentence somebody can act on."""


def product_name(part_number: str) -> str:
    return SKUS.get(part_number or "", part_number or "onbekend")


# --------------------------------------------------------------------------- #
# Talking to Graph
# --------------------------------------------------------------------------- #
def token(tenant_id: str, client_id: str, secret: str) -> str:
    try:
        r = httpx.post(f"{LOGIN}/{tenant_id}/oauth2/v2.0/token", timeout=_TIMEOUT, data={
            "grant_type": "client_credentials", "client_id": client_id,
            "client_secret": secret, "scope": "https://graph.microsoft.com/.default"})
    except httpx.HTTPError as exc:
        raise GraphError(f"geen verbinding met Microsoft ({type(exc).__name__})") from exc
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200 or "access_token" not in body:
        raise GraphError(_explain_signin(body.get("error_description") or body.get("error") or f"HTTP {r.status_code}"))
    return body["access_token"]


def _explain_signin(text: str) -> str:
    """Microsoft's sign-in errors start with a code; the code says what to do."""
    hints = {
        "AADSTS7000215": "het client secret klopt niet",
        "AADSTS7000222": "het client secret is verlopen — maak een nieuw aan",
        "AADSTS700016": "deze app-registratie bestaat niet in deze tenant (verkeerde client-ID, of nog geen toestemming)",
        "AADSTS90002": "deze tenant bestaat niet (controleer de tenant-ID)",
        "AADSTS900023": "de tenant-ID is geen geldige ID of domeinnaam",
        "AADSTS65001": "de beheerder heeft nog geen toestemming gegeven voor deze app",
    }
    for code, said in hints.items():
        if code in text:
            return f"{said} ({code})"
    return text.splitlines()[0][:200]


def _get(client: httpx.Client, url: str, **params) -> dict:
    try:
        r = client.get(url if url.startswith("http") else GRAPH + url, params=params or None)
    except httpx.HTTPError as exc:
        raise GraphError(f"geen antwoord van Microsoft Graph ({type(exc).__name__})") from exc
    if r.status_code == 403:
        raise GraphError("geen toestemming")
    if r.status_code == 404:
        raise GraphError("niet gevonden")
    if r.status_code >= 400:
        try:
            message = r.json().get("error", {}).get("message") or f"HTTP {r.status_code}"
        except ValueError:
            message = f"HTTP {r.status_code}"
        raise GraphError(message[:200])
    return r.json()


def _all(client: httpx.Client, url: str, **params) -> list:
    """Every page of a list."""
    out: list = []
    body = _get(client, url, **params)
    for _ in range(100):
        out.extend(body.get("value") or [])
        nxt = body.get("@odata.nextLink")
        if not nxt:
            break
        body = _get(client, nxt)
    return out


def _date(value) -> str:
    """An ISO timestamp as the date it falls on."""
    return str(value or "")[:10]


# --------------------------------------------------------------------------- #
# Reading a tenant
# --------------------------------------------------------------------------- #
def collect(tenant_id: str, client_id: str, secret: str) -> dict:
    """Everything this tenant lets us read, as the fields of an m365 item (see
    schema.M365), plus ``problems``: what could not be read, and why."""
    bearer = token(tenant_id, client_id, secret)
    out: dict = {"problems": []}
    with httpx.Client(timeout=_TIMEOUT, headers={"Authorization": f"Bearer {bearer}"}) as client:
        def part(name: str, permission: str, fn) -> None:
            try:
                fn()
            except GraphError as exc:
                said = f"{name}: {exc}"
                if str(exc) == "geen toestemming":
                    said += f" — geef de app {permission}"
                out["problems"].append(said)
                log.info("m365 %s: %s", tenant_id, said)

        skus: dict = {}

        def tenant() -> None:
            org = (_all(client, "/organization") or [{}])[0]
            out["tenant_id"] = org.get("id") or tenant_id
            out["tenant_name"] = org.get("displayName") or ""
            domains = org.get("verifiedDomains") or []
            default = next((d["name"] for d in domains if d.get("isDefault")), "")
            out["primary_domain"] = default
            out["domains"] = [{"label": "standaard" if d.get("isDefault") else
                               ("start" if d.get("isInitial") else ""), "value": d.get("name") or ""}
                              for d in sorted(domains, key=lambda d: (not d.get("isDefault"), d.get("name") or ""))
                              if d.get("name")]

        def subscriptions() -> None:
            renewals: dict = {}
            try:
                for s in _all(client, "/directory/subscriptions"):
                    if s.get("skuId"):
                        renewals[s["skuId"]] = s
            except GraphError:
                pass                       # the counts below still come; only the dates are missing
            rows = []
            for sku in _all(client, "/subscribedSkus"):
                skus[sku.get("skuId")] = product_name(sku.get("skuPartNumber"))
                seats = (sku.get("prepaidUnits") or {}).get("enabled") or 0
                if not seats and not sku.get("consumedUnits"):
                    continue                  # a free trial nobody took
                life = renewals.get(sku.get("skuId")) or {}
                rows.append({"product": skus[sku.get("skuId")], "seats": str(seats),
                             "used": str(sku.get("consumedUnits") or 0),
                             "renews": _date(life.get("nextLifecycleDateTime")),
                             "status": {"Enabled": "Actief", "Warning": "Verloopt", "Suspended": "Opgeschort",
                                        "Deleted": "Opgezegd", "LockedOut": "Geblokkeerd"}
                                       .get(sku.get("capabilityStatus") or "", sku.get("capabilityStatus") or "")})
            out["subscriptions"] = sorted(rows, key=lambda r: r["product"].lower())

        candidates: list = []

        def users() -> None:
            rows = []
            for u in _all(client, "/users", **{"$select": "id,displayName,userPrincipalName,mail,accountEnabled,"
                                                         "assignedLicenses,jobTitle,userType",
                                              "$top": "999"}):
                licences = [skus.get(l.get("skuId"), "licentie") for l in u.get("assignedLicenses") or []]
                # A shared mailbox is a user without a sign-in or a licence;
                # which ones are, the mailbox settings say below.
                if not u.get("accountEnabled") and not licences and u.get("mail"):
                    candidates.append(u)
                    continue
                rows.append({"name": u.get("displayName") or "", "account": u.get("userPrincipalName") or "",
                             "licenses": ", ".join(sorted(licences)),
                             "job": u.get("jobTitle") or "",
                             "enabled": "Ja" if u.get("accountEnabled") else "Nee",
                             "kind": "Gast" if u.get("userType") == "Guest" else ""})
            out["users"] = sorted(rows, key=lambda r: r["name"].lower())

        def mailboxes() -> None:
            rows, missing = [], 0
            for u in candidates[:_MAX_MAILBOX_CHECKS]:
                try:
                    purpose = (_get(client, f"/users/{u['id']}/mailboxSettings", **{"$select": "userPurpose"})
                               .get("userPurpose") or "")
                except GraphError as exc:
                    if str(exc) == "geen toestemming":
                        raise
                    missing += 1
                    continue
                kind = {"shared": "Gedeeld", "room": "Ruimte", "equipment": "Apparatuur"}.get(purpose)
                if kind:
                    rows.append({"mailbox": u.get("mail") or "", "name": u.get("displayName") or "", "kind": kind})
                else:
                    # Disabled and unlicensed, but an ordinary mailbox: someone who left.
                    out.setdefault("users", []).append({
                        "name": u.get("displayName") or "", "account": u.get("userPrincipalName") or "",
                        "licenses": "", "job": u.get("jobTitle") or "", "enabled": "Nee", "kind": ""})
            order = {"Gedeeld": 0, "Ruimte": 1, "Apparatuur": 2}
            out["shared"] = sorted(rows, key=lambda r: (order[r["kind"]], r["mailbox"].lower()))
            if "users" in out:
                out["users"].sort(key=lambda r: r["name"].lower())

        def groups() -> None:
            rows, listed = [], 0
            for g in _all(client, "/groups", **{"$select": "id,displayName,mail,mailEnabled,securityEnabled,"
                                                           "groupTypes,resourceProvisioningOptions",
                                               "$top": "999"}):
                types = g.get("groupTypes") or []
                if "Team" in (g.get("resourceProvisioningOptions") or []):
                    kind = "Team"
                elif "Unified" in types:
                    kind = "Microsoft 365-groep"
                elif g.get("mailEnabled") and not g.get("securityEnabled"):
                    kind = "Distributielijst"
                elif g.get("mailEnabled"):
                    kind = "Beveiligingsgroep met mail"
                else:
                    kind = "Beveiligingsgroep"
                members = ""
                # Who is in a list or a team is what gets asked; the members of
                # a security group are a different question, and often many.
                if kind != "Beveiligingsgroep" and "DynamicMembership" not in types and listed < _MAX_MEMBER_LISTS:
                    listed += 1
                    people = _all(client, f"/groups/{g['id']}/members",
                                  **{"$select": "displayName", "$top": "999"})
                    members = ", ".join(sorted(p.get("displayName") or "" for p in people if p.get("displayName")))
                elif "DynamicMembership" in types:
                    members = "dynamisch"
                rows.append({"name": g.get("displayName") or "", "mail": g.get("mail") or "",
                             "kind": kind, "members": members[:600]})
            out["groups"] = sorted(rows, key=lambda r: (r["kind"], r["name"].lower()))

        def sites() -> None:
            rows = [{"name": s.get("displayName") or s.get("name") or "", "url": s.get("webUrl") or ""}
                    for s in _all(client, "/sites", search="*")
                    if "-my.sharepoint.com" not in (s.get("webUrl") or "")]
            out["sites"] = sorted(rows, key=lambda r: r["name"].lower())

        def apps() -> None:
            rows = []
            for a in _all(client, "/applications", **{"$select": "displayName,appId,passwordCredentials,keyCredentials",
                                                     "$top": "999"}):
                for kind, creds in (("Secret", a.get("passwordCredentials")), ("Certificaat", a.get("keyCredentials"))):
                    for c in creds or []:
                        rows.append({"app": a.get("displayName") or a.get("appId") or "", "kind": kind,
                                     "name": c.get("displayName") or "", "expires": _date(c.get("endDateTime"))})
            out["apps"] = sorted(rows, key=lambda r: (r["expires"] or "9999", r["app"].lower()))

        def security() -> None:
            policy = _get(client, "/policies/identitySecurityDefaultsEnforcementPolicy")
            out["security_defaults"] = "Aan" if policy.get("isEnabled") else "Uit"

        def conditional_access() -> None:
            states = {"enabled": "Aan", "disabled": "Uit", "enabledForReportingButNotEnforced": "Alleen rapporteren"}
            out["ca"] = sorted(({"name": p.get("displayName") or "", "state": states.get(p.get("state"), p.get("state") or "")}
                                for p in _all(client, "/identity/conditionalAccess/policies")),
                               key=lambda r: r["name"].lower())

        part("Tenant en domeinen", "Organization.Read.All", tenant)
        part("Abonnementen", "Organization.Read.All", subscriptions)
        part("Gebruikers", "User.Read.All", users)
        part("Gedeelde mailboxen", "MailboxSettings.Read", mailboxes)
        if "shared" not in out and "users" in out:
            # Which of them are shared could not be read: they are listed as
            # what they are for sure -- accounts without a sign-in.
            out["users"] = sorted(out["users"] + [
                {"name": u.get("displayName") or "", "account": u.get("userPrincipalName") or "",
                 "licenses": "", "job": u.get("jobTitle") or "", "enabled": "Nee", "kind": ""}
                for u in candidates], key=lambda r: r["name"].lower())
        part("Groepen", "GroupMember.Read.All", groups)
        part("SharePoint", "Sites.Read.All", sites)
        part("App-registraties", "Application.Read.All", apps)
        part("Security defaults", "Policy.Read.All", security)
        part("Conditional Access", "Policy.Read.All (en Entra ID P1)", conditional_access)
    out["fetched_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    return out


# --------------------------------------------------------------------------- #
# Keeping a tenant item in step
# --------------------------------------------------------------------------- #
PREFIX = "m365:"
SYNC_HOURS = 6                    # how often a linked tenant is read again
# What is compared field by field for the history; the long lists are said in
# words instead (see changes).
_PLAIN_KEYS = ["tenant_name", "primary_domain", "security_defaults"]


def _label(key: str) -> str:
    return schema.label_of("m365", key)


def connect(item: dict, tenant_id: str, client_id: str, secret: str, by: str | None) -> dict:
    """Check that the registration can read the tenant, store it (the secret
    sealed), and read it for the first time. Raises GraphError when Microsoft
    refuses, before anything is stored."""
    tenant_id, client_id, secret = tenant_id.strip(), client_id.strip(), secret.strip()
    if not (tenant_id and client_id and secret):
        raise GraphError("tenant-ID, client-ID en client secret zijn alle drie nodig")
    token(tenant_id, client_id, secret)                       # refuses here when wrong
    other = database.item_by_rmm_device(PREFIX + tenant_id.lower())
    if other and other["id"] != item["id"]:
        raise GraphError(f"deze tenant is al gekoppeld aan {other['name']}")
    database.save_m365_link(item["id"], tenant_id, client_id, vault.pack(vault.seal(secret)),
                            secret[-4:], by)
    return sync(item["id"])


def sync(item_id: str) -> dict:
    """Read the tenant again and lay it over the item: what Microsoft 365 knows
    replaces what it knew, typed fields stay, and what changed is written down
    in words."""
    link = database.m365_link(item_id)
    item = database.get_item(item_id)
    if not link or not item:
        raise GraphError("deze tenant is niet gekoppeld")
    try:
        secret = vault.unseal(vault.unpack(link["secret_sealed"]))
        data = collect(link["tenant_id"], link["client_id"], secret)
    except GraphError as exc:
        database.m365_result(item_id, ok=False, error=str(exc))
        raise
    except Exception as exc:                          # never leave a link without a status
        database.m365_result(item_id, ok=False, error=f"{type(exc).__name__}: {exc}"[:200])
        raise GraphError("het ophalen liep vast") from exc
    problems = data.pop("problems", [])
    fetched = data.pop("fetched_at", None)
    holds = [k for k in schema.M365_KEYS if k in data]
    payload = {**{k: data[k] for k in holds}, "holds": holds, "source": "m365", "fetched_at": fetched}

    device = PREFIX + link["tenant_id"].lower()
    if item.get("source") != "m365" or item.get("rmm_device_id") != device:
        try:
            database.link_rmm(item_id, device, holds, source="m365")
        except sqlite3.IntegrityError as exc:
            database.m365_result(item_id, ok=False, error="deze tenant is al aan iets anders gekoppeld")
            raise GraphError("deze tenant is al aan iets anders gekoppeld") from exc
        item = database.get_item(item_id)
    said = changes(item.get("rmm") or {}, payload)
    database.update_item(item_id, rmm=payload, rmm_keys=[k for k in _PLAIN_KEYS if k in holds],
                         by=None, source="m365", label=_label)
    if said:
        database.record(item_id, "updated", [{"key": "m365", "label": "Microsoft 365", "said": "; ".join(said)}],
                        by=None, source="m365")
    database.m365_result(item_id, ok=True, problems=problems)
    return status(item_id)


def disconnect(item_id: str) -> None:
    """Stop reading the tenant. What was read stays on the page, typed from
    now on, and the secret is gone."""
    database.unlink_rmm(item_id, schema.M365_KEYS)
    database.delete_m365_link(item_id)


def status(item_id: str) -> dict:
    link = database.m365_link(item_id)
    out = {"linked": bool(link), "permissions": [{"name": n, "for": w} for n, w in PERMISSIONS]}
    if link:
        out.update(tenant_id=link["tenant_id"], client_id=link["client_id"], secret_hint=link["secret_hint"],
                   linked_at=link["linked_at"], linked_by=link["linked_by"], last_sync=link["last_sync"],
                   last_ok=bool(link["last_ok"]), last_error=link["last_error"], problems=link["problems"])
    return out


def due() -> list:
    """The linked tenants whose last reading is older than SYNC_HOURS."""
    now = time.time()
    return [l["item_id"] for l in database.m365_links()
            if not l["last_sync"] or now - l["last_sync"] >= SYNC_HOURS * 3600]


def changes(before: dict, after: dict) -> list:
    """What changed in a tenant, in words -- who joined and who left, a
    subscription with more or fewer licences, a new shared mailbox -- rather
    than two copies of a list of fifty people."""
    if not any(k in before for k in ("users", "subscriptions", "shared", "groups", "apps")):
        return []                                    # the first reading: nothing to compare with
    said = []

    def keyed(rows, key):
        return {r.get(key): r for r in rows or [] if r.get(key)}

    old, new = keyed(before.get("users"), "account"), keyed(after.get("users"), "account")
    said += [f"Nieuwe gebruiker: {new[a]['name']}" for a in new if a not in old]
    said += [f"Weg: {old[a]['name']}" for a in old if a not in new]
    for a in new:
        if a in old and old[a].get("licenses") != new[a].get("licenses"):
            said.append(f"{new[a]['name']}: {old[a].get('licenses') or 'geen licentie'} → "
                        f"{new[a].get('licenses') or 'geen licentie'}")
        if a in old and old[a].get("enabled") != new[a].get("enabled"):
            said.append(f"{new[a]['name']}: {'kan weer aanmelden' if new[a].get('enabled') == 'Ja' else 'aanmelden geblokkeerd'}")

    old, new = keyed(before.get("subscriptions"), "product"), keyed(after.get("subscriptions"), "product")
    said += [f"Nieuw abonnement: {p} ({new[p].get('seats')})" for p in new if p not in old]
    said += [f"Abonnement weg: {p}" for p in old if p not in new]
    said += [f"{p}: {old[p].get('seats')} → {new[p].get('seats')} licenties"
             for p in new if p in old and old[p].get("seats") != new[p].get("seats")]

    for key, field, word in (("shared", "mailbox", "mailbox"), ("groups", "name", "groep")):
        old, new = keyed(before.get(key), field), keyed(after.get(key), field)
        said += [f"Nieuwe {word}: {n}" for n in new if n not in old]
        said += [f"{word.capitalize()} weg: {n}" for n in old if n not in new]

    def creds(rows):
        return {(r.get("app"), r.get("kind"), r.get("expires")) for r in rows or []}
    for app, kind, expires in sorted(creds(after.get("apps")) - creds(before.get("apps")), key=str):
        said.append(f"{app}: nieuw {kind.lower()}{f', verloopt {expires}' if expires else ''}")
    return said[:60]
