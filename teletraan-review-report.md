# Teletraan — Full Architecture & Design Review

**Repository:** https://github.com/barkain/teletraan
**Review Date:** 2026-02-17
**Review Team:** team-lead (architect) · dev-squad-leader + dev-1 (backend) + dev-2 (frontend/desktop) · analysts-squad-leader + analyst-1 (domain modeling) + analyst-2 (product/business logic) · devops-squad-leader + devops-1

---

## Executive Summary

Teletraan is a genuinely impressive AI-powered market intelligence platform — a solo/small-team project that achieves multi-agent LLM orchestration, a clean async Python stack, a modern TypeScript frontend, and a cross-platform desktop app. The core analysis engine is sophisticated and well-documented.

However, the project has a fundamental architectural identity problem: it is built for **single-user local use** but aspires to features (WebSocket multi-user chat, GitHub Pages publishing, hosted API) that require multi-user infrastructure it does not have.

**Overall verdict: ~65% of a complete product.** Strong foundation; blocked from any public or multi-user deployment by critical security and scalability gaps.

---

## Table of Contents

1. [Architecture Assessment](#1-architecture-assessment)
2. [Critical Issues — Blockers](#2-critical-issues--blockers)
3. [High-Severity Issues](#3-high-severity-issues)
4. [DevOps & Operational Readiness](#4-devops--operational-readiness)
5. [Domain Modeling Weaknesses](#5-domain-modeling-weaknesses)
6. [Code Quality Issues](#6-code-quality-issues)
7. [Product Completeness](#7-product-completeness)
8. [Business Logic & Workflow Gaps](#8-business-logic--workflow-gaps)
9. [Improvement Roadmap (Priority Ranked)](#9-improvement-roadmap-priority-ranked)
10. [Quick Wins](#10-quick-wins)
11. [Per-Team Detailed Reports](#11-per-team-detailed-reports)

---

## 1. Architecture Assessment

### Tech Stack

| Layer | Stack | Verdict |
|-------|-------|---------|
| Backend | FastAPI + SQLAlchemy 2.0 + aiosqlite + SQLite | Appropriate for local/desktop; SQLite is the binding scalability constraint |
| LLM | claude-agent-sdk subprocess + ClientPool | Sophisticated but tight vendor lock-in; "7 LLM providers" are really 7 auth modes for the same SDK |
| Frontend | Next.js 16 + React 19 + TanStack Query + shadcn/ui | Slightly bleeding-edge but technically sound |
| Desktop | Tauri v2 + PyInstaller backend sidecar | Novel but well-executed; distribution blocked by unsigned binaries |
| Scheduling | APScheduler AsyncIOScheduler (in-process) | Correct for single-instance; non-functional with `--workers > 1` |
| Data | yfinance + FRED + Finnhub (optional) | Appropriate for scope; no circuit breakers |

### What's Good

**Multi-Agent Pipeline (Genuinely Sophisticated)**
The 6-phase autonomous pipeline (MacroScan → HeatmapFetch → HeatmapAnalysis → DeepDive × 5 analysts → CoverageEvaluation → Synthesis) is the system's crown jewel. The `Prompt/Parse` pattern (`ANALYST_PROMPT` constant + `format_context()` + `parse_response()`) is consistent across all 5 analysts — testable, composable, well-documented. The `ClientPool` reuses persistent Claude SDK subprocess connections to eliminate spawn overhead — architecturally clever and shows deep SDK knowledge.

**Async Discipline**
FastAPI + SQLAlchemy 2.0 async + `asyncio.gather()` for parallel analyst execution is correct and well-applied throughout. `run_in_executor` for blocking yfinance calls is the right pattern. `return_exceptions=True` on gather prevents one analyst failure from cancelling the rest.

**Frontend Architecture**
Next.js App Router + TanStack Query + shadcn/ui is a modern, appropriate choice. 16 custom hooks pattern is well-organized. Hybrid real-time model (WebSocket for streaming chat, 2s polling for long-running analysis tasks) is architecturally sound given analysis durations (minutes, not milliseconds).

**Insight Lifecycle Design**
`DeepInsight → InsightConversation → InsightModification → InsightOutcome → KnowledgePattern` feedback loop is conceptually complete with proper audit trail. The `ConversationTheme` relevance decay mechanism is domain-appropriate. Few platforms at this stage think through the full knowledge lifecycle.

**Documentation Quality**
`ARCHITECTURE.md` is 1,300+ lines of accurate, detailed documentation with Mermaid sequence diagrams. `API.md` covers all endpoints with request/response examples. This is rare quality for a personal project.

### What's Broken

**Single-User Architecture, Multi-User Features**
`MarketAnalysisAgent` is a module-level singleton with `self.conversation_history: list`. All WebSocket clients share one conversation history. `POST /chat/clear` clears history for ALL clients simultaneously. This is both a **privacy violation** and a **correctness bug**.

**Monoliths Within the Codebase**
`autonomous_engine.py` is 2,759 lines: orchestrates 6 phases, tracks metrics, writes to DB, manages LLM semaphore, and handles fallback logic — all in one class. `api/routes/reports.py` is 1,500+ lines mixing HTML generation, git subprocess orchestration, and publishing config detection. Both violate Single Responsibility Principle.

**Bespoke Migration System**
`database.py::_sync_migrate_missing_columns()` is a homegrown migration tool that only handles `ALTER TABLE ADD COLUMN`. It cannot rename columns, change types, drop columns, add constraints, or roll back. One bad change silently corrupts schema state.

**Dual Insight Hierarchy**
Two completely separate, unlinked insight systems coexist: legacy `Insight` (stock-FK, severity-based, `InsightAnnotation`) and `DeepInsight` (AI-synthesized, action/thesis/trading params, conversations/outcomes). No FK between them. `Insight` appears to be dead code that hasn't been retired.

---

## 2. Critical Issues — Blockers

These must be resolved before any public or multi-user deployment.

### 🔴 CRITICAL-1: Zero Authentication on All Endpoints

Every API endpoint is completely open. Any process reaching port 8000 can:
- Read all stored insights and portfolio data
- Trigger expensive autonomous analysis runs (LLM API calls at cost)
- Modify LLM settings including injecting a different API endpoint via `POST /api/v1/settings/llm/proxy`
- Clear all chat history for all users simultaneously
- Delete insights and portfolio data
- Trigger GitHub Pages commits to a git repository

`start.sh` binds uvicorn to `0.0.0.0` — exposes backend on all network interfaces. The CORS policy matches any localhost port, which is appropriate for local dev but bypasses browser security if server is publicly accessible.

**Fix:** Add JWT middleware or API key header validation. FastAPI-Users or a simple API key Depends() on all routers as an interim solution.

### 🔴 CRITICAL-2: API Keys Stored in Plaintext SQLite

`LLMSettingsService.save()` writes `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, and other LLM credentials directly to the SQLite database in plaintext. Anyone with filesystem access to `data/teletraan.db` extracts all LLM API credentials.

**Fix:** Use OS keychain (macOS Keychain, Windows DPAPI), environment variable injection, or at minimum AES encrypt the values before storage with a machine-specific key.

### 🔴 CRITICAL-3: Shared Conversation History (Privacy + Correctness Bug)

`MarketAnalysisAgent` is a module-level singleton (`get_market_agent()` → `_instance`). The singleton holds `self.conversation_history: list[dict]`. When multiple browser tabs or users connect via WebSocket, they all share **the same conversation history**. User A's market question gets context injected from User B's prior conversation. The global `POST /chat/clear` endpoint clears history for **all users** simultaneously.

**Fix:** Move conversation history to a per-session or per-connection data structure, keyed by WebSocket connection ID or session token.

### 🔴 CRITICAL-4: No Production Deployment Path

No `Dockerfile`, no `docker-compose.yml`. `start.sh` runs `uvicorn --reload` (hot-reload dev mode) and `npm run dev` (Next.js dev server) — both are development-only modes. There is no supported, documented path to a production hosted deployment.

**Fix:** Add Dockerfile (multi-stage: Python backend + Next.js build) and docker-compose with proper `uvicorn --workers 4` and `next start` commands.

### 🔴 CRITICAL-5: Desktop Process Management Bugs

**SIGKILL without SIGTERM:** The Tauri sidecar calls `child.kill()` (SIGKILL on Unix) with no prior SIGTERM. The Python backend gets no chance to flush write-ahead log, commit open transactions, or close DB connections cleanly. This can corrupt the SQLite database.

**Windows SQLite URL path separator:** `format!("sqlite+aiosqlite:///{}", db_path.display())` produces `sqlite+aiosqlite:///C:\Users\...` on Windows. SQLAlchemy's SQLite URL parser expects forward slashes — this silently fails on every Windows installation.

**Fix:** Send SIGTERM first, wait 5 seconds, then escalate to SIGKILL. Replace `db_path.display()` with `db_path.to_string_lossy().replace('\\', "/")`.

---

## 3. High-Severity Issues

### 🟠 No Alembic / Formal Migration Toolchain

The bespoke `_sync_migrate_missing_columns()` in `database.py` lines 99–133 only handles `ALTER TABLE ADD COLUMN`. Column renames, type changes, constraint additions, index modifications, and column drops all require manual intervention with no migration history or rollback capability. As the schema continues to evolve (13+ tables, all actively extended), this will produce data corruption on the next non-trivial schema change.

**Fix:** Adopt Alembic. Generate initial migration from current schema, then all future changes via `alembic revision --autogenerate`.

### 🟠 Stock Model Eager-Loads All Relationships (O(N) Performance Trap)

`models/stock.py:32–46` sets `lazy="selectin"` on `price_history`, `technical_indicators`, and `insights`. Loading any single `Stock` object triggers three additional SELECT queries fetching the **complete** price history (up to 252 rows), all indicators, and all insights for that stock. At 500 S&P 500 stocks, this is catastrophic for list endpoints.

**Fix:** Change to `lazy="select"` or `lazy="noload"`, and use explicit `.options(selectinload(...))` only on endpoints that need the relationships.

### 🟠 SQLite Write Serialization Under Concurrent Load

SQLite allows only one writer at a time. The system has multiple concurrent writers:
- Background analysis task (writes DB updates per phase, runs 10+ minutes)
- 7 ETL cron jobs (price refresh, economic data, feature computation, outcome checks)
- User API requests (portfolio CRUD, settings, insight conversations)

Under any load, all writers serialize behind SQLite's global write lock, causing frontend polling timeouts and ETL job failures.

**Fix:** For hosted/multi-user deployment: migrate to PostgreSQL + Alembic. SQLite remains acceptable for single-user desktop builds.

### 🟠 No LLM Cost Controls

`POST /api/v1/deep-insights/autonomous` triggers the full 6-phase LLM pipeline (10+ minutes, up to 7 × 5 = 35 analyst LLM calls + macro/heatmap/coverage/synthesis calls). There is no concurrency guard beyond SQLite's optimistic locking — two simultaneous triggers run in parallel. No budget cap, no per-run cost limit, no alerting when costs exceed a threshold.

**Fix:** Add a concurrent-analysis guard (check for existing `IN_PROGRESS` tasks before starting), configurable `MAX_ANALYSIS_COST_USD` setting, and email/webhook alert when threshold is crossed.

### 🟠 Subprocess Git in Reports Route (Argument Injection Risk)

`api/routes/reports.py` constructs git command arguments from user-configurable settings (`GITHUB_PAGES_REPO`, `GITHUB_PAGES_BRANCH`). While `shell=False` is used (correct), the repo name and branch values are not validated against an allowlist before being passed as git arguments. A crafted value like `--upload-pack=/tmp/evil` in `GITHUB_PAGES_REPO` could inject a git flag.

**Fix:** Validate repo name matches `^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$` and branch matches `^[a-zA-Z0-9/_.-]+$` before use in subprocess args.

### 🟠 No Monitoring, No Structured Logging, Always-200 Health Check

- Zero APM (no Prometheus, no OpenTelemetry, no Datadog, no Sentry)
- Plain-text `logging.basicConfig()` to stdout — cannot be aggregated by ELK/Loki/CloudWatch
- Health check `GET /api/v1/health` always returns HTTP 200 even when the database query fails — load balancers cannot detect degraded state
- ETL job failures are logged but never alerted on
- No LLM cost/latency tracking exposed as metrics

### 🟠 Unsigned Desktop Binaries Block Distribution

`"signingIdentity": "-"` in `tauri.conf.json` is ad-hoc self-signing. macOS Gatekeeper will block users from running the app without right-clicking → Open. Windows SmartScreen will show a warning on every install. The CI `build-desktop.yml` has Apple certificate signing as a TODO comment. The `release.yml` workflow publishes releases without human review on `v*` tag pushes.

---

## 4. DevOps & Operational Readiness

*Source: devops-squad-leader + devops-1 review*

### Operational Readiness Matrix

| Area | Status | Severity |
|------|--------|----------|
| Containerization (Docker) | Missing entirely | 🔴 Critical |
| API authentication | None | 🔴 Critical |
| Production deployment config | None | 🔴 Critical |
| Database scalability | SQLite only | 🔴 Critical |
| Formal migrations (Alembic) | None — homebrew only | 🟠 High |
| HTTPS/TLS configuration | None | 🟠 High |
| macOS/Windows code signing | Not configured | 🟠 High |
| Monitoring / APM | None | 🟠 High |
| Structured logging | None (plain text) | 🟡 Medium |
| Dependency vulnerability scanning | None | 🟡 Medium |
| Health check accuracy | Always HTTP 200 | 🟡 Medium |
| Automated dependency updates | No Dependabot/Renovate | 🟡 Medium |
| Horizontal scaling | Not supported | 🟡 Medium |
| Tauri auto-update mechanism | Not configured | 🟡 Medium |
| Backup/restore procedure | None documented | 🟡 Medium |
| Rate limiting | None | 🟡 Medium |
| APScheduler ETL timezone | Hardcoded Eastern Time | 🟡 Medium |
| Distributed locking for ETL | Not implemented | 🟡 Medium |

### CI/CD Assessment

**`ci.yml` (push/PR to main):**
- ✅ Backend pytest with in-memory SQLite
- ✅ Next.js build + Playwright E2E with browser caching
- ✅ ESLint linting
- ✅ `concurrency` cancel-in-progress
- ❌ No code coverage reporting or enforcement
- ❌ No SAST (CodeQL, Semgrep)
- ❌ No dependency vulnerability scanning (`pip-audit`, `npm audit`, Trivy)
- ❌ No secret scanning (GitGuardian, truffleHog)
- ❌ No staging deployment job

**`build-desktop.yml` (manual or `v*` tags):**
- ✅ Multi-platform matrix: macOS arm64, macOS x64, Windows x64
- ✅ Bundle integrity check (fails if PyInstaller output < 100MB)
- ✅ Full toolchain caching (Rust, uv, npm)
- ❌ macOS code signing: NOT configured (TODO comment)
- ❌ Releases non-draft immediately — no human review gate
- ❌ No Windows code signing

**`release.yml` (on `v*.*.*` tags):**
- ✅ Extends matrix to Linux x64 with proper Tauri system deps
- ✅ Publishes as draft (`releaseDraft: true`)
- ❌ macOS signing still missing
- ❌ Duplicate of `build-desktop.yml` with minor differences — confusing two-workflow pattern
- ❌ No SBOM generation, no SLSA provenance attestation

### Environment & Secrets

**Positives:**
- `.gitignore` correctly excludes `.env`, `.env.local`, `*.db`, `*.log`
- `backend/.env.example` is exceptionally well-documented with all 6 LLM provider options
- `pydantic-settings` (`BaseSettings`) with `lru_cache` provides typed, validated config

**Gaps:**
- No secrets management integration (Vault, AWS Secrets Manager, GCP Secret Manager)
- Missing required keys silently fall back to Claude Code subscription — no startup validation failure
- `PUBLISH_METHOD` defaults to `"github_pages"` in config.py but `GITHUB_PAGES_ENABLED` defaults to `False` — contradictory defaults
- No Dependabot or Renovate for automated dependency updates

### Dependency Management

**Backend (`pyproject.toml`):** Python `>=3.12, <3.14`, `uv.lock` committed — deterministic. `uv` is modern. Deps well-chosen: FastAPI 0.109+, SQLAlchemy 2.0 async, APScheduler 3.10, Pydantic v2.

**Frontend (`package.json`):** Next.js 16.1.6, React 19.2.3 (bleeding edge). `package-lock.json` committed. Heavy Radix UI (11 packages). No `npm audit` in CI.

**Desktop (`Cargo.toml`):** Tauri 2, reqwest, tokio, serde. `Cargo.lock` committed. Minimal and appropriate.

**Shared gap:** No automated vulnerability scanning anywhere in the dependency chain.

---

## 5. Domain Modeling Weaknesses

*Source: analyst-1 domain modeling review*

### Critical Modeling Issues

**A. Dual Parallel Insight Hierarchies**
`Insight` and `DeepInsight` are two completely separate models with no FK relationship. `Insight` appears to be legacy code never retired when `DeepInsight` grew to supersede it. Creates domain ambiguity throughout.

**B. PortfolioHolding.symbol — No Referential Integrity**
`PortfolioHolding.symbol` and `StatisticalFeature.symbol` are plain `String(20)` columns, not FKs to `stocks.symbol`. Holdings can reference non-existent symbols. No cascade behavior. Cross-entity queries require string matching instead of joins.

**C. PostgreSQL UUID Dialect on SQLite**
`KnowledgePattern`, `InsightOutcome`, `ConversationTheme` import and use `from sqlalchemy.dialects.postgresql import UUID`. The database is SQLite. This is a latent compatibility bug and signals migration pain ahead.

**D. Trading Price Fields Stored as Strings**
`DeepInsight.entry_zone`, `target_price`, `stop_loss` are `String(50)` storing display values like `"$150-155"`. Makes range queries, arithmetic, and DB-level validation impossible.

**E. Financial Values as Float**
`PortfolioHolding.cost_basis`, `PriceHistory` OHLCV columns use `float`. Should use `Numeric(precision, scale)` to avoid floating-point rounding errors in financial calculations.

**F. `AnalysisTaskStatus` Conflates Phases with Lifecycle States**
Mixes terminal states (`COMPLETED`, `FAILED`, `CANCELLED`) with workflow phase names (`MACRO_SCAN`, `SECTOR_ROTATION`). These are different concepts and should be separate enums.

**G. JSON Blobs vs. Typed Fields — Two Patterns**
Old models use raw `Text` with manual `json.loads()` (`Insight.data_json`, `TechnicalIndicator.metadata_json`, `AnalysisTask.phase_timings`). New models use SQLAlchemy `JSON` type. Inconsistency means some fields have zero type safety.

**H. `DeepInsight` Is Excessively Wide**
30+ columns with overlapping JSON fields added over time: `supporting_evidence`, `technical_analysis_data`, `prediction_market_data`, `sentiment_data`, `discovery_context`. The boundary between `DeepInsight` and `InsightResearchContext` (its 1:1 companion) is unclear and overlapping.

**I. `lazy="selectin"` on Stock Relationships Causes Mass Loading**
See Critical Issues §3 above.

**J. Schema/Model Enum Duplication**
`InsightAction` and `InsightType` are defined in both `models/deep_insight.py` AND `schemas/deep_insight.py`. The schema doesn't import from models — defines its own copies. These can silently diverge.

### Missing Domain Entities

| Entity | Impact |
|--------|--------|
| `FundamentalData` | No P/E, EPS, revenue, book value — incomplete for fundamental analysis |
| `Watchlist` / `WatchlistItem` | No monitoring concept without ownership |
| `Alert` / `Notification` | Insights have `invalidation_trigger` but nothing fires |
| `MarketSession` | `PriceHistory` is daily-only (Date not DateTime); no intraday |
| `Exchange` | No exchange association (NYSE, NASDAQ) for trading hours |
| `PortfolioTransaction` | Holdings only store current state; no history for tax-lot P&L |

---

## 6. Code Quality Issues

*Source: dev-1 (backend) + dev-2 (frontend/desktop) reviews*

### Backend

| Issue | Severity | Location |
|-------|----------|----------|
| `datetime.utcnow()` deprecated in Python 3.12 | Medium | 10+ files |
| `pattern_detector.min_confidence = min_confidence` — shared singleton mutation, race condition | Medium | `api/routes/analysis.py:143` |
| Three pagination styles: `skip/limit`, `offset/limit`, `page/page_size` | Medium | Various routes |
| `ValidationError` in `api/exceptions.py` shadows FastAPI/Pydantic's `RequestValidationError` | Medium | `api/exceptions.py:19` |
| Silent `except ValueError: pass` on date parsing — should return HTTP 400 | Medium | `api/routes/deep_insights.py:137–146` |
| `str(e)` in 500 handlers leaks internal exception strings to clients | Medium | `runs.py`, `deep_insights.py` |
| `asyncio.get_event_loop()` deprecated — use `asyncio.get_running_loop()` | Low | `portfolio.py:42` |
| Dead code: `AnalysisEngine.generate_insights()` never called | Low | `analysis/engine.py:310–365` |
| Three overlapping engine abstractions (engine.py, deep_engine.py, autonomous_engine.py) | Low | `analysis/` |
| `get_db` defined in two places | Low | `database.py` + `api/deps.py` |
| 30+ `# type: ignore[import-not-found]` in autonomous_engine.py — mypy blind spot | Low | `analysis/autonomous_engine.py` |
| `AnalysisTask.to_dict()` bypasses Pydantic schema layer | Low | `models/analysis_task.py` |
| Magic numbers: `limit=252`, `limit=300`, `limit=50` without named constants | Low | `api/routes/analysis.py` |
| `TimestampMixin.created_at` not indexed despite use in ORDER BY | Low | `models/base.py` |

### Frontend

| Issue | Severity | Location |
|-------|----------|----------|
| `fetchApi` calls `res.json()` on all responses — fails on 204 No Content | High | `lib/api.ts` |
| Export endpoints typed as `Blob` but `fetchApi` calls `.json()` — runtime failure | High | `lib/api.ts` |
| Sidebar fires `useDeepInsights({ limit: 100 })` on every page just for badge counts | Medium | Sidebar component |
| Dashboard page component is 1,364 lines — needs decomposition | Medium | `app/page.tsx` |
| Fabricated data: `insights_generated: data.symbols_updated.length * 3` | Medium | `components/refresh-data-button.tsx` |
| `LLMProviderStatus` interface exposes `anthropic_api_key: string \| null` to frontend | Medium | `lib/types/index.ts` |
| Legacy API wrappers not consolidated with new `api` object | Low | `lib/api.ts` |
| Busy-wait WS connection poll: 100ms `setInterval` instead of `onopen` queue | Low | `lib/hooks/use-chat.ts` |
| `console.log` in production WebSocket paths | Low | `lib/hooks/use-chat.ts` |
| No error boundaries — any component error crashes full app | Low | Entire frontend |
| Duplicate `WSMessage` type that doesn't match actual protocol | Low | `types/chat.ts` |
| Debug spec files committed to repo (`debug-*.spec.ts`) | Low | `frontend/tests/` |
| Dual `types/index.ts` files with potential naming collision | Low | `types/` + `lib/types/` |

### Desktop (Rust / Tauri)

| Issue | Severity | Location |
|-------|----------|----------|
| `child.kill()` is SIGKILL — no SIGTERM first, no graceful Python shutdown | High | `desktop/src-tauri/src/lib.rs` |
| Windows SQLite URL backslash path separator bug | High | `desktop/src-tauri/src/lib.rs` |
| `"signingIdentity": "-"` — ad-hoc self-signing, blocks distribution | High | `tauri.conf.json` |
| No `WindowEvent::CloseRequested` handling — backend may become orphan on macOS | Medium | `desktop/src-tauri/src/lib.rs` |
| Duplicate health-check polling: Rust background loop + frontend `BackendReadinessGate` | Low | Both layers |
| No auto-update mechanism configured in Tauri | Low | `tauri.conf.json` |
| No crash reporting integration | Low | — |

---

## 7. Product Completeness

*Source: analyst-2 product review*

| Feature Area | Completeness | Critical Gap |
|---|---|---|
| Analysis Engine (6-phase autonomous) | 85% | Backtesting missing |
| Technical Analysis (RSI, MACD, patterns) | 90% | — |
| Insight Management (CRUD, modifications) | 75% | Auto outcome tracking missing |
| Portfolio Tracking | 50% | No P&L, no transaction history, disconnected from analysis engine |
| Research System | 60% | Execution depth unclear for WHAT_IF/SCENARIO research types |
| HTML Reporting | 55% | No PDF, no email delivery, no scheduling |
| Chat / Conversations | 70% | No cross-session memory; shared singleton privacy bug |
| Knowledge / Patterns | 65% | Stored but not actionable as real-time alerts |
| **Authentication** | **0%** | **Blocker for any deployment** |
| **Alerts / Notifications** | **0%** | Price target hits not surfaced to user |
| **Backtesting** | **0%** | Major credibility gap for a trading platform |

**Overall: ~65% of a complete market intelligence product.**

---

## 8. Business Logic & Workflow Gaps

### Critical Product Gaps

1. **No Alert/Notification System** — Insights have `invalidation_trigger` fields but nothing fires when price hits those levels. No push notifications, email, or SMS when analysis completes or signals trigger.

2. **No Historical Backtesting** — The platform has price history data and validated patterns (KnowledgePattern with success_rate) but no way to test strategy performance historically. This is a major credibility gap for any trading-oriented tool.

3. **Outcome Tracking Is Passive** — `InsightOutcome` model exists and is tracked, but outcomes aren't automatically marked COMPLETED when price targets are hit or time horizons expire. The ETL scheduler is already in place — an outcome-check job just needs to be wired in.

4. **Chat Has No Cross-Session Memory** — WebSocket chat lacks multi-turn context persistence across browser sessions. Each page reload starts fresh. Users cannot build on prior analysis dialogues.

5. **Portfolio Disconnected from Analysis** — Users manually track holdings separately from insights. No "Analyze My Portfolio" button. Impact analysis exists as passive lookup but doesn't trigger active re-analysis of held positions.

6. **Insight Discovery Is All-or-Nothing** — Users can run full 6-phase analysis or browse existing insights. No targeted flows: "scan just tech sector", "analyze stocks in my portfolio", "re-analyze my watchlist".

### Workflow Intuitiveness Issues

- How does a user go from "I want to understand NVDA" to an insight? Too many paths (chat, deep insights, technical analysis, search) with no clear recommended starting point.
- Insight conversations vs. global chat — purpose overlap creates confusion about which to use.
- Statistical signals (`/signals` page) produce Z-scores and anomaly data but aren't surfaced as "you should look at this now" — just a data dump.
- No onboarding flow for API key configuration.

---

## 9. Improvement Roadmap (Priority Ranked)

### Immediate — Before Any Public Release

| Priority | Item | Effort |
|---|---|---|
| 1 | Add API authentication (JWT middleware or API key header on all routers) | Medium |
| 2 | Fix shared conversation history — make `MarketAnalysisAgent` per-session | Small |
| 3 | Fix API key storage — encrypt at rest or use OS keychain | Small |
| 4 | Add Alembic — replace bespoke `_sync_migrate_missing_columns()` | Medium |
| 5 | Fix desktop SIGKILL — send SIGTERM, wait, then escalate | Trivial |
| 6 | Fix Windows SQLite URL path separator | Trivial |
| 7 | Validate git subprocess args (repo name, branch) against allowlist | Small |

### Short-Term — Next Month

| Priority | Item | Effort |
|---|---|---|
| 8 | Replace SQLite with PostgreSQL for any hosted deployment | Large |
| 9 | Extract `ReportPublisher` service from 1,500-line reports route | Medium |
| 10 | Break up `AutonomousDeepEngine` monolith into phase-level service classes | Large |
| 11 | Fix `Stock` eager-loading — change `lazy="selectin"` to `lazy="noload"` with explicit loads | Small |
| 12 | Add `Numeric` types for financial values (prices, portfolio cost basis) | Small |
| 13 | Merge or retire legacy `Insight` model into `DeepInsight` | Medium |
| 14 | Add `PortfolioHolding.symbol` FK to stocks table | Small |
| 15 | Fix PostgreSQL UUID dialect — use `sqlalchemy.Uuid` or `String(36)` | Small |
| 16 | Add concurrency guard on autonomous analysis (one active run at a time) | Small |
| 17 | Separate `AnalysisTaskStatus` phases from lifecycle states | Small |

### Medium-Term — Next Quarter

| Priority | Item | Effort |
|---|---|---|
| 18 | Add Dockerfile + docker-compose for reproducible server deployment | Medium |
| 19 | Implement structured JSON logging + Sentry/error aggregation | Small |
| 20 | Fix health check — return HTTP 503 when DB is unreachable | Trivial |
| 21 | Add rate limiting on expensive endpoints (`/deep-insights/autonomous`) | Small |
| 22 | Configure macOS/Windows code signing in CI | Medium |
| 23 | Add LLM cost budget cap — configurable max spend per run with hard stop | Medium |
| 24 | Automate `InsightOutcome` tracking via existing ETL scheduler | Small |
| 25 | Add basic alert model — notify when price hits invalidation triggers | Medium |
| 26 | Add chat session persistence — users should resume prior dialogues | Medium |
| 27 | Add circuit breakers on yfinance and FRED data source calls | Small |
| 28 | Add `npm audit` and `pip-audit` to CI pipeline | Trivial |
| 29 | Configure Dependabot/Renovate for automated dependency updates | Trivial |
| 30 | Add ETL timezone enforcement — explicit `timezone="America/New_York"` in APScheduler | Small |

### Long-Term — Platform Growth

| Priority | Item | Effort |
|---|---|---|
| 31 | Add backtesting framework against stored price history | Large |
| 32 | Add `PortfolioTransaction` history for cost-basis / P&L tracking | Medium |
| 33 | Add `Watchlist` and `Alert` as first-class domain entities | Medium |
| 34 | Broker API integration for trade execution (Alpaca as entry point) | Large |
| 35 | Add `FundamentalData` model (P/E, EPS, revenue) | Medium |
| 36 | APScheduler distributed locking for multi-instance deployment | Medium |
| 37 | Add "Analyze My Portfolio" mode to autonomous engine | Medium |
| 38 | Add Prometheus/OpenTelemetry metrics endpoint | Medium |
| 39 | Configure Tauri updater plugin for desktop auto-updates | Small |
| 40 | Add SBOM generation and SLSA provenance attestation to release pipeline | Small |

---

## 10. Quick Wins

Low-effort changes with immediate high value — can be done in a single sitting:

1. **`fetchApi` 204 fix:** `if (res.status === 204) return undefined as T;` before `.json()` call
2. **Export endpoints:** Use `res.blob()` not `res.json()` for export routes
3. **`datetime.utcnow()`:** Replace with `datetime.now(timezone.utc)` across all 10+ files
4. **Pattern detector race:** Pass `min_confidence` as a parameter; remove singleton mutation in `analysis.py:143`
5. **WS busy-wait poll:** Replace 100ms `setInterval` with proper `onopen` message queue
6. **Fabricated count:** Remove `insights_generated: data.symbols_updated.length * 3` from RefreshDataButton
7. **Desktop SIGTERM:** Add `child.signal(Signal::Term)` before `child.kill()` in Rust stop_backend
8. **Windows path:** `db_path.to_string_lossy().replace('\\', "/")` in SQLite URL construction
9. **Debug specs:** Remove committed `debug-*.spec.ts` files from frontend/tests/
10. **Startup warning:** Warn on startup if `PUBLISH_METHOD=github_pages` but `GITHUB_PAGES_ENABLED=false`
11. **UTC deprecation:** Replace `datetime.utcnow` with `func.now()` in `models/settings.py`
12. **Health check:** Return HTTP 503 (not 200) when `SELECT 1` health check fails

---

## 11. Per-Team Detailed Reports

### 11.1 Dev Team Report (dev-squad-leader + dev-1 backend + dev-2 frontend/desktop)

#### Backend Deep Dive (dev-1)

**API Design Issues:**
- `/analysis/run` returns no task ID — client has no handle to poll for status. The newer `/deep-insights` pattern does this correctly.
- `/deep-insights/autonomous` blocks synchronously for 60–300 seconds — should return a task ID immediately
- Chat history clearing is global: `ConnectionManager` holds per-client state but `get_market_agent()` returns a singleton — clearing history clears it for ALL clients
- `/settings/{key}` catch-all: new routes added below it will be silently shadowed

**Error Handling Issues:**
- `ValidationError` in `api/exceptions.py:19` shadows FastAPI/Pydantic's internal `RequestValidationError`
- `except Exception` in `runs.py:97,191` wraps entire route bodies — masks real bugs
- Invalid date formats silently ignored (`except ValueError: pass`) — should return HTTP 400
- `str(e)` in 500 responses (`deep_insights.py:276`) leaks full Python exception strings to clients

**Security Issues (most critical first):**
- API credentials stored unencrypted in SQLite via `LLMSettingsService.save()`
- No authentication on any endpoint; `start.sh` binds to `0.0.0.0`
- `str(e)` leaks internal paths/class names
- `allow_credentials=True` with any localhost port — malicious page on any localhost port could make cross-origin requests
- No rate limiting on `/deep-insights/autonomous`

**Database Model Issues:**
- `Stock` eager-loads ALL relationships via `lazy="selectin"` on price_history, technical_indicators, insights — O(N) load on every stock lookup
- `Insight.data_json` is `Text` not `JSON` — forces manual `json.loads()`/`json.dumps()` everywhere
- `AnalysisTask.phase_timings`/`phase_token_usage` also `Text` with manual `_parse_json_field()` deserialization
- No DB-level constraints on enum fields — invalid values can be written directly
- `get_db` defined in both `database.py` and `api/deps.py` — consolidate

#### Frontend & Desktop Deep Dive (dev-2)

**API Layer (`lib/api.ts`):**
- `fetchApi` always calls `res.json()` — 204 No Content and Blob responses will throw
- Response normalization for `stocks.list()` computes `total` as `stocks.length` — incorrect with server-side pagination
- `clearHistory` URL inconsistency: `use-chat.ts` uses `NEXT_PUBLIC_API_URL + /api/v1/...` while `lib/api.ts` strips the prefix — configuration-dependent failure
- `stocksApi`, `insightsApi`, `analysisApi` legacy wrappers coexist with the newer `api` object — different parts of the codebase import from each

**State Management:**
- Sidebar makes a full 100-item query (`useDeepInsights({ limit: 100 })`) on every page load just for badge counts — needs a dedicated lightweight count endpoint
- Dashboard page is 1,364 lines — inline chart components, helpers, constants, and the page component all co-located
- `setTick` pattern forces full component re-render every 30s just to update a relative time label

**WebSocket / Chat:**
- Busy-wait connection polling: 100ms `setInterval` checking `readyState === OPEN` — queue messages in `onopen` callback instead
- `console.log` in production WebSocket connect/close paths
- `WSMessage` type in `types/chat.ts` defined "for future integration" but doesn't match the actual protocol in `use-chat.ts` — dead/misleading code

**UX Issues:**
- Fabricated data: `insights_generated: data.symbols_updated.length * 3` shows made-up insight counts in RefreshDataButton dialog
- Badge semantics non-obvious: "Insights" badge = STRONG_BUY/BUY/SELL/STRONG_SELL count; "Research" badge = WATCH count — unintuitive
- No error boundaries — runtime error in any component crashes entire app with no recovery
- No loading state for `clearHistory` button

**Desktop (Rust):**
- `child.kill()` on Unix is SIGKILL — Python gets no chance to flush DB write-ahead log
- Windows SQLite URL path separator bug (backslashes) — fails silently on every Windows install
- `"signingIdentity": "-"` — ad-hoc signing, won't pass macOS Gatekeeper
- No `WindowEvent::CloseRequested` handler — clicking macOS red X may not fire `RunEvent::Exit`, leaving Python backend as orphan
- Duplicate health-check: Rust background loop AND frontend `BackendReadinessGate` both poll `/health`

---

### 11.2 Analysts Squad Report (analysts-squad-leader + analyst-1 + analyst-2)

#### Domain Modeling (analyst-1)

Beyond the issues documented in §5 above, additional findings:

**`KnowledgePattern` source links unconstrained:**
`source_insights` and `source_conversations` store arrays of integer IDs as JSON with no FK constraints. Deleting a `DeepInsight` leaves stale references with no cascade.

**`UserSettings` uses deprecated pattern:**
`datetime.utcnow` (deprecated Python 3.12) used instead of `func.now()`. Missing `created_at`. Values serialized as JSON string in `Text` column — no schema enforcement.

**`InsightOutcome.deep_insight` relationship not typed:**
Missing `Mapped[...]` annotation — all other relationships use typed `Mapped`. Breaks type checking and IDE support.

#### Business Logic & Product (analyst-2)

**Features that exist:**
- 6-Phase Autonomous Analysis with fallback to legacy sector-rotation pipeline
- Technical analysis: RSI, MACD, Bollinger Bands, Stochastic, ATR, moving averages, chart patterns (H&S, double tops, golden/death cross, breakouts), anomaly detection
- Sector rotation analysis: momentum tracking, heatmaps, relative strength
- Statistical signals: Z-scores, confidence intervals, signal detection
- Deep Insight CRUD with full trading parameters (entry/target/stop zones, time horizon, invalidation triggers)
- AI-augmented conversation threads with modification proposals (PENDING/APPROVED/REJECTED audit trail)
- Portfolio CRUD with live price enrichment and impact analysis
- Knowledge base: KnowledgePattern with success_rate feedback loop
- Outcome tracking with accuracy measurement over 20 trading days
- Research spawning (SCENARIO_ANALYSIS, DEEP_DIVE, CORRELATION_CHECK, WHAT_IF)
- HTML report generation with GitHub Pages publishing
- Full-text search across insights
- 7 LLM provider support
- Runs analytics dashboard with per-phase token/cost/timing metrics

---

### 11.3 DevOps Squad Report (devops-squad-leader + devops-1)

Key findings are documented in §4 above. Additional detail:

**`start.sh` Analysis:**
- Runs `uvicorn --reload` (hot-reload dev mode) — not suitable for production
- Runs `npm run dev` — Next.js development server, not production
- Binds uvicorn to `0.0.0.0` — exposes backend on all network interfaces
- Uses `lsof` for port checks — macOS-specific, fails on many Linux systems
- Auto-overwrites `frontend/.env.local` on every run — breaks user customizations
- Auto-opens browser on macOS only — not portable
- No systemd unit, no supervisord, no PM2, no SSL/TLS

**APScheduler ETL:**
- 7 well-scheduled cron jobs covering all data refresh needs
- All schedules hardcode Eastern Time offset without explicit timezone enforcement
- If deployed to UTC server (any cloud VM default), all market-hours jobs shift by 5 hours
- No distributed locking — multiple instances duplicate all job execution
- No dead-letter queue or retry policy for failed jobs
- No way to pause/resume individual jobs via API

---

### 11.4 Architect Report (architect reviewer)

Full architectural assessment covered in §1–§3 above. Additional findings:

**LLM Integration Architecture:**
The `ClientPool` pattern (reusing persistent Claude SDK subprocess connections via `asyncio.Queue`) is architecturally sophisticated. The `MAX_CONCURRENT_LLM = 3` semaphore prevents resource exhaustion. However:
- The system cannot function without `claude-agent-sdk` (proprietary, spawns `claude` CLI subprocess). True provider abstraction would require an `LLMClient` interface that could be satisfied by raw Anthropic API, OpenAI, or local models.
- Error handling in the LLM layer catches all exceptions identically — transient network blips, JSON parse failures, and rate limits all get the same 2-retry, 1-second backoff treatment.
- LLM responses parsed by `json.loads()` with minimal validation. No structured output validation (JSON Schema or Pydantic model against LLM output). Malformed JSON raises exceptions caught by the generic analyst retry handler, masking whether the issue is LLM output quality or network failure.

**External Data Integration:**
The `run_in_executor` pattern for synchronous yfinance is correct. FRED marked optional based on key presence is good. However, there is no circuit breaker on external data sources — a yfinance outage causes Phase 2 (HeatmapFetch) to fail, triggering legacy fallback, which also calls yfinance for individual stocks. A full yfinance outage causes total pipeline failure with no graceful degradation.

**Frontend ↔ Backend Integration:**
The typed `api.ts` client with generic `fetchApi<T>()` / `postApi<T>()` is clean TypeScript. `localStorage` for task persistence is pragmatic but doesn't handle tab isolation, storage clearing, or orphaned task ID cleanup. The 2-second polling interval generates 30 requests over a 1-minute analysis window from a single client — with no authentication, this is indistinguishable from external DDoS from the server's perspective.

---

## Final Verdict

**Strengths:**
Sophisticated AI orchestration, clean async Python, well-documented, impressive scope for a small team. The multi-agent pipeline, institutional memory design, and outcome tracking show genuine architectural thinking.

**Weaknesses:**
Built for one user, aspires to many. The authentication gap is the single most urgent architectural issue. The shared conversation history singleton is a live privacy bug. The desktop distribution blockers (SIGKILL, Windows path) need immediate fixes.

**Risk Profile:**
✅ Safe to use locally as a personal tool.
⚠️ Not safe to expose to the internet or share with other users in current state.
✅ Foundation is solid enough to build on — the gaps are operational and security-related, not fundamental design flaws.

**Estimated effort to production-ready multi-user deployment:** 3–6 months of dedicated engineering time covering: authentication, PostgreSQL migration, Alembic, monitoring, containerization, and desktop distribution signing.
