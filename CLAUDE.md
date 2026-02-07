# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Run (both services)
```bash
./start.sh                                    # default ports 8000/3000
BACKEND_PORT=8001 FRONTEND_PORT=3001 ./start.sh  # custom ports
```

### Backend
```bash
cd backend
uv sync                                       # install dependencies
uv run uvicorn main:app --reload              # run dev server (port 8000)
uv run pytest                                 # run tests
uv run pytest tests/test_foo.py               # single test file
uv run pytest tests/test_foo.py::test_bar     # single test
```

### Frontend
```bash
cd frontend
npm install                                   # install dependencies
npm run dev                                   # run dev server (port 3000)
npm run build                                 # production build
npm run lint                                  # ESLint
npx playwright test                           # E2E tests
npx playwright test tests/integration.spec.ts # single E2E test
```

### URLs
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- Swagger: http://localhost:8000/docs
- WebSocket: ws://localhost:8000/api/v1/chat

## Architecture

Teletraan -- Full-stack AI market intelligence app: **FastAPI** backend + **Next.js 16** frontend.

### Backend (Python 3.11+, uv)
- **FastAPI** with async SQLAlchemy (SQLite via aiosqlite)
- **claude-agent-sdk** for LLM — uses Claude Code subscription, NO `ANTHROPIC_API_KEY` needed
- All API routes under `/api/v1/` prefix
- Three analysis engines:
  - `AnalysisEngine` — basic technical analysis
  - `DeepAnalysisEngine` — multi-agent deep analysis (5 specialist analysts run in parallel via `asyncio.gather()`, then a Synthesis Lead aggregates)
  - `AutonomousDeepEngine` — self-guided 5-phase pipeline: MacroScanner → SectorRotator → OpportunityHunter → DeepDive → SynthesisLead
- **ETL scheduler** (APScheduler) for cron-based data ingestion
- **Data adapters**: Yahoo Finance (`yfinance`), FRED (`fredapi`), Finnhub (optional)
- **Chat agent** (`llm/market_agent.py`): MCP tool calling with 10 market data tools
- Blocking calls (yfinance) wrapped with `run_in_executor()`

### Frontend (TypeScript, React 19)
- **Next.js App Router** with `'use client'` on interactive pages
- **TanStack Query** for server state (1-min stale, 10-min cache)
- **shadcn/ui** (new-york style) + Tailwind CSS 4 + Recharts
- `fetchApi`/`postApi` in `lib/api.ts` for typed API calls
- `useChat` hook manages WebSocket with auto-reconnect
- Autonomous analysis: polls status endpoint every 2s, task ID in localStorage for reload resilience

### Communication
- REST: Frontend → `/api/v1/...` via HTTP
- WebSocket: Real-time chat via `ws://localhost:8000/api/v1/chat`
- Background tasks: FastAPI `BackgroundTasks` + polling for autonomous analysis

## Key Patterns

- **Singletons**: Module-level instances with `get_*()` factory functions (e.g., `get_deep_analysis_engine()`)
- **Backend file naming**: snake_case; **Frontend**: kebab-case for components, `use-*` prefix for hooks
- **Frontend path alias**: `@/*` maps to project root
- **Pydantic v2**: `model_validate()` for ORM → schema conversion
- **SQLAlchemy**: `DeclarativeBase`, `mapped_column()`, `Mapped[]`, `TimestampMixin` for created_at/updated_at
- **Custom exceptions**: `NotFoundError`, `ValidationError`, `DataSourceError` with registered FastAPI handlers
- **Agent prompts**: System prompt constants + `format_*_context()` / `parse_*_response()` per analyst in `analysis/agents/`

## Environment Variables

**Backend** (`backend/.env` — auto-created by `start.sh`):
- `DATABASE_URL` — default: `sqlite+aiosqlite:///./data/market-analyzer.db`
- `FRED_API_KEY` — optional, for economic data
- `FINNHUB_API_KEY` — optional

**Frontend** (`frontend/.env.local` — auto-created by `start.sh`):
- `NEXT_PUBLIC_API_URL` — default: `http://localhost:8000`
- `NEXT_PUBLIC_WS_URL` — default: `ws://localhost:8000/api/v1/chat`

## Database

SQLite at `backend/data/market-analyzer.db`. Auto-created on first startup via `init_db()`. Tables created from SQLAlchemy models. The `data/` directory is created by `start.sh`.
