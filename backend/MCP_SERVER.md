# Teletraan MCP Server

Exposes Teletraan to MCP clients (Claude Desktop, Claude Code, etc.) so they can
run market analysis, kick off autonomous discovery under a research policy, read
stored insights, and start/stop the app.

It's a self-contained [PEP 723](https://peps.python.org/pep-0723/) script
(`backend/mcp_server.py`) — `uv run mcp_server.py` resolves its `mcp` + `httpx`
dependencies in an ephemeral environment, so it does **not** depend on the
backend's virtualenv.

## How it works

- **Proxy tools** forward to the running FastAPI backend over HTTP and handle JWT
  login automatically (re-logging in on token expiry). These need the backend up.
- **App-control tools** (`start_app` / `stop_app`) run locally via the shell —
  they can't go over HTTP because the app may be down.

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) on PATH.
- For the proxy tools: the Teletraan backend running (`./start.sh`, or use the
  `start_app` tool). A user must exist matching `TELETRAAN_USERNAME` /
  `TELETRAAN_PASSWORD` (defaults to the app's admin account).

## Register in Claude Desktop

Open **Settings → Developer → Edit Config** (this opens
`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS), add:

```json
{
  "mcpServers": {
    "teletraan": {
      "command": "uv",
      "args": ["run", "/Users/nadavbarkai/dev/teletraan/backend/mcp_server.py"],
      "env": {
        "TELETRAAN_API_URL": "http://localhost:8000",
        "TELETRAAN_USERNAME": "admin",
        "TELETRAAN_PASSWORD": "changeme",
        "TELETRAAN_DIR": "/Users/nadavbarkai/dev/teletraan"
      }
    }
  }
}
```

Then fully **quit and reopen Claude Desktop**. The `teletraan` tools appear in the
tools menu. (Use the real absolute path; set credentials to your own.)

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `TELETRAAN_API_URL` | `http://localhost:8000` | Backend base URL |
| `TELETRAAN_USERNAME` | `admin` | Login for protected endpoints |
| `TELETRAAN_PASSWORD` | `changeme` | Login password |
| `TELETRAAN_DIR` | two levels above the script | Repo root for `start_app`/`stop_app` |
| `TELETRAAN_BACKEND_PORT` / `TELETRAAN_FRONTEND_PORT` | `8000` / `3000` | Ports for app control |

## Tools

| Tool | What it does |
|---|---|
| `get_technical_analysis(symbol)` | Indicators, signals, key levels |
| `get_patterns(symbol)` | Detected chart/price patterns |
| `get_anomalies(symbol)` | Volume/price/volatility outliers |
| `get_sector_performance()` | Sector rotation snapshot |
| `run_discovery(policy, max_insights, deep_dive_count)` | Start an autonomous run under a research policy (`balanced`, `aggressive_asymmetric`, `best_bets`, `defensive_income`); returns a `task_id` |
| `discovery_status(task_id)` | Progress + results for a run |
| `recent_discovery()` | Most recent discovery run |
| `list_insights(limit, action, symbol, insight_type)` | List stored deep insights |
| `get_insight(insight_id)` | One stored insight |
| `app_health()` | Unauthenticated backend health probe |
| `start_app()` | Launch backend + frontend via `./start.sh` (detached) |
| `stop_app()` | Stop backend/frontend on the configured ports |

> `run_discovery`'s `policy` parameter requires a backend that has research-policy
> support (the `feat/research-policy` work). Against a backend without it, the
> extra field is simply ignored and the run uses the default behavior.

## Quick manual check

```bash
cd backend
uv run --with mcp --with httpx python - <<'PY'
import asyncio, mcp_server
print(asyncio.run(mcp_server.app_health()))
PY
```
