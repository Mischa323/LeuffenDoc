"""Entry point.

TLS is terminated by the reverse proxy in front of this server (the same one the
RMM sits behind), so the app serves plain HTTP and reads the scheme and the
visitor's address from the proxy's `X-Forwarded-*` headers.

Those headers are only believed when the connection comes from a proxy we were
told about: `DOC_PROXY_IPS`. Without that, anyone who can reach the container
directly could hand it any address they liked and have it land in the audit log.

Environment:
  DOC_HOST         bind address (default 0.0.0.0)
  DOC_PORT         bind port (default 8000)
  DOC_DB_PATH      database file (default /data/leuffendoc.db in the container)
  DOC_TRUST_PROXY  1 when a reverse proxy sits in front
  DOC_PROXY_IPS    which addresses that proxy connects from (default: any)
"""
from __future__ import annotations

import os

import uvicorn


def _load_saved_settings() -> None:
    """Pull settings saved in the database into the environment, without ever
    overriding what the container was actually started with."""
    from app import database
    database.init_db()
    for key, value in database.all_settings().items():
        if value is not None and key not in os.environ:
            os.environ[key] = value


def main() -> None:
    _load_saved_settings()
    host = os.environ.get("DOC_HOST", "0.0.0.0")
    port = int(os.environ.get("DOC_PORT", "8000"))
    trust = os.environ.get("DOC_TRUST_PROXY", "0") == "1"
    proxies = os.environ.get("DOC_PROXY_IPS", "*").strip()
    print(f"[leuffendoc] serving on {host}:{port}; "
          + (f"trusting forwarded headers from {proxies}" if trust
             else "forwarded headers ignored (no proxy configured)"))
    uvicorn.run("app.main:app", host=host, port=port,
                proxy_headers=trust,
                forwarded_allow_ips=proxies if trust else [])


if __name__ == "__main__":
    main()
