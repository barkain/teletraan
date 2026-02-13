# Development Guide

## Prerequisites

- **Python 3.11+** with [`uv`](https://github.com/astral-sh/uv) package manager
- **Node.js 18+** with `npm`
- **Git**

## Running Both Services

```bash
./start.sh                                    # default ports 8000/3000
BACKEND_PORT=8001 FRONTEND_PORT=3001 ./start.sh  # custom ports
```

The `start.sh` script handles:
- Installing Python and Node.js dependencies
- Creating `.env` files with defaults
- Starting both backend and frontend
- Waiting for services to be ready
- Opening your browser automatically

## Backend Commands

```bash
cd backend
uv sync                                    # Install dependencies
uv run uvicorn main:app --reload           # Run dev server with hot reload
uv run pytest                              # Run all tests
uv run pytest tests/test_foo.py            # Run single test file
uv run pytest tests/test_foo.py::test_bar  # Run specific test
```

## Frontend Commands

```bash
cd frontend
npm install                                # Install dependencies
npm run dev                                # Start dev server (http://localhost:3000)
npm run build                              # Production build
npm run lint                               # ESLint
npx playwright test                        # Run E2E tests
npx playwright test -g "test name"         # Run specific test
```

## URLs

- Frontend: http://localhost:3000
- API Docs (Swagger): http://localhost:8000/docs
- WebSocket: ws://localhost:8000/api/v1/chat

## Environment Variables

### Backend (`backend/.env`)

Auto-created by `start.sh` with defaults:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/market-analyzer.db` | SQLite async connection string |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Override default LLM model |
| `FRED_API_KEY` | *(optional)* | Federal Reserve Economic Data API key for macro data |
| `FINNHUB_API_KEY` | *(optional)* | Finnhub API key for enhanced data sources |
| `GITHUB_PAGES_ENABLED` | `false` | Enable report publishing to GitHub Pages |
| `GITHUB_PAGES_REPO` | *(auto-detected)* | Target repo for publishing |
| `GITHUB_PAGES_BASE_URL` | *(derived from repo)* | Override published report base URL |

For LLM provider configuration, see [LLM Providers](llm-providers.md).

### Frontend (`frontend/.env.local`)

Auto-created by `start.sh` with defaults:

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend REST API base URL |
| `NEXT_PUBLIC_WS_URL` | `ws://localhost:8000/api/v1/chat` | WebSocket endpoint for chat |

## API Endpoints

### REST API (v1)

All endpoints prefixed with `/api/v1/`:

**Analysis**
- `POST /deep-insights/autonomous` -- Start autonomous analysis pipeline
- `GET /deep-insights/{task_id}/status` -- Get analysis task status
- `GET /deep-insights` -- List deep insights (paginated)

**Portfolio**
- `GET /portfolio` -- Get portfolio with enriched holdings (live prices, gain/loss, allocation)
- `POST /portfolio` -- Create portfolio
- `POST /portfolio/holdings` -- Add holding
- `PUT /portfolio/holdings/{id}` -- Update holding
- `DELETE /portfolio/holdings/{id}` -- Delete holding
- `GET /portfolio/impact` -- Analyze insight impact on portfolio holdings

**Reports**
- `GET /reports` -- List completed analysis reports (paginated)
- `GET /reports/{task_id}` -- Get full report with insights
- `GET /reports/{task_id}/html` -- Get self-contained HTML report
- `POST /reports/{task_id}/publish` -- Publish report to GitHub Pages

**Research**
- `GET /research` -- List follow-up research (filterable by status/type)
- `GET /research/{id}` -- Get research details
- `POST /research` -- Create and launch follow-up research
- `DELETE /research/{id}` -- Cancel pending/running research

**Knowledge & Track Record**
- `GET /knowledge/patterns` -- List validated patterns (filterable)
- `GET /knowledge/patterns/matching` -- Get patterns matching current market conditions
- `GET /knowledge/patterns/{id}` -- Get specific pattern
- `GET /knowledge/themes` -- List conversation themes
- `GET /knowledge/track-record` -- Get insight accuracy statistics
- `GET /knowledge/track-record/monthly-trend` -- Get monthly success rate trend

**Outcomes**
- `POST /outcomes/start` -- Start tracking an insight's prediction
- `GET /outcomes` -- List tracked outcomes
- `POST /outcomes/check` -- Check and update all active trackers
- `GET /outcomes/summary` -- Get tracking summary statistics

**Other**
- `GET /health` -- Health check
- `GET /docs` -- Interactive Swagger API documentation

### WebSocket

- `ws://localhost:8000/api/v1/chat` -- Real-time chat with tool calling

## Database

SQLite at `backend/data/market-analyzer.db`. Auto-created on first startup via `init_db()`. Schema defined via SQLAlchemy models in `backend/models/`. Missing columns are auto-migrated on startup via `ALTER TABLE ADD COLUMN`.

To reset database:
```bash
rm backend/data/market-analyzer.db
# Restart backend to recreate
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request
