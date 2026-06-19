#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2", "httpx>=0.27"]
# ///
"""Teletraan MCP server — exposes the market-intelligence app to MCP clients (Claude Desktop, etc.).

It proxies the running Teletraan FastAPI backend over HTTP (handling JWT login
automatically) and adds local app-control tools that start/stop the app — those
can't go over HTTP because the app may be down.

This is a self-contained PEP-723 script: `uv run mcp_server.py` resolves the
`mcp` + `httpx` dependencies in an ephemeral environment, so it does NOT depend
on the backend's virtualenv.

Configuration (environment variables):
  TELETRAAN_API_URL   Base URL of the backend (default: http://localhost:8000)
  TELETRAAN_USERNAME  Login username for protected endpoints (default: admin)
  TELETRAAN_PASSWORD  Login password (default: changeme)
  TELETRAAN_DIR       Repo root used by the start/stop tools
                      (default: derived as two levels above this file)
  TELETRAAN_BACKEND_PORT / TELETRAAN_FRONTEND_PORT  Ports for app control (8000/3000)

Claude Desktop registration (claude_desktop_config.json):
  {
    "mcpServers": {
      "teletraan": {
        "command": "uv",
        "args": ["run", "/ABS/PATH/backend/mcp_server.py"]
      }
    }
  }
"""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# --- Configuration -----------------------------------------------------------

API_URL = os.environ.get("TELETRAAN_API_URL", "http://localhost:8000").rstrip("/")
API_V1 = f"{API_URL}/api/v1"
USERNAME = os.environ.get("TELETRAAN_USERNAME", "admin")
PASSWORD = os.environ.get("TELETRAAN_PASSWORD", "changeme")
REPO_DIR = Path(
    os.environ.get("TELETRAAN_DIR", str(Path(__file__).resolve().parent.parent))
)
BACKEND_PORT = os.environ.get("TELETRAAN_BACKEND_PORT", "8000")
FRONTEND_PORT = os.environ.get("TELETRAAN_FRONTEND_PORT", "3000")

mcp = FastMCP("teletraan")

# --- HTTP plumbing with lazy JWT auth ---------------------------------------

_token: str | None = None


async def _login(client: httpx.AsyncClient) -> str:
    """Authenticate and cache an access token."""
    global _token
    resp = await client.post(
        f"{API_V1}/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
    )
    resp.raise_for_status()
    _token = resp.json()["access_token"]
    return _token


async def _request(
    method: str,
    path: str,
    *,
    auth: bool = True,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    """Call a backend endpoint, logging in (and retrying once) on 401.

    Returns parsed JSON on success, or a ``{"error": ...}`` dict so tool calls
    surface a readable message instead of throwing.
    """
    global _token
    url = f"{API_V1}{path}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            for attempt in (1, 2):
                headers = {}
                if auth:
                    headers["Authorization"] = f"Bearer {_token or await _login(client)}"
                resp = await client.request(method, url, headers=headers, json=json, params=params)
                if resp.status_code == 401 and auth and attempt == 1:
                    _token = None  # token expired/invalid — force re-login and retry
                    continue
                if resp.status_code >= 400:
                    return {"error": f"HTTP {resp.status_code}", "detail": resp.text[:500]}
                return resp.json() if resp.content else {}
    except httpx.ConnectError:
        return {
            "error": "Teletraan backend unreachable",
            "hint": f"Is it running at {API_URL}? Use the start_app tool or run ./start.sh.",
        }
    except Exception as exc:  # noqa: BLE001 — surface any failure to the caller
        return {"error": str(exc)}


# --- Market analysis (read-only) --------------------------------------------

@mcp.tool()
async def get_technical_analysis(symbol: str) -> Any:
    """Technical analysis for a stock symbol (indicators, signals, key levels)."""
    return await _request("GET", f"/analysis/technical/{symbol.upper()}")


@mcp.tool()
async def get_patterns(symbol: str) -> Any:
    """Detected chart/price patterns for a symbol."""
    return await _request("GET", f"/analysis/patterns/{symbol.upper()}")


@mcp.tool()
async def get_anomalies(symbol: str) -> Any:
    """Statistical anomalies (volume/price/volatility outliers) for a symbol."""
    return await _request("GET", f"/analysis/anomalies/{symbol.upper()}")


@mcp.tool()
async def get_sector_performance() -> Any:
    """Current sector performance / rotation snapshot."""
    return await _request("GET", "/analysis/sectors")


# --- Autonomous discovery (run under a research policy) ----------------------

@mcp.tool()
async def run_discovery(
    policy: str = "balanced",
    max_insights: int = 10,
    deep_dive_count: int = 12,
) -> Any:
    """Start an autonomous discovery run under a research policy and return a task_id.

    The run is asynchronous (takes minutes). Poll discovery_status(task_id) for
    progress and results.

    Args:
        policy: Research-policy preset — e.g. "balanced", "aggressive_asymmetric",
                "best_bets" (top 1-3 highest-upside short-horizon picks),
                "defensive_income". Requires a backend with research-policy support.
        max_insights: Max final insights to produce.
        deep_dive_count: Number of candidates to deep-dive.
    """
    return await _request(
        "POST",
        "/deep-insights/autonomous/start",
        json={"policy": policy, "max_insights": max_insights, "deep_dive_count": deep_dive_count},
    )


@mcp.tool()
async def discovery_status(task_id: str) -> Any:
    """Progress + results for a discovery run started with run_discovery."""
    return await _request("GET", f"/deep-insights/autonomous/status/{task_id}")


@mcp.tool()
async def recent_discovery() -> Any:
    """The most recent completed/active autonomous discovery run."""
    return await _request("GET", "/deep-insights/autonomous/recent")


# --- Stored insights ---------------------------------------------------------

@mcp.tool()
async def list_insights(
    limit: int = 20,
    action: str | None = None,
    symbol: str | None = None,
    insight_type: str | None = None,
) -> Any:
    """List stored deep insights, optionally filtered by action/symbol/type."""
    params: dict[str, Any] = {"limit": limit}
    if action:
        params["action"] = action.upper()
    if symbol:
        params["symbol"] = symbol.upper()
    if insight_type:
        params["insight_type"] = insight_type
    return await _request("GET", "/deep-insights", params=params)


@mcp.tool()
async def get_insight(insight_id: int) -> Any:
    """Fetch a single stored deep insight by id."""
    return await _request("GET", f"/deep-insights/{insight_id}")


# --- App control (local shell; cannot go over HTTP when the app is down) -----

@mcp.tool()
async def app_health() -> Any:
    """Check whether the backend is up (unauthenticated health probe)."""
    return await _request("GET", "/health", auth=False)


@mcp.tool()
def start_app() -> dict[str, Any]:
    """Launch Teletraan (backend + frontend) via ./start.sh, detached.

    Returns immediately; use app_health to confirm the backend is up. No-op-safe
    to call when already running (ports will just be in use).
    """
    script = REPO_DIR / "start.sh"
    if not script.exists():
        return {"error": f"start.sh not found at {script}. Set TELETRAAN_DIR."}
    try:
        log = open(REPO_DIR / "teletraan-mcp-start.log", "ab")  # noqa: SIM115
        proc = subprocess.Popen(
            ["bash", str(script)],
            cwd=str(REPO_DIR),
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # detach so it survives this tool call
            env={**os.environ, "BACKEND_PORT": BACKEND_PORT, "FRONTEND_PORT": FRONTEND_PORT},
        )
        return {
            "status": "launching",
            "pid": proc.pid,
            "log": str(REPO_DIR / "teletraan-mcp-start.log"),
            "hint": "Give it ~10-20s, then call app_health.",
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@mcp.tool()
def stop_app() -> dict[str, Any]:
    """Stop the Teletraan backend (uvicorn) and frontend (next) on the configured ports."""
    killed: list[str] = []
    for label, port in (("backend", BACKEND_PORT), ("frontend", FRONTEND_PORT)):
        try:
            out = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
                capture_output=True, text=True, timeout=10,
            )
            for pid in filter(None, out.stdout.split()):
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    killed.append(f"{label}:{pid}")
                except ProcessLookupError:
                    pass
        except Exception as exc:  # noqa: BLE001
            killed.append(f"{label}:error({exc})")
    return {"stopped": killed or "nothing was listening on the configured ports"}


if __name__ == "__main__":
    mcp.run()  # stdio transport
