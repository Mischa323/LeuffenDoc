# LeuffenDoc

IT documentation per customer — pages, customisable document types and a
password vault — alongside [Leuffen RMM](https://github.com/Mischa323/Leuffenrrm).

Same stack as the RMM on purpose: FastAPI, SQLite, and plain HTML/CSS/JS with no
build step, sharing the dashboard's design system. It runs as its own container
with its own data volume.

## Running it

The container needs an image, a port and a volume — nothing else:

```yaml
services:
  leuffendoc:
    image: ghcr.io/mischa323/leuffendoc:latest
    ports:
      - "8100:8000"
    volumes:
      - ./data:/data
    restart: unless-stopped
```

(In Dockge: **+ Compose**, paste this, **Deploy**.) The first time you open it,
it shows a **set-up screen**:

1. **The set-up code.** It is printed in the container's log — on the stack's
   page in Dockge, or `docker logs leuffendoc`. Until set-up is done anyone who
   reaches the page could claim the server, so only whoever runs the container
   can. Five wrong tries and a new code is printed.
2. **The RMM's address, and one button.** **Koppelen met de RMM** sends you to
   the RMM, which asks a global administrator to approve. It then issues
   LeuffenDoc's API key and records LeuffenDoc's address on its side (the Docs
   button, the drawer's Docs tab, the permitted sign-in return). The key never
   passes through the browser: the browser carries a single-use code, which
   this server exchanges — together with a secret only it holds — over its own
   connection. Whoever approves administers LeuffenDoc and is signed in.

The rest is filled in from what the server sees of that very request: its own
address, whether a reverse proxy is in front and from which address it
connects, and https-only cookies when you arrive over https. **Zelf aanpassen**
changes any of it. If this server cannot reach the RMM at the address your
browser uses — a NAS that does not reach its own public name, or an RMM with a
self-signed certificate — the page says so after you approve and asks for one
that works, such as the LAN address and port. An RMM without the one-button
link, or Microsoft 365 on its own, can be set up by hand on the same screen.

Everything lands in the database and is changed later under **Instellingen**;
**Koppelen** there links again, with another RMM or after a key was revoked.
The RMM can start it too: **Settings → API & webhooks → LeuffenDoc → Link with
LeuffenDoc**.

Environment variables are no longer needed, but still work, and win over what
is saved — to pin a value, or to get back in:

| Variable | What it does |
|---|---|
| `DOC_BOOTSTRAP_ADMIN` | Addresses (comma separated) that are always administrators, on top of those chosen at set-up — the way back in if nobody is left with the rights. |
| `DOC_SECRET_KEY` | The master key of the password vault, to keep it out of the database. Set it to a 32-byte key (base64 or hex) or a passphrase, and **keep it somewhere other than the database backup**. Left unset, a key is generated and stored in the database — fine with the encrypted back-ups, and what the set-up screen says it does. Change it and the existing passwords can no longer be opened, so decide before you start filling the vault. |
| `DOC_PUBLIC_URL`, `DOC_RMM_URL`, `DOC_RMM_API_KEY`, `DOC_RMM_PUBLIC_URL`, `DOC_RMM_INSECURE_TLS`, `DOC_SYNC_MINUTES`, `DOC_M365_*`, `DOC_TRUST_PROXY`, `DOC_PROXY_IPS`, `DOC_SECURE_COOKIES`, `DOC_SESSION_DAYS`, `DOC_BACKUP_HOURS`, `DOC_BACKUP_KEEP`, `PW_*` | Everything on the set-up screen and under **Instellingen**, pinned. The page then shows the value as fixed rather than offering a field that would be ignored. A container started with `DOC_RMM_URL`, `DOC_PUBLIC_URL` or `DOC_BOOTSTRAP_ADMIN` skips the set-up screen. |
| `DOC_SESSION_SECRET` | Signs session cookies. Generated into the database if unset. |
| `DOC_DEV_LOGIN` | `1` allows a password-free sign-in. Development only. |
| `DOC_IMAGE` | The image an update from the page pulls. Defaults to the one the container runs. |

### Updating from the page

**Instellingen → Over deze server** can pull the newest image and restart
LeuffenDoc on it, like the RMM does. It needs the Docker socket and an image
from a registry:

```yaml
services:
  leuffendoc:
    image: ghcr.io/mischa323/leuffendoc:latest
    volumes:
      - leuffendoc-data:/data
      - /var/run/docker.sock:/var/run/docker.sock
```

A short-lived helper container does the swap, because a container cannot
replace itself mid-request. It keeps your ports, volumes, networks, restart
policy and the settings you gave the container — but takes the command,
health check and built-in defaults from the **new** image, so a release that
changes those is not silently run with the old ones. The previous version is
only thrown away once the new one reports healthy; if it does not start, the
previous one is put back and the page says so.

Without the socket the page says updating is not possible there, and why.
Mounting the socket gives the container control over Docker on that host, so
only do it where that is acceptable — updating by pulling the image and
recreating the container yourself works just as well.

## Signing in

Two ways, both ending in the same session cookie.

**Through the RMM** (the normal way). The RMM is where accounts live, so it does
the identifying: LeuffenDoc sends the browser there, the RMM recognises the
session it already has — or asks the person to sign in, 2FA and IP rules
included — and sends them back with a **single-use ticket**. LeuffenDoc redeems
that ticket over its own connection using the API key, so a ticket left in a
browser's history is worth nothing by itself. Their customers and whether they
are an administrator come across in the same answer.

Linking with one button (see *Running it*) sets up both sides. By hand
instead: make a key under **Settings → API & webhooks** in the RMM that spans
all organisations, fill it in with the RMM's address under **Instellingen**
here, and fill in LeuffenDoc's address in the RMM under **Settings → API &
webhooks → LeuffenDoc** — the RMM hands a sign-in ticket to no other address.

**With Microsoft 365** — the fallback for when the RMM is unreachable, or for
someone with no RMM account. They arrive with **no customers**; what they may
see is granted here, since Microsoft 365 knows nothing about our customers. Add
`https://doc.example.com/auth/m365/callback` as a redirect URI on the app
registration (the RMM's own registration will do, with that URI added).

Users, customers and access are pulled from the RMM every `DOC_SYNC_MINUTES`
and whenever somebody signs in, so access withdrawn there disappears here.
**Klanten** shows the state of that link, with a button to sync on the spot.

The other way round, what is documented about each machine is sent to the RMM,
where its device drawer shows it under **Docs** — with the same API key, so
nothing extra to set up. It goes within seconds of a change, and only for the
machines whose summary changed. Passwords never go, and neither does anything
shut off to named colleagues. The links in that tab point at LeuffenDoc's
own address, as chosen at set-up.

## Sharing a password with someone outside

**Delen** on a password makes a link for someone without an account — a
supplier, a customer's new employee. You choose how long it works (an hour to a
week) and how many times it may be opened; the link is shown once, and only a
hash of it is kept. The page behind it shows nothing until the button is
pressed, because Teams, Outlook and Slack open links by themselves to draw a
preview. Changing the password closes every link still open for it, and every
opening is in the log with where it came from.

For the link to work for someone outside, two things:

- **`DOC_PUBLIC_URL`** must be set, or the address is guessed from the request
  (and the page says so).
- **`/deel/`** must be reachable from where that person is. If LeuffenDoc is
  only reachable over a VPN, publish that one path; it needs no sign-in and
  hands out nothing without a valid link.

## Kluis

**Kluis**, for administrators, lists across every customer which passwords are
due to be replaced, which are the same password in more than one place, which
are weak, and which have not changed in `PW_MAX_AGE_DAYS` (a year by default,
under **Instellingen**; 0 switches it off). It is drawn up without opening the
vault: a grade and a fingerprint are stored with each password when it is
saved. The fingerprint is an HMAC keyed from the vault's master key, so it is
useless without that key.

Passwords stored before this existed have neither, and are listed as not
judged until an administrator presses **Nu beoordelen**. That opens each of
them once on the server — nothing reaches the browser — and is one line in the
log. After changing `DOC_SECRET_KEY` the fingerprints no longer match new ones,
but by then the old passwords do not open either.

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

1. **The proxy's address** (Instellingen → Toegang) — where your proxy
   connects from. Forwarded headers are believed only on connections from
   there, so someone reaching the container directly cannot dictate their own
   address. Empty means "any", which is only safe while nothing but the proxy
   can reach the container. Setting up through the proxy fills it in.
2. **Overwriting, not appending.** nginx's usual `$proxy_add_x_forwarded_for`
   *appends* to whatever the browser sent, and the oldest entry in that list —
   the visitor's own claim — is the one that counts as the client. Setting
   `$remote_addr` replaces the whole thing with the address nginx actually saw.

Switching the reverse proxy off under Instellingen → Toegang ignores the
headers entirely; the log then records the proxy's address for everyone. The
app resolves all of this itself, per request, so a change there takes effect
without a restart.

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

The proxy's address is then the gateway of the container's Docker network
(something like `172.20.0.1` — each Dockge stack has its own network), not the
NAS's LAN address. Set up through DSM's proxy and the set-up screen fills it
in; otherwise **Logboek** says which address it sees and **Instellingen →
Toegang** takes it.

**Check it worked:** sign in and open **Logboek**. It says which address the
server sees you arriving from and over which scheme, and names anything that is
off (a proxy whose headers aren't being passed on, a missing public address, a
cookie that the browser will refuse).

## Exporting a customer

**Exporteren** on a customer's overview gives a zip: `documentatie.html` to read
and print (it needs no server), `data.json` with everything structured, and
`csv/` with a sheet per kind, semicolon-separated with a byte-order mark so
Excel on a Dutch machine opens it as columns. Only what the person exporting
may see goes in. Passwords go in only when ticked, only for someone whose role
allows reading them — then the file holds them in plain text, and every one of
them is written in the log.

## Back-ups

Copying `leuffendoc.db` while the server runs is not a back-up: SQLite keeps
the latest changes in a second file (`-wal`), and a copy taken halfway through
a write can come back broken. So LeuffenDoc makes its own **snapshots**, from
one consistent moment, into `backups/` in the data volume — every
`DOC_BACKUP_HOURS`, keeping the newest `DOC_BACKUP_KEEP`. Back up the volume as
you would anyway and those files are what you restore from.

**Instellingen → Back-ups** lists them, makes one on the spot, and downloads
one — always encrypted with a passphrase you choose, since it holds every
customer's documentation and, without `DOC_SECRET_KEY` in the environment, the
vault's key as well. Keep the passphrase somewhere other than the file.

**Putting one back** is done on the same page: upload the file, it is checked
(whole, a LeuffenDoc database, and passwords that open with the key that will
be in force), then **Terugzetten**. The contents are replaced in place; the
state just before is kept as a snapshot of its own, so it can be undone. On a
new server: start LeuffenDoc with the same `DOC_SECRET_KEY` if you had one set,
sign in as a `DOC_BOOTSTRAP_ADMIN`, and upload.

A `.ldbak` file can be opened without LeuffenDoc. It is a line
`LEUFFENDOC-BACKUP`, a line of JSON, and then the SQLite database, gzipped and
encrypted with AES-256-GCM; the key is scrypt of the passphrase with the
parameters in the JSON, which is itself the associated data:

```python
import base64, gzip, hashlib, json, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

data = open(sys.argv[1], "rb").read().split(b"\n", 2)       # magic, header, body
head = json.loads(data[1])
key = hashlib.scrypt(sys.argv[2].encode(), salt=base64.b64decode(head["salt"]),
                     n=head["n"], r=head["r"], p=head["p"], maxmem=2**27, dklen=32)
plain = AESGCM(key).decrypt(base64.b64decode(head["nonce"]), data[2], data[1])
open("leuffendoc.db", "wb").write(gzip.decompress(plain))
```

## Tests

```sh
pip install -r requirements.txt pytest
python -m pytest server/tests
```

They run against a real LeuffenDoc on a throw-away database — the vault,
who may see and read what, share links, back-ups and putting one back, the
export, and what is sent to the RMM — in a few seconds. GitHub Actions runs
them on every push, and only builds the image when they pass.

## Where things live

```
server/app/main.py       every HTTP endpoint
server/app/database.py   SQLite schema, migrations and queries
server/app/auth.py       sessions and the sign-in plumbing
server/app/static/       the interface (no build step)
server/tests/            the test suite (pytest)
```

The data volume holds the database, uploaded files and the vault's master key.
Back that volume up; without the master key the vault cannot be read.
