# Changelog

## [Unreleased]

### Added
- **The foundation.** LeuffenDoc runs as its own container next to the RMM: SQLite storage, signed session cookies, customers, an audit log that everything else will write to, and the interface shell in the same design as the dashboard. Signing in through the RMM and with Microsoft 365, the documents themselves, customisable document types and the password vault are built on top of this, each in its own step.
