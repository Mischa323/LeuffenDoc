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

## How everything works: things are items

These are the user's standing rules for every feature, not suggestions:

- **Every thing is an item with a page of its own** — the way configuration
  items work. Whatever a customer *has* (a machine, a network, a VPN, a
  Microsoft 365 account, a shared mailbox, a group or Team, a licence, an app
  registration, a supplier …) is an item: listed in its section with search and
  columns, clickable, with its own page. Never only a row in a table on
  somebody else's page. A table field is for what is genuinely part of one
  thing (the NAT rules of a firewall), not for things that deserve a page.
- **Everything can be linked.** On an item's page you can link it to anything
  else (Gekoppeld), and references read from both sides. Files and photos can
  be added to it, and it has its history.
- **Everything takes notes.** On every item, of every kind — built-in, a type
  of your own, or kept up by the RMM — anyone who may change it can leave a
  note (Notities, on the right of the page), without editing the item. A note
  says who wrote it and when, and is searchable and in the export.
- **What comes from elsewhere is kept up, not typed over.** Data from the RMM
  (devices, UniFi, Microsoft 365) arrives as items too: their own fields shown
  from the source and kept in step (`rmm` fields, `schema.rmm_held`), the rest
  typed here — so links, notes and files on them survive every sync. An item
  that leaves the source keeps its page and says so.

## Conventions

- Verify before a push: `python -m py_compile` the changed `.py`,
  `node --check` the changed `.js`.
- `CHANGELOG.md` entry under `## [Unreleased]` for anything user-visible.
- `VERSION` is bumped automatically by CI on pushes touching `server/` — don't
  hand-bump it.
- Commit trailer: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- The interface is in **Dutch**; code, comments and commits are in English.
