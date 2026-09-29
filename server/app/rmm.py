"""Talking to the Leuffen RMM.

The RMM is where accounts and customers live. LeuffenDoc asks it two things:

  * **who is this?** -- a single-use ticket the browser brought back, redeemed
    server-to-server with the API key, so the ticket alone is not enough to
    become anybody; and
  * **who exists, and what may they see?** -- the periodic sync, which is what
    makes access granted (or withdrawn) in the RMM show up here without a second
    administration.

Nothing here raises on a network failure by itself: the RMM being unreachable
must not take LeuffenDoc down with it, which is exactly why the Microsoft 365
sign-in exists alongside this one.
"""
from __future__ import annotations

import logging
import os
import time
import urllib.parse

import httpx

from . import database, schema, settings

log = logging.getLogger("leuffendoc.rmm")

# What the last sync did, for the status shown in the interface.
last_sync: dict = {"at": None, "ok": None, "detail": "nog niet uitgevoerd",
                   "users": 0, "orgs": 0, "devices": 0}


def _setting(key: str) -> str:
    return (os.environ.get(key) or database.get_setting(key) or "").strip()


def base_url() -> str:
    """Where *this server* reaches the RMM. Behind the same reverse proxy that
    is often an internal address."""
    return _setting("DOC_RMM_URL").rstrip("/")


def public_base_url() -> str:
    """Where *a browser* reaches the RMM. The same address in a simple setup,
    and a different one whenever the two servers talk over an internal network
    the browser knows nothing about -- send someone to that and they land
    nowhere."""
    return (_setting("DOC_RMM_PUBLIC_URL") or _setting("DOC_RMM_URL")).rstrip("/")


def api_key() -> str:
    # Stored sealed when it was entered on the settings page.
    return settings.secret("DOC_RMM_API_KEY")


def configured() -> bool:
    return bool(base_url() and api_key())


def _client() -> httpx.Client:
    # An RMM on a self-signed certificate is normal on a LAN; the operator says
    # so explicitly rather than us quietly accepting any certificate.
    verify = _setting("DOC_RMM_INSECURE_TLS") not in ("1", "true", "yes")
    return httpx.Client(timeout=15.0, verify=verify,
                        headers={"X-API-Key": api_key()})


def try_link(url: str, key: str, insecure: bool = False) -> tuple[bool, str]:
    """Whether an address and key work, before they are saved."""
    try:
        with httpx.Client(timeout=15.0, verify=not insecure, headers={"X-API-Key": key}) as client:
            r = client.get(f"{url.rstrip('/')}/api/v1/orgs")
        r.raise_for_status()
    except Exception as exc:
        explained = _explain(exc)
        return False, explained.replace(base_url() or "\x00", url)
    n = len(r.json().get("orgs", []))
    return True, f"verbonden, {n} {'klant' if n == 1 else 'klanten'}"


def handoff_url(return_to: str) -> str:
    """Where to send the browser to have the RMM identify someone."""
    return (f"{public_base_url()}/auth/sso/handoff"
            f"?return={urllib.parse.quote(return_to, safe='')}")


def exchange_ticket(ticket: str) -> dict:
    """Redeem a hand-off ticket. Returns the identity, or raises."""
    with _client() as client:
        r = client.post(f"{base_url()}/api/v1/sso/exchange", json={"ticket": ticket})
    if r.status_code == 401:
        raise PermissionError(r.json().get("detail", "De aanmeldlink is verlopen"))
    r.raise_for_status()
    return r.json()


def fetch_orgs() -> list[dict]:
    with _client() as client:
        r = client.get(f"{base_url()}/api/v1/orgs")
    r.raise_for_status()
    return r.json().get("orgs", [])


def fetch_users() -> list[dict]:
    with _client() as client:
        r = client.get(f"{base_url()}/api/v1/users")
    r.raise_for_status()
    return r.json().get("users", [])


# --------------------------------------------------------------------------- #
# Bringing identities across
# --------------------------------------------------------------------------- #
def apply_identity(identity: dict, source: str = "rmm") -> dict:
    """Store one person and the customers they may see, exactly as the RMM has
    it. Replacing their access (rather than adding to it) is deliberate: access
    taken away there has to disappear here too."""
    email = (identity.get("email") or "").strip().lower()
    if not email:
        raise ValueError("identity has no email address")
    user = database.upsert_user(email,
                                display_name=identity.get("display_name") or None,
                                is_admin=bool(identity.get("is_global_admin")),
                                source=source)
    # The role per customer comes along: a viewer there reads the
    # documentation here but does not see passwords -- administered once, in
    # the RMM, like the access itself.
    orgs = []
    for org in identity.get("orgs") or []:
        if not org.get("id"):
            continue
        orgs.append((database.upsert_org(org.get("name") or org["id"], rmm_org_id=org["id"]),
                     org.get("role") or "member"))
    database.set_user_orgs(email, orgs)
    return user


def _explain(exc: Exception) -> str:
    """What went wrong, in a sentence an administrator can act on. The library's
    own message is a URL and a link to a status-code reference, which says
    nothing about which of the three likely causes this is."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return "de RMM weigert de API-sleutel (DOC_RMM_API_KEY)"
        if code == 404:
            return ("dit adres is geen RMM, of de RMM is te oud voor deze koppeling "
                    f"({exc.request.url.path} bestaat daar niet)")
        return f"de RMM antwoordde met {code}"
    if isinstance(exc, httpx.ConnectError):
        return f"geen verbinding met {base_url()}"
    if isinstance(exc, httpx.TimeoutException):
        return f"{base_url()} antwoordt niet op tijd"
    return f"{type(exc).__name__}: {exc}"[:200]


def sync() -> dict:
    """Pull every account and its customers from the RMM."""
    if not configured():
        last_sync.update(at=time.time(), ok=None, detail="de RMM is niet ingesteld")
        return last_sync
    try:
        # Customers first, and on their own: one that nobody has been assigned
        # to yet still needs to exist here, ready to be documented.
        orgs = fetch_orgs()
        users = fetch_users()
    except Exception as exc:                       # network, TLS, a wrong key
        log.warning("sync from the RMM failed: %r", exc)
        last_sync.update(at=time.time(), ok=False, detail=_explain(exc))
        return last_sync
    for org in orgs:
        if org.get("id"):
            database.upsert_org(org.get("name") or org["id"], rmm_org_id=org["id"])
    for identity in users:
        try:
            apply_identity(identity)
        except Exception as exc:
            log.warning("could not apply %s: %r", identity.get("email"), exc)
    # Devices last: they land in the customers the round above just created.
    # A failure here does not undo the accounts and customers that did arrive,
    # which is the difference between a partly useful sync and a useless one.
    try:
        devices = sync_devices()
    except Exception as exc:
        log.warning("syncing devices from the RMM failed: %r", exc)
        last_sync.update(at=time.time(), ok=False, users=len(users), orgs=len(orgs),
                         detail=f"gebruikers en klanten gelukt, apparaten niet: {_explain(exc)}")
        return last_sync
    last_sync.update(at=time.time(), ok=True, detail="gelukt",
                     users=len(users), orgs=len(orgs), devices=devices["devices"])
    database.audit("rmm.sync", detail=f"{len(users)} gebruikers, {len(orgs)} klanten, "
                                      f"{devices['devices']} apparaten "
                                      f"({devices['new']} nieuw, {devices['gone']} verdwenen)")
    return last_sync


# --------------------------------------------------------------------------- #
# Devices becoming configurations
#
# If the RMM is there, it already knows what is in a machine. Typing that in a
# second time produces two answers to the same question, and the documented one
# is the one that goes stale. So every device becomes a configuration here, its
# hardware is shown from the RMM and kept in step, and what the RMM cannot know
# -- when it was installed and by whom, which switch port, the warranty -- is
# yours to fill in on the same page.
#
# Without an RMM none of this runs and every field is simply typed, which is
# what an installation of LeuffenDoc on its own looks like.
# --------------------------------------------------------------------------- #
def fetch_devices() -> list[dict]:
    with _client() as client:
        r = client.get(f"{base_url()}/api/v1/devices")
    r.raise_for_status()
    return r.json().get("devices", [])


def _bytes(value) -> str:
    """A size as somebody says it out loud, not as a number of bytes."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    for unit, step in (("TB", 1024 ** 4), ("GB", 1024 ** 3), ("MB", 1024 ** 2)):
        if n >= step:
            size = n / step
            text = f"{size:.1f}".rstrip("0").rstrip(".") if size < 100 else f"{round(size)}"
            return f"{text.replace('.', ',')} {unit}"
    return f"{int(n)} B"


def _storage(disks: list) -> str:
    parts = []
    for disk in disks or []:
        size = _bytes(disk.get("total"))
        if not size:
            continue
        where = (disk.get("mount") or "").rstrip("\\")
        parts.append(f"{size} ({where})" if where else size)
    return " + ".join(parts)


def _os(device: dict) -> str:
    """The operating system with its version, without saying it twice -- the
    RMM's own name for a Home Assistant box already carries its version."""
    name = (device.get("os") or "").strip()
    version = (device.get("os_version") or "").strip()
    if version and version.lower() not in name.lower():
        return f"{name} {version}".strip()
    return name


def _role(device: dict) -> str:
    """A starting guess at what kind of machine this is. It is written once, at
    the moment the configuration is created, and never again: after that it is
    whatever the person who looked at it says it is."""
    name = f"{device.get('os') or ''} {device.get('os_version') or ''}".lower()
    if "synology" in name or "dsm" in name or "truenas" in name:
        return "NAS"
    if device.get("is_server") or device.get("os_kind") == "windows_server":
        return "Server"
    if "home assistant" in name:
        return "Server"
    if device.get("os_kind") == "linux":
        return "Server"
    return "Desktop"


def device_payload(device: dict) -> dict:
    """What the RMM knows, under the names the field catalogue uses.

    Anything beyond those names (the adapters, when it was last seen) rides
    along for the pages that need it and is deliberately left out of the
    comparison that writes the history.
    """
    return {
        "cpu": device.get("cpu") or "",
        "memory": _bytes(device.get("ram_total")),
        "storage": _storage(device.get("disks")),
        "os": _os(device),
        "manufacturer": device.get("manufacturer") or "",
        "model": device.get("model") or "",
        "serial": device.get("serial") or "",
        # Not fields, but what the rest of the page and the adapters need.
        "device_id": device.get("id"),
        "hostname": device.get("hostname"),
        "online": bool(device.get("online")),
        "last_seen": device.get("last_seen"),
        "ip": device.get("ip"),
        "mac": device.get("mac"),
        "agent_version": device.get("agent_version"),
        "nics": device.get("nics") or [],
    }


# --------------------------------------------------------------------------- #
# Virtual machines on Hyper-V hosts
#
# They run no agent, so the RMM does not list them as devices -- but the host
# reports them, and they are machines the customer has. Each becomes a
# configuration of the type Virtuele machine, "Draait op" its host. Known by
# customer and name (Hyper-V gives no id), so one that moves to another host
# stays the same page and says where it runs now. A guest that has an agent of
# its own is that device already, and only gets told where it runs.
# --------------------------------------------------------------------------- #
VM_PREFIX = "hv:"
# What the history compares for a VM: how many processors it has. How much
# memory it is using right now and whether it is running are shown, but not
# written down every time they change -- that would be the whole history.
VM_KEYS = ["cpu", "manufacturer", "model"]
_VM_STATES = {"running": "Draait", "off": "Uit", "saved": "Opgeslagen", "paused": "Gepauzeerd",
              "starting": "Start op", "stopping": "Stopt"}


def vm_key(rmm_org: str, name: str) -> str:
    return f"{VM_PREFIX}{rmm_org}:{name.strip().lower()}"


def vm_payload(vm: dict, host: dict) -> dict:
    vcpu = vm.get("vcpu")
    memory = vm.get("mem_assigned") or 0
    state = str(vm.get("state") or "")
    return {"cpu": f"{vcpu} vCPU" if vcpu else "", "memory": _bytes(memory) if memory else "",
            "storage": "", "os": "", "serial": "",
            "manufacturer": "Microsoft", "model": "Hyper-V virtuele machine",
            "vm_state": _VM_STATES.get(state.lower(), state),
            "host": host.get("hostname"), "host_device_id": host.get("id")}


def _runs_on(item_id: str, host_item_id: str, always: bool, label) -> None:
    """Say where a machine runs. For a Hyper-V guest the host is the RMM's to
    say; for a machine with an agent of its own only when nobody filled it in."""
    item = database.get_item(item_id)
    current = (item or {}).get("fields", {}).get("host")
    if item and current != host_item_id and (always or not current):
        database.update_item(item_id, fields={"host": host_item_id}, by=None,
                             source="rmm", label=label)


def sync_devices() -> dict:
    """Mirror every device the API key can see into the right customer."""
    devices = fetch_devices()
    by_rmm_org = {o["rmm_org_id"]: o["id"] for o in database.list_orgs() if o.get("rmm_org_id")}
    keys = [f["key"] for f in schema.fields_of("computer").values() if f.get("rmm")]
    label = lambda key: schema.label_of("computer", key)     # noqa: E731

    made = updated = 0
    seen = set()
    host_items: dict = {}                  # device id -> its item
    by_name: dict = {}                     # (customer, hostname) -> item, for guests with an agent
    for device in devices:
        org = (device.get("org") or {}).get("id")
        org_id = by_rmm_org.get(org)
        if not org_id or not device.get("id"):
            continue                       # a customer this side does not have
        seen.add(device["id"])
        payload = device_payload(device)
        existing = database.item_by_rmm_device(device["id"])
        if existing:
            host_items[device["id"]] = existing["id"]
            if device.get("hostname"):
                by_name[(org_id, device["hostname"].strip().lower())] = existing["id"]
            database.update_item(existing["id"], rmm=payload, rmm_keys=keys,
                                 by=None, source="rmm", label=label)
            # Adapters are matched on their MAC, so the port a machine is
            # patched into survives a renamed or reordered interface.
            database.sync_adapters(existing["id"], payload.get("nics"))
            updated += 1
        else:
            # The name and the kind of machine are a starting point, not a
            # standing instruction: rename it here and the next sync leaves it
            # alone, because only the RMM's own fields are refreshed.
            item = database.create_item(org_id, "computer",
                                        device.get("hostname") or device["id"],
                                        {"role": _role(device), "status": "In gebruik"},
                                        by=None, source="rmm", rmm_device_id=device["id"],
                                        rmm=payload, label=label)
            database.sync_adapters(item["id"], payload.get("nics"))
            host_items[device["id"]] = item["id"]
            if device.get("hostname"):
                by_name[(org_id, device["hostname"].strip().lower())] = item["id"]
            made += 1
    device_count = len(seen)

    vms = vms_made = 0
    for device in devices:
        host_item = host_items.get(device.get("id"))
        org = (device.get("org") or {}).get("id")
        org_id = by_rmm_org.get(org)
        if not host_item or not org_id:
            continue
        for vm in device.get("hyperv") or []:
            name = str(vm.get("name") or "").strip()
            if not name:
                continue
            twin = by_name.get((org_id, name.lower()))
            if twin and twin != host_item:
                _runs_on(twin, host_item, always=False, label=label)
                continue
            key = vm_key(org, name)
            if key in seen:
                continue                   # the same name twice on one customer's hosts
            seen.add(key)
            vms += 1
            payload = vm_payload(vm, device)
            existing = database.item_by_rmm_device(key)
            if existing:
                database.update_item(existing["id"], rmm=payload, rmm_keys=VM_KEYS,
                                     by=None, source="rmm", label=label)
                _runs_on(existing["id"], host_item, always=True, label=label)
            else:
                database.create_item(org_id, "computer", name,
                                     {"role": "Virtuele machine", "status": "In gebruik",
                                      "host": host_item},
                                     by=None, source="rmm", rmm_device_id=key,
                                     rmm=payload, label=label)
                vms_made += 1

    # A device that is no longer in the RMM keeps its page and says so. It is
    # never removed here: what was documented about it is usually exactly what
    # somebody needs afterwards. The same for a VM its host no longer reports.
    gone = 0
    for item in database.rmm_items():
        missing = item["rmm_device_id"] not in seen
        if missing != item["rmm_gone"]:
            database.mark_rmm_gone(item["id"], missing)
        if missing:
            gone += 1
    return {"devices": device_count, "new": made + vms_made, "updated": updated,
            "gone": gone, "vms": vms}
