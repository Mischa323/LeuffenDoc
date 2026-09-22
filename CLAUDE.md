# LeuffenDoc — working notes

IT documentation per customer (pages, customisable document types, a password
vault), running next to [Leuffen RMM](https://github.com/Mischa323/Leuffenrrm).

## Stack, and why

The same as the RMM, deliberately — one stack to maintain, and the two products
look and read alike: **FastAPI + SQLite**, plain **HTML/CSS/JS with no build
step**, its own container and data volume.

`server/app/static/styles.css` and `icons.js` are **copies of the RMM's**. Keep
them that way: fix a design token or an icon in the RMM first, then copy it
across, rather than letting the two drift.

## Where things live

| Path | What |
|---|---|
| `server/app/main.py` | Every HTTP endpoint. |
| `server/app/database.py` | Schema, additive migrations, queries. One connection **per thread** (a shared one turns two simultaneous reads into a 500), writes serialised behind a lock. |
| `server/app/auth.py` | Sessions (signed cookie), and the plumbing both sign-in routes land in. |
| `server/app/static/` | The interface. `index.html` + `app.js` is the app; `login.html` + `login.js` is the sign-in page. |

Pages are served through `_serve_html`, which stamps `?v=<VERSION>` onto their
own CSS/JS so an upgrade never leaves a browser on yesterday's files. Assets are
referenced **absolutely** (`/styles.css`), because `/auth/login` would otherwise
resolve a relative path to `/auth/styles.css`.

To add a database column: put it in `SCHEMA` *and* add an `if col not in cols`
line to `_migrate`, so new and existing databases end up the same.

## Signing in

Two ways in, both ending at `auth.sign_in`:

1. **Through the RMM** (the normal way). The RMM already knows the person, mints
   a single-use ticket, and LeuffenDoc exchanges it server-to-server for their
   identity, customers and permissions. 2FA, IP rules, Microsoft 365 and account
   removal all stay in one place. Needs `DOC_RMM_URL` + `DOC_RMM_API_KEY`.
2. **Microsoft 365 directly** — the fallback for when the RMM is unreachable or
   someone has no RMM account.

`DOC_DEV_LOGIN=1` adds a password-free sign-in for local work; the first account
to arrive becomes the administrator. Never enable it on a reachable server.

## The vault (when it is built)

- AES-256-GCM per secret, with a key **per customer** that is itself encrypted
  with a master key from the environment or the data volume — never the repo
  (which is public).
- "May see" is a separate permission from "may reveal/copy".
- Every reveal, copy and change goes into `audit`. Never put a secret in
  `audit.detail`, a log line, or an export.
- Losing the master key means losing the vault: it lives on the data volume, so
  that volume is the backup that matters.

## Conventions

- Verify before a push: `python -m py_compile` the changed `.py`,
  `node --check` the changed `.js`.
- `CHANGELOG.md` entry under `## [Unreleased]` for anything user-visible.
- `VERSION` is bumped automatically by CI on pushes touching `server/` — don't
  hand-bump it.
- Commit trailer: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- The interface is in **Dutch**; code, comments and commits are in English.
