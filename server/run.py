"""Entry point.

TLS is terminated by the reverse proxy in front of this server (the same one the
RMM sits behind), so the app serves plain HTTP and reads the scheme and the
visitor's address from the proxy's `X-Forwarded-*` headers.

Which proxy to believe is decided by the app itself (see ``auth.client_ip``),
not by uvicorn: it is set on the set-up screen and under Instellingen, and a
change there takes effect on the next request rather than at the next restart.

Nothing saved in the database is copied into the environment. The environment
is what the container was started with -- an override, shown as such -- and
treating saved settings as if they were would lock them on the settings page.

Environment (all optional):
  DOC_HOST         bind address (default 0.0.0.0)
  DOC_PORT         bind port (default 8000)
  DOC_DB_PATH      database file (default /data/leuffendoc.db in the container)
"""
from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("DOC_HOST", "0.0.0.0")
    port = int(os.environ.get("DOC_PORT", "8000"))
    print(f"[leuffendoc] serving on {host}:{port}", flush=True)
    uvicorn.run("app.main:app", host=host, port=port, proxy_headers=False)


if __name__ == "__main__":
    main()
