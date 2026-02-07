"""Tests for the stocks API endpoints."""

from httpx import AsyncClient


# ---------------------------------------------------------------------------
# GET /api/v1/stocks  (list stocks)
# ---------------------------------------------------------------------------


async def test_list_stocks_empty_db(client: AsyncClient):
    """Listing stocks on an empty database returns an empty list with total 0."""
    response = await client.get("/api/v1/stocks")

    assert response.status_code == 200
    data = response.json()
    assert data["stocks"] == []
    assert data["total"] == 0


async def test_list_stocks_with_data(client: AsyncClient, sample_stock):
    """Listing stocks returns the inserted stock and correct total."""
    response = await client.get("/api/v1/stocks")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["stocks"]) == 1
    assert data["stocks"][0]["symbol"] == "AAPL"
    assert data["stocks"][0]["name"] == "Apple Inc."


async def test_list_stocks_search_filter(client: AsyncClient, sample_stock):
    """Search parameter filters stocks by symbol or name (case-insensitive)."""
    # Match by symbol
    response = await client.get("/api/v1/stocks", params={"search": "aapl"})
    assert response.status_code == 200
    assert response.json()["total"] == 1

    # Match by name
    response = await client.get("/api/v1/stocks", params={"search": "apple"})
    assert response.status_code == 200
    assert response.json()["total"] == 1

    # No match
    response = await client.get("/api/v1/stocks", params={"search": "ZZZZ"})
    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_list_stocks_sector_filter(client: AsyncClient, sample_stock):
    """Sector parameter filters stocks by exact sector value."""
    response = await client.get("/api/v1/stocks", params={"sector": "Technology"})
    assert response.status_code == 200
    assert response.json()["total"] == 1

    response = await client.get("/api/v1/stocks", params={"sector": "Healthcare"})
    assert response.status_code == 200
    assert response.json()["total"] == 0


# ---------------------------------------------------------------------------
# GET /api/v1/stocks/{symbol}  (get stock by symbol)
# ---------------------------------------------------------------------------


async def test_get_stock_found(client: AsyncClient, sample_stock):
    """Getting a stock by its symbol returns the stock details."""
    response = await client.get("/api/v1/stocks/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "AAPL"
    assert data["name"] == "Apple Inc."
    assert data["sector"] == "Technology"
    assert data["is_active"] is True
    assert "id" in data
    assert "created_at" in data


async def test_get_stock_found_case_insensitive(client: AsyncClient, sample_stock):
    """Symbol lookup is case-insensitive (lowercased input still matches)."""
    response = await client.get("/api/v1/stocks/aapl")

    assert response.status_code == 200
    assert response.json()["symbol"] == "AAPL"


async def test_get_stock_not_found(client: AsyncClient):
    """Requesting a non-existent symbol returns 404."""
    response = await client.get("/api/v1/stocks/NOPE")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /api/v1/stocks/{symbol}/history  (price history)
# ---------------------------------------------------------------------------


async def test_get_price_history_with_data(
    client: AsyncClient, sample_stock_with_prices
):
    """Price history endpoint returns all price rows for an existing stock."""
    response = await client.get("/api/v1/stocks/AAPL/history")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 5  # 5 days of sample data

    # Verify the most recent entry (results ordered by date desc)
    first = data[0]
    assert "date" in first
    assert "open" in first
    assert "high" in first
    assert "low" in first
    assert "close" in first
    assert "volume" in first


async def test_get_price_history_empty(client: AsyncClient, sample_stock):
    """Stock exists but has no price rows -- returns an empty list."""
    response = await client.get("/api/v1/stocks/AAPL/history")

    assert response.status_code == 200
    data = response.json()
    assert data == []


async def test_get_price_history_stock_not_found(client: AsyncClient):
    """Price history for a non-existent symbol returns 404."""
    response = await client.get("/api/v1/stocks/NOPE/history")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /api/v1/stocks (search behaviour — acts as stock search)
# ---------------------------------------------------------------------------


async def test_stock_search_partial_match(client: AsyncClient, sample_stock):
    """Search with a partial string matches against symbol or name."""
    response = await client.get("/api/v1/stocks", params={"search": "App"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["stocks"][0]["symbol"] == "AAPL"


async def test_stock_search_no_results(client: AsyncClient, sample_stock):
    """Search with a non-matching string returns zero results."""
    response = await client.get("/api/v1/stocks", params={"search": "XYZ123"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["stocks"] == []
