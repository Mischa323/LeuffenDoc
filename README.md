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
| `DOC_RMM_PUBLIC_URL` | Where a *browser* reaches the RMM, when that differs from the address this server uses (an internal network, say). Defaults to `DOC_RMM_URL`. |
| `DOC_SYNC_MINUTES` | How often to pull users and customers from the RMM. Default 15. |
| `DOC_M365_TENANT` / `DOC_M365_CLIENT_ID` / `DOC_M365_CLIENT_SECRET` | Microsoft 365 sign-in, the fallback for when the RMM is unreachable. |
| `DOC_BOOTSTRAP_ADMIN` | Addresses (comma separated) that are always administrators, whatever the database says — how a fresh install is set up, and the way back in if nobody is left with the rights. |
| `DOC_SECRET_KEY` | The master key of the password vault. Set it to a 32-byte key (base64 or hex) or a passphrase, and **keep it somewhere other than the database backup** — a backup that holds both the vault and its key protects nothing. Left unset, a key is generated and stored in the database, and the **Wachtwoorden** page says so. Change it and the existing passwords can no longer be opened, so set it before you start filling the vault. |
| `DOC_SESSION_SECRET` | Signs session cookies. Generated into the data volume on first boot if unset. |
| `DOC_SECURE_COOKIES` | `1` by default. Only set to `0` for local HTTP development. |
| `DOC_TRUST_PROXY` | `1` behind a reverse proxy, so the audit log records the visitor rather than the proxy. `0` if the container is reachable directly. |
| `DOC_PROXY_IPS` | The address(es) your proxy connects from. Forwarded headers are only believed from there. |
| `DOC_DEV_LOGIN` | `1` allows a password-free sign-in. Development only; the first account to sign in becomes the administrator. |

## Signing in

Two ways, both ending in the same session cookie.

**Through the RMM** (the normal way). The RMM is where accounts live, so it does
the identifying: LeuffenDoc sends the browser there, the RMM recognises the
session it already has — or asks the person to sign in, 2FA and IP rules
included — and sends them back with a **single-use ticket**. LeuffenDoc redeems
that ticket over its own connection using the API key, so a ticket left in a
browser's history is worth nothing by itself. Their customers and whether they
are an administrator come across in the same answer.

Set up:

1. In the RMM, **Settings → API & webhooks**, make a key that spans all
   organisations, and put it in `DOC_RMM_API_KEY` with `DOC_RMM_URL`.
2. On the RMM server, set `RMM_SSO_RETURN_URLS` to LeuffenDoc's address
   (`https://doc.example.com`). Anything not on that list is refused: without
   it the hand-off would send a valid ticket wherever a link said.

**With Microsoft 365** — the fallback for when the RMM is unreachable, or for
someone with no RMM account. They arrive with **no customers**; what they may
see is granted here, since Microsoft 365 knows nothing about our customers. Add
`https://doc.example.com/auth/m365/callback` as a redirect URI on the app
registration (the RMM's own registration will do, with that URI added).

Users, customers and access are pulled from the RMM every `DOC_SYNC_MINUTES`
and whenever somebody signs in, so access withdrawn there disappears here.
**Klanten** shows the state of that link, with a button to sync on the spot.

## Behind a reverse proxy

TLS is terminated by the proxy, as with the RMM. The server needs three things
from it:

- **`X-Forwarded-Proto: https`** — without it the session cookie is set with
  `Secure` over what the server believes is plain HTTP, and the browser drops
  it, so signing in appears to do nothing.
- **`X-Forwarded-For`** — the visitor's address, for the audit log.
- **`Host`** — kept as the public hostname.

Give it its **own hostname** (`doc.example.com`), not a sub-path of another
site: pages reference their assets from the root.

```nginx
location / {
    proxy_pass         http://127.0.0.1:8100;
    proxy_set_header   Host              $host;
    # $remote_addr, not $proxy_add_x_forwarded_for: see below.
    proxy_set_header   X-Forwarded-For   $remote_addr;
    proxy_set_header   X-Forwarded-Proto $scheme;
}
```

Caddy: `reverse_proxy 127.0.0.1:8100 { header_up X-Forwarded-For {remote_host} }`
(the rest it sets itself).

### Two settings that decide whether the audit log can be trusted

`X-Forwarded-For` is a header like any other — a visitor's browser can send one.
Two things keep that from ending up in the log as their address:

1. **`DOC_PROXY_IPS`** — the address your proxy connects from. Forwarded headers
   are believed only on connections coming from there, so someone reaching the
   container directly cannot dictate their own address. Left unset it means
   "any", which is only safe while nothing but the proxy can reach the
   container.
2. **Overwriting, not appending.** nginx's usual `$proxy_add_x_forwarded_for`
   *appends* to whatever the browser sent, and the oldest entry in that list —
   the visitor's own claim — is the one that counts as the client. Setting
   `$remote_addr` replaces the whole thing with the address nginx actually saw.

`DOC_TRUST_PROXY=0` switches the headers off entirely; the log then records the
proxy's address for everyone.

### Synology DSM as the reverse proxy

DSM's reverse proxy passes almost nothing on by default. In **Control Panel →
Login Portal → Advanced → Reverse Proxy**, edit the rule and open **Custom
Header**:

| Header name | Value | Why |
|---|---|---|
| `X-Forwarded-Proto` | `$scheme` | Without it the session cookie is set `Secure` over what the server believes is plain HTTP, and the browser drops it — signing in then appears to do nothing. |
| `X-Forwarded-For` | `$remote_addr` | The visitor's address, for the audit log. `$remote_addr` **replaces** whatever the browser sent, which is the point. |
| `X-Real-IP` | `$remote_addr` | Not used here, but handy in DSM's own logs. |

(The **Create → WebSocket** preset adds `Upgrade`/`Connection`. LeuffenDoc
doesn't use WebSockets, so it needs neither — the RMM on the same NAS does.)

Then set `DOC_PROXY_IPS` to the address DSM's proxy connects from: for a
container on the same NAS that is the Docker bridge gateway (commonly
`172.17.0.1`), not the NAS's LAN address. Afterwards open **Logboek**, which
tells you the address it sees you arriving from and names anything still wrong.

**Check it worked:** sign in and open **Logboek**. It says which address the
server sees you arriving from and over which scheme, and names anything that is
off (a proxy whose headers aren't being passed on, a missing public address, a
cookie that the browser will refuse).

## Where things live

```
server/app/main.py       every HTTP endpoint
server/app/database.py   SQLite schema, migrations and queries
server/app/auth.py       sessions and the sign-in plumbing
server/app/static/       the interface (no build step)
```

The data volume holds the database, uploaded files and the vault's master key.
Back that volume up; without the master key the vault cannot be read.
