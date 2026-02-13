# ![Teletraan](frontend/public/teletraan-hero.png)

# Teletraan

> AI-powered market intelligence platform with autonomous multi-agent analysis, portfolio tracking, and pattern recognition.

<div align="center">

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109%2B-green)](https://fastapi.tiangolo.com/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16.1-black)](https://nextjs.org/)
[![Claude Agent SDK](https://img.shields.io/badge/Claude%20Agent%20SDK-LLM-purple)](https://github.com/anthropics/anthropic-sdk-python)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

## Features

- **Autonomous 6-Phase Analysis** -- Scans macro conditions, rotates sectors, hunts opportunities, deep-dives candidates, evaluates coverage, and synthesizes insights
- **Multi-Agent Deep Analysis** -- Five specialist analysts (Macro Economist, Sector Strategist, Technical Analyst, Risk Analyst, Correlation Detective) run in parallel, aggregated by a Synthesis Lead
- **Portfolio Tracking** -- Holdings CRUD with live prices, insight impact analysis, and portfolio-aware discovery
- **Pattern Recognition** -- LLM-based extraction of repeatable trading patterns with automatic deduplication and quality validation
- **Prediction Track Record** -- Outcome tracking, monthly trend analysis, and pattern success rate feedback loops
- **Research Hub** -- Spawn follow-up research from conversations with background execution and provenance linking
- **Published Reports** -- Self-contained HTML reports auto-published to GitHub Pages
- **Real-Time Chat** -- WebSocket-based conversational analysis with 10 market data tools
- **7 LLM Providers** -- Anthropic, Bedrock, Vertex, Azure, z.ai, Ollama, Claude Code subscription
- **Desktop App** -- Native packaging via Tauri v2 with CI builds for macOS and Windows

## Install

Download the latest desktop app from [Releases](https://github.com/barkain/teletraan/releases):
- **macOS**: `Teletraan_x.x.x_aarch64.dmg` (Apple Silicon) or `_x64.dmg` (Intel)
- **Windows**: `Teletraan_x.x.x_x64-setup.msi`

Or run from source -- see [Quick Start](#quick-start).

## Quick Start

### Prerequisites

- **Python 3.11+** with [`uv`](https://github.com/astral-sh/uv)
- **Node.js 18+** with `npm`

### Install and Run

```bash
git clone https://github.com/yourusername/teletraan.git
cd teletraan
./start.sh
```

This installs all dependencies, creates `.env` files, starts both services, and opens your browser.

```
Frontend:  http://localhost:3000
API Docs:  http://localhost:8000/docs
```

Custom ports:
```bash
BACKEND_PORT=8001 FRONTEND_PORT=3001 ./start.sh
```

## Architecture

![Teletraan System Architecture](docs/teletraan-architecture.png)

FastAPI backend (Python) + Next.js 16 frontend (TypeScript/React 19) with SQLite storage, Claude Agent SDK for multi-agent LLM orchestration, and data from Yahoo Finance, FRED, and Finnhub.

See [docs/architecture.md](docs/architecture.md) for the full system diagram, pipeline details, and project structure.

## Documentation

| Topic | Link |
|-------|------|
| Architecture | [docs/architecture.md](docs/architecture.md) |
| LLM Providers | [docs/llm-providers.md](docs/llm-providers.md) |
| Publishing Reports | [docs/publishing.md](docs/publishing.md) |
| Desktop App | [docs/desktop-app.md](docs/desktop-app.md) |
| Development Guide | [docs/development.md](docs/development.md) |

Additional references:
- **[CLAUDE.md](CLAUDE.md)** -- Developer guidance: architecture patterns, commands, key modules
- **Swagger UI** -- Interactive API docs at `http://localhost:8000/docs` when running

## License

Teletraan is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.

---

<div align="center">

**Built with FastAPI, Next.js, and Claude Agent SDK**

[Report Bug](https://github.com/yourusername/teletraan/issues) · [Request Feature](https://github.com/yourusername/teletraan/issues)

</div>
