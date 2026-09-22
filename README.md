# LeuffenDoc

IT documentation per customer — pages, customisable document types and a
password vault — alongside [Leuffen RMM](https://github.com/Mischa323/Leuffenrrm).

Same stack as the RMM on purpose: FastAPI, SQLite, and plain HTML/CSS/JS with no
build step, sharing the dashboard's design system. It runs as its own container
with its own data volume.

## Running it

```sh
docker compose up -d      # http://localhost:8100
```

Everything is configured through environment variables (see
`docker-compose.yml`); settings saved in the app land in the database, and an
explicit environment variable always wins over one of those.

| Variable | What it does |
|---|---|
| `DOC_PUBLIC_URL` | The address people reach this server at. Sign-in redirects are built from it. |
| `DOC_RMM_URL` + `DOC_RMM_API_KEY` | Sign in through the RMM, and mirror its users, customers and permissions. The key is made under **Settings → API & webhooks** in the RMM. |
| `DOC_M365_TENANT` / `DOC_M365_CLIENT_ID` / `DOC_M365_CLIENT_SECRET` | Microsoft 365 sign-in, the fallback for when the RMM is unreachable. |
| `DOC_SESSION_SECRET` | Signs session cookies. Generated into the data volume on first boot if unset. |
| `DOC_SECURE_COOKIES` | `1` by default. Only set to `0` for local HTTP development. |
| `DOC_DEV_LOGIN` | `1` allows a password-free sign-in. Development only; the first account to sign in becomes the administrator. |

TLS is expected to be terminated by the reverse proxy in front of it, as with
the RMM.

## Where things live

```
server/app/main.py       every HTTP endpoint
server/app/database.py   SQLite schema, migrations and queries
server/app/auth.py       sessions and the sign-in plumbing
server/app/static/       the interface (no build step)
```

The data volume holds the database, uploaded files and the vault's master key.
Back that volume up; without the master key the vault cannot be read.
