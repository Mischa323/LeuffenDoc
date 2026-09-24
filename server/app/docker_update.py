"""Updating this server from its own settings page, the way the RMM does.

When ``/var/run/docker.sock`` is mounted and LeuffenDoc runs from a registry
image, the page can pull the newest image and recreate this container in place.
A container cannot cleanly recreate itself -- stopping it kills the process
halfway through -- so the swap is done by a short-lived **helper** container
started from the freshly pulled image: this server hands it the plan and keeps
answering; the helper stops the old container, recreates it from the new image
with the same configuration, and starts it, putting the old one back if
anything fails.

Same design as the RMM's, with two additions: the version waiting in the new
image is read from its label, so the page can say *which* version is ready;
and the page waits for the version to change rather than for any answer at all,
because the old server keeps answering for a few seconds after the button is
pressed.

Without the socket nothing here runs, and the page says what is missing.
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket as _socket
import time

log = logging.getLogger("leuffendoc.update")

SOCK = os.environ.get("DOCKER_HOST_SOCK", "/var/run/docker.sock")
# Registry image to track; defaults to the running container's own image.
IMAGE_OVERRIDE = os.environ.get("DOC_IMAGE", "").strip()
VERSION_LABEL = "org.opencontainers.image.version"


def available() -> bool:
    try:
        return os.path.exists(SOCK) and os.access(SOCK, os.R_OK | os.W_OK)
    except OSError:
        return False


def _request(method: str, path: str, body: dict | None = None, timeout: float = 120.0):
    """A minimal HTTP/1.1 client over the Docker socket -- no extra dependency."""
    conn = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    conn.settimeout(timeout)
    conn.connect(SOCK)
    data = json.dumps(body).encode() if body is not None else b""
    headers = [f"{method} {path} HTTP/1.1", "Host: docker", "Accept: application/json",
               "Connection: close"]
    if body is not None:
        headers += ["Content-Type: application/json", f"Content-Length: {len(data)}"]
    conn.sendall(("\r\n".join(headers) + "\r\n\r\n").encode() + data)
    buf = b""
    while True:
        chunk = conn.recv(65536)
        if not chunk:
            break
        buf += chunk
    conn.close()
    head, _, raw = buf.partition(b"\r\n\r\n")
    try:
        code = int(head.split(b"\r\n", 1)[0].decode(errors="replace").split(" ")[1])
    except (IndexError, ValueError):
        code = 0
    if b"transfer-encoding: chunked" in head.lower():
        raw = _dechunk(raw)
    return code, raw


def _dechunk(raw: bytes) -> bytes:
    out, i = b"", 0
    try:
        while i < len(raw):
            j = raw.find(b"\r\n", i)
            if j < 0:
                break
            size = int(raw[i:j].split(b";")[0], 16)
            if size == 0:
                break
            out += raw[j + 2:j + 2 + size]
            i = j + 2 + size + 2
    except ValueError:
        return raw
    return out


def _json(method: str, path: str, body: dict | None = None):
    code, raw = _request(method, path, body)
    try:
        return code, (json.loads(raw) if raw.strip() else None)
    except json.JSONDecodeError:
        return code, raw.decode(errors="replace")


def _own_container() -> str | None:
    """This container's id: Docker sets the hostname to it, and failing that
    it is in the cgroup paths."""
    host = _socket.gethostname()
    code, _ = _json("GET", f"/containers/{host}/json")
    if code == 200:
        return host
    for path in ("/proc/self/mountinfo", "/proc/self/cgroup"):
        try:
            with open(path) as fh:
                found = re.search(r"\b([0-9a-f]{64})\b", fh.read())
        except OSError:
            continue
        if found:
            return found.group(1)
    return None


def _inspect(cid: str) -> dict | None:
    code, data = _json("GET", f"/containers/{cid}/json")
    return data if code == 200 and isinstance(data, dict) else None


def _image_of(inspect: dict) -> str:
    return IMAGE_OVERRIDE or inspect.get("Config", {}).get("Image", "")


def _image(image: str) -> dict | None:
    code, data = _json("GET", f"/images/{image}/json")
    return data if code == 200 and isinstance(data, dict) else None


def _version_of(image_info: dict | None) -> str | None:
    labels = ((image_info or {}).get("Config") or {}).get("Labels") or {}
    return (labels.get(VERSION_LABEL) or "").lstrip("v") or None


# --------------------------------------------------------------------------- #
# What the running image itself set
#
# To carry over only what somebody chose, the updater compares the container's
# configuration with its image's defaults. But once the tag points at a newer
# image, the running one can no longer always be looked up -- Docker's newer
# image store answers 404 for it -- and without that comparison the old image's
# command would be carried onto the new one. So the defaults are noted while
# they can still be read: at start-up, and again before anything is pulled.
# --------------------------------------------------------------------------- #
DEFAULTS_SETTING = "DOC_IMAGE_DEFAULTS"


def remember_own_image() -> None:
    """Note the running image's defaults while they can still be read."""
    if not available():
        return
    try:
        cid = _own_container()
        inspect = _inspect(cid) if cid else None
        if not inspect:
            return
        from . import database
        saved = json.loads(database.get_setting(DEFAULTS_SETTING) or "{}")
        if saved.get("id") == inspect.get("Image"):
            return
        info = _image(inspect.get("Image", ""))
        if info:
            database.set_setting(DEFAULTS_SETTING, json.dumps(
                {"id": inspect.get("Image"), "config": info.get("Config") or {}}))
    except Exception as exc:                       # never stop the app over this
        log.warning("could not note the image defaults: %r", exc)


def _image_defaults(inspect: dict) -> dict | None:
    info = _image(inspect.get("Image", ""))
    if info:
        return info.get("Config") or {}
    try:
        from . import database
        saved = json.loads(database.get_setting(DEFAULTS_SETTING) or "{}")
        if saved.get("id") == inspect.get("Image"):
            return saved.get("config") or {}
    except Exception:
        pass
    return None


def _pull(image: str) -> bool:
    if ":" in image.rsplit("/", 1)[-1]:
        name, _, tag = image.rpartition(":")
    else:
        name, tag = image, "latest"
    code, _ = _request("POST", f"/images/create?fromImage={name}&tag={tag}", timeout=600)
    log.info("pull %s:%s -> HTTP %s", name, tag, code)
    return code == 200


def status() -> dict:
    """Whether an update from the page is possible, and whether one is waiting."""
    if not available():
        return {"available": False,
                "reason": "de Docker-socket is niet aan deze container gekoppeld"}
    cid = _own_container()
    inspect = _inspect(cid) if cid else None
    if not inspect:
        return {"available": False, "reason": "deze container kan zichzelf niet bekijken"}
    image = _image_of(inspect)
    if image.startswith("sha256:") or "@" in image:
        return {"available": False,
                "reason": "de container draait op een vastgepind image, niet op een tag"}
    if "/" not in image:
        return {"available": False,
                "reason": f"“{image}” is een lokaal gebouwd image, geen image uit een registry"}
    local = _image(image)
    running_id = inspect.get("Image")
    return {"available": True, "image": image, "container": cid,
            "running_image_id": running_id,
            "local_image_id": (local or {}).get("Id"),
            "waiting_version": _version_of(local),
            "update_staged": bool(local and running_id and local.get("Id") != running_id)}


def check() -> dict:
    """Fetch the newest image and say whether it differs from the running one."""
    remember_own_image()
    st = status()
    if not st.get("available"):
        return st
    st["pulled"] = _pull(st["image"])
    local = _image(st["image"])
    st["local_image_id"] = (local or {}).get("Id")
    st["waiting_version"] = _version_of(local)
    st["update_staged"] = bool(local and st.get("running_image_id")
                               and local.get("Id") != st["running_image_id"])
    return st


def start() -> dict:
    """Pull, then hand the swap to a helper started from the new image."""
    remember_own_image()
    st = status()
    if not st.get("available"):
        raise RuntimeError(st.get("reason", "bijwerken is hier niet mogelijk"))
    cid, image = st["container"], st["image"]
    inspect = _inspect(cid)
    if not inspect:
        raise RuntimeError("deze container kan zichzelf niet bekijken")
    if not _pull(image):
        raise RuntimeError("het nieuwe image kon niet worden opgehaald")
    name = inspect.get("Name", "").lstrip("/") or cid
    plan = {"name": name, "old_id": cid, "image": image,
            "spec": _create_spec(inspect, image)}
    helper = _launch_helper(image, plan)
    log.info("update helper %s started to recreate %s from %s", helper, name, image)
    return {"ok": True, "image": image, "container": name, "helper": helper}


def _create_spec(inspect: dict, new_image: str) -> dict:
    """The running container's own configuration, pointed at the new image.

    A container's Config is the image's defaults with whatever was set when it
    was created laid on top. Copying it whole would carry the *old* image's
    command, environment defaults and health check onto the new one, and a
    release that changes any of those would silently keep the old. So only
    what differs from the old image -- what somebody actually chose -- goes
    across, and the new image supplies the rest.
    """
    cfg = dict(inspect.get("Config", {}))
    base = _image_defaults(inspect)
    image_keys = ("Cmd", "Entrypoint", "WorkingDir", "User", "Healthcheck",
                  "ExposedPorts", "Volumes", "StopSignal", "Shell", "OnBuild")

    if base is not None:
        image_env = set(base.get("Env") or [])
        cfg["Env"] = [e for e in (cfg.get("Env") or []) if e not in image_env]
        for key in image_keys:
            if key in cfg and cfg.get(key) == base.get(key):
                cfg.pop(key)
        image_labels = base.get("Labels") or {}
    else:
        # The old image's defaults are unknown. Taking none of them is the
        # safe side: the new image supplies its own command and health check,
        # and of the environment only what is clearly this installation's --
        # its DOC_ settings, and anything the new image does not define --
        # goes across.
        log.warning("image defaults unknown; carrying over only this installation's settings")
        fresh = (_image(new_image) or {}).get("Config") or {}
        fresh_keys = {e.split("=", 1)[0] for e in (fresh.get("Env") or [])}
        cfg["Env"] = [e for e in (cfg.get("Env") or [])
                      if e.startswith("DOC_") or e.split("=", 1)[0] not in fresh_keys]
        for key in image_keys:
            cfg.pop(key, None)
        image_labels = fresh.get("Labels") or {}
    cfg["Labels"] = {k: v for k, v in (cfg.get("Labels") or {}).items()
                     if image_labels.get(k) != v}
    cfg["Image"] = new_image

    host = inspect.get("HostConfig", {})
    nets = inspect.get("NetworkSettings", {}).get("Networks", {}) or {}
    if str(host.get("NetworkMode", "")).startswith(("host", "container")):
        cfg["Hostname"] = ""
        nets = {}
    body = dict(cfg)
    body["HostConfig"] = host
    if nets:
        body["NetworkingConfig"] = {"EndpointsConfig": {
            k: ({"NetworkID": v.get("NetworkID")} if v.get("NetworkID") else {})
            for k, v in nets.items()}}
    return body


def _launch_helper(image: str, plan: dict) -> str:
    body = {
        "Image": image,
        "Entrypoint": ["python", "-c", "from app import docker_update as d; d.run_helper()"],
        "Env": [f"DOC_UPDATE_PLAN={json.dumps(plan)}", f"DOCKER_HOST_SOCK={SOCK}"],
        "HostConfig": {"Binds": [f"{SOCK}:{SOCK}"], "AutoRemove": True,
                       "RestartPolicy": {"Name": "no"}},
        "Labels": {"com.leuffen.doc.role": "updater"},
    }
    code, data = _json("POST", "/containers/create", body)
    if code not in (200, 201) or not isinstance(data, dict):
        raise RuntimeError(f"de hulpcontainer kon niet worden gemaakt (HTTP {code})")
    hid = data["Id"]
    code, _ = _json("POST", f"/containers/{hid}/start")
    if code not in (200, 204):
        raise RuntimeError(f"de hulpcontainer kon niet starten (HTTP {code})")
    return hid


def _settled(cid: str, wait: float = 90.0) -> tuple:
    """Whether a freshly started container is really up.

    Starting is not the same as working: an image that crashes on boot starts
    just fine. With a health check (the image has one) the answer is Docker's;
    without one, running for a while without a restart is the best signal
    there is.
    """
    deadline = time.time() + wait
    running_since = None
    while time.time() < deadline:
        info = _inspect(cid) or {}
        state = info.get("State") or {}
        health = (state.get("Health") or {}).get("Status")
        if state.get("Status") in ("exited", "dead") or state.get("Restarting")                 or (info.get("RestartCount") or 0) > 0:
            return False, f"it stopped (exit code {state.get('ExitCode')})"
        if health == "healthy":
            return True, "healthy"
        if health == "unhealthy":
            return False, "its health check failed"
        if health is None and state.get("Running"):
            running_since = running_since or time.time()
            if time.time() - running_since >= 15:
                return True, "running"
        time.sleep(2)
    return False, "it did not become ready in time"


def run_helper() -> None:
    """Runs inside the throwaway helper: stop, recreate, start -- or roll back."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    time.sleep(3)                   # let the old server finish answering the page
    try:
        plan = json.loads(os.environ["DOC_UPDATE_PLAN"])
    except (KeyError, json.JSONDecodeError) as exc:
        log.error("helper: no usable plan: %s", exc)
        return
    name, old_id, spec = plan["name"], plan["old_id"], plan["spec"]
    backup = f"{name}_old"
    new_id = None
    try:
        _request("POST", f"/containers/{old_id}/stop?t=20")
        _json("POST", f"/containers/{old_id}/rename?name={backup}")
        code, data = _json("POST", f"/containers/create?name={name}", spec)
        if code not in (200, 201):
            raise RuntimeError(f"create failed (HTTP {code}): {data}")
        new_id = data["Id"]
        code, _ = _json("POST", f"/containers/{new_id}/start")
        if code not in (200, 204):
            raise RuntimeError(f"start failed (HTTP {code})")
        # The previous version is only thrown away once the new one works.
        # Until then it is the way back.
        up, why = _settled(new_id)
        if not up:
            raise RuntimeError(f"the new version did not come up: {why}")
        log.info("helper: recreated %s as %s (%s)", name, new_id, why)
        _request("DELETE", f"/containers/{old_id}?force=1")
    except Exception as exc:
        log.error("helper: update failed (%s) -- putting the old one back", exc)
        # A new container that was made but would not start still holds the
        # name, and then the old one cannot have it back -- leaving nothing
        # running at all. It goes first.
        if new_id:
            _request("DELETE", f"/containers/{new_id}?force=1")
        _json("POST", f"/containers/{old_id}/rename?name={name}")
        _request("POST", f"/containers/{old_id}/start")


if __name__ == "__main__":
    run_helper()
