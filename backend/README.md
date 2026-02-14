# Teletraan Backend

FastAPI-based backend service for the Teletraan application. Handles autonomous multi-agent market analysis, portfolio tracking, LLM metric instrumentation, and real-time chat.

## Setup

```bash
uv sync
```

## Run

Development server with auto-reload:
```bash
uv run uvicorn main:app --reload
```

Custom port:
```bash
uv run uvicorn main:app --reload --port 8001
```

## Project Structure

```
backend/
  api/routes/             API endpoint modules
    analysis.py           Basic technical analysis
    deep_insights.py      Autonomous & deep analysis
    portfolio.py          Portfolio CRUD
    reports.py            Report generation & publishing
    research.py           Follow-up research management
    knowledge.py          Patterns & themes
    outcomes.py           Outcome tracking
    runs.py               Past analysis runs & metrics
    chat.py               WebSocket chat
    ...
  analysis/               Analysis engines
    engines.py            AnalysisEngine, DeepAnalysisEngine, AutonomousDeepEngine
    agents/               Per-phase agents (macro, sector, etc.)
  models/                 SQLAlchemy ORM models
    analysis_task.py      Analysis run tracking with LLM metrics
    deep_insight.py       Deep insights
    portfolio.py          Portfolios & holdings
    ...
  llm/                    LLM & agent logic
    client_pool.py        ClaudeSDK connection pool
    market_agent.py       MCP-based market data agent
  database.py             SQLAlchemy setup, auto-migration
  scheduler.py            APScheduler for ETL tasks
  main.py                 FastAPI app entry point
```

## Key Patterns

- **Singletons**: Module-level factory functions (`get_analysis_engine()`, `get_db()`)
- **Metrics**: Per-phase timing and token usage tracked in `RunMetrics`, aggregated into `AnalysisTask`
- **Auto-migration**: Missing columns auto-detected and added on startup
- **ClaudeSDK pool**: 3 persistent connections for efficient LLM reuse
- **Async-first**: All database and external API calls are async

## Testing

```bash
uv run pytest                       # all tests
uv run pytest tests/test_foo.py     # single file
uv run pytest tests/test_foo.py::test_bar -v  # single test with output
```

## API Documentation

Interactive Swagger docs available at `http://localhost:8000/docs` when the server is running.

### Runs API (`/api/v1/runs`)

- `GET /stats` — Aggregate metrics across all past runs (total cost, token usage, averages)
- `GET /` — Paginated list of past runs with filtering by status or text search
- `GET /{run_id}` — Full details for a single run

### Key LLM Metrics

Each run tracks:
- `total_input_tokens` / `total_output_tokens` — total tokens consumed
- `total_cost_usd` — total cost in USD
- `model_used` — LLM model identifier
- `provider_used` — LLM provider name
- `llm_call_count` — number of LLM calls made
- `phase_timings` — per-phase start/end/duration
- `phase_token_usage` — per-phase token breakdown and cost
