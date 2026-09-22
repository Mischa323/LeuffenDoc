# Changelog

## [Unreleased]

### Added
- **Runs behind your reverse proxy, and says so when it doesn't.** TLS is terminated by the proxy, as with the RMM. Forwarded headers are believed **only** on connections from the address you name in `DOC_PROXY_IPS`, so nobody reaching the container directly can write their own address into the audit log — and the proxy must *overwrite* `X-Forwarded-For` rather than append to it, since the oldest entry in an appended list is whatever the visitor's browser felt like claiming. **Logboek** shows the address the server sees you arriving from and names anything that is off: headers not passed on, a missing public address, a cookie the browser will refuse, or a proxy that any caller could impersonate.
- **The foundation.** LeuffenDoc runs as its own container next to the RMM: SQLite storage, signed session cookies, customers, an audit log that everything else will write to, and the interface shell in the same design as the dashboard. Signing in through the RMM and with Microsoft 365, the documents themselves, customisable document types and the password vault are built on top of this, each in its own step.
