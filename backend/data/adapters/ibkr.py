"""Interactive Brokers Client Portal Web API adapter.

Connects to the IBKR Client Portal Gateway running locally (default
https://localhost:5000). The user must authenticate via the gateway's
browser UI before Teletraan can pull portfolio data.

Setup:
    1. Download IB Gateway or TWS
    2. Enable the Client Portal API in gateway settings
    3. Navigate to https://localhost:5000 and log in
    4. Set IBKR_GATEWAY_URL in backend/.env if using a non-default address

The gateway session expires after ~24 hours of inactivity. Call tickle()
periodically or re-authenticate via the browser when it expires.
"""

from __future__ import annotations

import logging
import ssl
from dataclasses import dataclass
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

_GATEWAY_URL_DEFAULT = "https://localhost:5000"


@dataclass
class IBKRPosition:
    """A single position returned from IBKR."""

    account_id: str
    symbol: str
    description: str
    asset_class: str      # STK, OPT, FUT, CASH, etc.
    position: float       # number of shares / contracts
    avg_cost: float       # average cost per share
    market_value: float
    unrealized_pnl: float
    currency: str


@dataclass
class IBKRAccount:
    account_id: str
    account_type: str     # e.g. "PAPER", "INDIVIDUAL"
    display_name: str


class IBKRAdapter:
    """Async client for the IBKR Client Portal REST API.

    Uses a shared aiohttp session; call close() when done (or use as
    an async context manager).
    """

    def __init__(self, gateway_url: str = _GATEWAY_URL_DEFAULT) -> None:
        self._base = gateway_url.rstrip("/")
        # Gateway uses a self-signed TLS cert — disable verification
        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=self._ssl_ctx)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "IBKRAdapter":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def _get(self, path: str) -> Any:
        session = await self._get_session()
        url = f"{self._base}{path}"
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _post(self, path: str, json: dict | None = None) -> Any:
        session = await self._get_session()
        url = f"{self._base}{path}"
        async with session.post(url, json=json or {}) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ------------------------------------------------------------------
    # Auth / session
    # ------------------------------------------------------------------

    async def check_auth(self) -> dict[str, Any]:
        """Return auth status from the gateway.

        Returns a dict with at least:
            authenticated (bool) — whether the session is valid
            connected (bool)     — whether gateway is reachable
        """
        try:
            data = await self._get("/v1/api/iserver/auth/status")
            return {
                "connected": True,
                "authenticated": bool(data.get("authenticated")),
                "competing": bool(data.get("competing")),
                "message": data.get("message", ""),
            }
        except aiohttp.ClientConnectorError:
            return {"connected": False, "authenticated": False, "message": "Gateway unreachable"}
        except Exception as exc:
            return {"connected": True, "authenticated": False, "message": str(exc)}

    async def tickle(self) -> bool:
        """Keep the gateway session alive. Returns True on success."""
        try:
            await self._post("/v1/api/tickle")
            return True
        except Exception as exc:
            logger.warning("IBKR tickle failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------

    async def get_accounts(self) -> list[IBKRAccount]:
        """List all accounts accessible via this gateway session."""
        data = await self._get("/v1/api/portfolio/accounts")
        accounts: list[IBKRAccount] = []
        for item in data:
            accounts.append(IBKRAccount(
                account_id=item.get("id", ""),
                account_type=item.get("type", ""),
                display_name=item.get("displayName") or item.get("id", ""),
            ))
        return accounts

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    async def get_positions(self, account_id: str) -> list[IBKRPosition]:
        """Fetch all positions for an account (paginates automatically)."""
        positions: list[IBKRPosition] = []
        page = 0
        while True:
            data = await self._get(f"/v1/api/portfolio/{account_id}/positions/{page}")
            if not data:
                break
            for item in data:
                asset_class = item.get("assetClass", "STK")
                # Skip non-equity positions (options, futures, forex)
                if asset_class not in ("STK", "ETF"):
                    logger.debug("Skipping %s position: %s", asset_class, item.get("ticker"))
                    continue
                positions.append(IBKRPosition(
                    account_id=account_id,
                    symbol=item.get("ticker", ""),
                    description=item.get("fullName") or item.get("companyName") or "",
                    asset_class=asset_class,
                    position=float(item.get("position", 0)),
                    avg_cost=float(item.get("avgCost", 0)),
                    market_value=float(item.get("mktValue", 0)),
                    unrealized_pnl=float(item.get("unrealizedPnl", 0)),
                    currency=item.get("currency", "USD"),
                ))
            # IBKR paginates in groups of ~30; stop if fewer returned
            if len(data) < 30:
                break
            page += 1
        return positions
