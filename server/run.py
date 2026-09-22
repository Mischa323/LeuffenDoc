"""Entry point.

TLS is expected to be terminated by the reverse proxy in front of this server
(the same one the RMM sits behind), so the app serves plain HTTP and trusts the
forwarded headers for the scheme and the caller's address.

Environment:
  DOC_HOST   bind address (default 0.0.0.0)
  DOC_PORT   bind port (default 8000)
  DOC_DB_PATH  database file (default /data/leuffendoc.db in the container)
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
    print(f"[leuffendoc] serving on {host}:{port}")
    uvicorn.run("app.main:app", host=host, port=port,
                proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
