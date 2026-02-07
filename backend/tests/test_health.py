"""Tests for the health check API endpoint."""

from httpx import AsyncClient


async def test_health_returns_200(client: AsyncClient):
    """Health endpoint returns HTTP 200 with all expected fields."""
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"
    assert "timestamp" in data
    assert "version" in data


async def test_health_includes_version_info(client: AsyncClient):
    """Health endpoint response contains a non-empty version string."""
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["version"], str)
    assert len(data["version"]) > 0
    # Version should follow semver-ish pattern (e.g. "1.0.0")
    assert data["version"] == "1.0.0"
