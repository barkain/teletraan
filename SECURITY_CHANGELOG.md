# Security Changelog

This document tracks security reviews and remediation actions for the Teletraan codebase.
Entries are ordered newest first.

---

## 2026-02-27 17:25 IST — Security Review: feat/thematic-investor-intelligence

**Branch reviewed:** `feat/thematic-investor-intelligence`
**Reviewer:** Automated (Claude Code)
**Scope:** SQLite to Neon PostgreSQL migration + thematic investor intelligence features (~30 files)
**Result:** No vulnerabilities found — 0 HIGH, 0 MEDIUM

### Areas Reviewed

| Category | Result | Notes |
|---|---|---|
| SQL Injection | Clear | All queries use SQLAlchemy ORM (parameterized). DDL in `database.py` uses internal model metadata, not user input. |
| XSS | Clear | New HTML report sections properly escape all dynamic content via `_esc()`. |
| Command Injection / RCE | Clear | No `eval()`, `exec()`, `pickle`, or unsafe deserialization in new code. |
| Hardcoded Secrets | Clear | No credentials in committed files. Previously flagged migration script deleted. |
| SSRF | Excluded | `investor_feeds.py` constructs URLs with fixed hosts (`data.sec.gov`); user input only controls path segments. |
| Auth/Authz | Clear | New routes follow existing patterns. Single-user local-first app. |
| Sensitive Data Exposure | Clear | No secrets or PII logged. DB credentials sourced from env vars. |
| SSL/TLS | Acceptable | PostgreSQL uses `ssl: "require"` for encrypted traffic. |

### Remediation Actions Taken

- Deleted `backend/scripts/migrate_sqlite_to_pg.py` which contained hardcoded Neon PostgreSQL credentials
- Removed hardcoded Neon connection string from `backend/config.py` default; restored SQLite as default with PostgreSQL configurable via env var
- Added `.gitignore` comment for one-time migration utilities

---
