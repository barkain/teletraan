"""Tests for application configuration and custom exception classes.

Config and exception tests are synchronous.
Exception handler tests are async since the handlers are async functions.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from config import Settings, get_settings
from api.exceptions import (
    NotFoundError,
    ValidationError,
    DataSourceError,
    not_found_handler,
    validation_error_handler,
    data_source_error_handler,
)


# ---------------------------------------------------------------------------
# Settings defaults
# ---------------------------------------------------------------------------


class TestSettingsDefaults:
    """Verify Settings loads correct default values."""

    def test_database_url_default(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
        )
        assert settings.DATABASE_URL == "sqlite+aiosqlite:///./data/market-analyzer.db"

    def test_debug_default_false(self):
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.DEBUG is False

    def test_api_prefix_default(self):
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.API_V1_PREFIX == "/api/v1"

    def test_fred_api_key_default_none(self):
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.FRED_API_KEY is None

    def test_finnhub_api_key_default_none(self):
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.FINNHUB_API_KEY is None


# ---------------------------------------------------------------------------
# Settings with environment variable overrides
# ---------------------------------------------------------------------------


class TestSettingsOverrides:
    """Verify Settings picks up environment variable overrides."""

    def test_override_database_url(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.DATABASE_URL == "sqlite+aiosqlite:///./test.db"

    def test_override_debug(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "true")
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.DEBUG is True

    def test_override_api_prefix(self, monkeypatch):
        monkeypatch.setenv("API_V1_PREFIX", "/api/v2")
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.API_V1_PREFIX == "/api/v2"

    def test_override_fred_api_key(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-fred-key-123")
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.FRED_API_KEY == "test-fred-key-123"

    def test_override_finnhub_api_key(self, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "test-finnhub-key-456")
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.FINNHUB_API_KEY == "test-finnhub-key-456"

    def test_case_insensitive_env_vars(self, monkeypatch):
        """Settings model_config has case_sensitive=False."""
        monkeypatch.setenv("debug", "true")
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.DEBUG is True


# ---------------------------------------------------------------------------
# get_settings() factory
# ---------------------------------------------------------------------------


class TestGetSettings:
    """Verify the get_settings() cached factory function."""

    def test_returns_settings_instance(self):
        get_settings.cache_clear()
        result = get_settings()
        assert isinstance(result, Settings)

    def test_caching_returns_same_object(self):
        get_settings.cache_clear()
        first = get_settings()
        second = get_settings()
        assert first is second


# ---------------------------------------------------------------------------
# NotFoundError
# ---------------------------------------------------------------------------


class TestNotFoundError:
    """Tests for the NotFoundError exception class."""

    def test_without_identifier(self):
        exc = NotFoundError("Stock")
        assert exc.resource == "Stock"
        assert exc.identifier is None
        assert str(exc) == "Stock not found"

    def test_with_string_identifier(self):
        exc = NotFoundError("Stock", "AAPL")
        assert exc.resource == "Stock"
        assert exc.identifier == "AAPL"
        assert str(exc) == "Stock with id 'AAPL' not found"

    def test_with_int_identifier(self):
        exc = NotFoundError("Insight", 42)
        assert exc.resource == "Insight"
        assert exc.identifier == 42
        assert str(exc) == "Insight with id '42' not found"

    def test_is_exception(self):
        exc = NotFoundError("Stock")
        assert isinstance(exc, Exception)


# ---------------------------------------------------------------------------
# ValidationError (custom, not Pydantic)
# ---------------------------------------------------------------------------


class TestCustomValidationError:
    """Tests for the custom ValidationError exception class."""

    def test_message_only(self):
        exc = ValidationError("Invalid symbol format")
        assert exc.message == "Invalid symbol format"
        assert exc.field is None
        assert str(exc) == "Invalid symbol format"

    def test_with_field(self):
        exc = ValidationError("Must be positive", field="confidence")
        assert exc.message == "Must be positive"
        assert exc.field == "confidence"

    def test_is_exception(self):
        exc = ValidationError("Bad input")
        assert isinstance(exc, Exception)


# ---------------------------------------------------------------------------
# DataSourceError
# ---------------------------------------------------------------------------


class TestDataSourceError:
    """Tests for the DataSourceError exception class."""

    def test_source_only(self):
        exc = DataSourceError("yfinance")
        assert exc.source == "yfinance"
        assert str(exc) == "Data source 'yfinance' error"

    def test_with_message(self):
        exc = DataSourceError("FRED", "Connection timeout")
        assert exc.source == "FRED"
        assert str(exc) == "Data source 'FRED' error: Connection timeout"

    def test_is_exception(self):
        exc = DataSourceError("finnhub")
        assert isinstance(exc, Exception)


# ---------------------------------------------------------------------------
# Exception handlers (async)
# ---------------------------------------------------------------------------


def _make_mock_request() -> MagicMock:
    """Create a minimal mock Request object for handler tests."""
    mock_req = MagicMock()
    mock_req.url = "http://test/api/v1/stocks/999"
    mock_req.method = "GET"
    return mock_req


class TestNotFoundHandler:
    """Tests for the not_found_handler async function."""

    async def test_returns_404(self):
        exc = NotFoundError("Stock", 999)
        resp = await not_found_handler(_make_mock_request(), exc)
        assert resp.status_code == 404

    async def test_response_body(self):
        exc = NotFoundError("Stock", 999)
        resp = await not_found_handler(_make_mock_request(), exc)
        body = resp.body.decode()
        assert '"success":false' in body.lower().replace(" ", "")
        assert "Stock" in body
        assert "999" in body

    async def test_without_identifier(self):
        exc = NotFoundError("Insight")
        resp = await not_found_handler(_make_mock_request(), exc)
        assert resp.status_code == 404
        body = resp.body.decode()
        assert "Insight not found" in body


class TestValidationErrorHandler:
    """Tests for the validation_error_handler async function."""

    async def test_returns_422(self):
        exc = ValidationError("Invalid format")
        resp = await validation_error_handler(_make_mock_request(), exc)
        assert resp.status_code == 422

    async def test_response_body_without_field(self):
        exc = ValidationError("Bad input")
        resp = await validation_error_handler(_make_mock_request(), exc)
        body = resp.body.decode()
        assert "Bad input" in body
        assert '"field"' not in body

    async def test_response_body_with_field(self):
        exc = ValidationError("Must be positive", field="confidence")
        resp = await validation_error_handler(_make_mock_request(), exc)
        body = resp.body.decode()
        assert "Must be positive" in body
        assert "confidence" in body


class TestDataSourceErrorHandler:
    """Tests for the data_source_error_handler async function."""

    async def test_returns_503(self):
        exc = DataSourceError("yfinance")
        resp = await data_source_error_handler(_make_mock_request(), exc)
        assert resp.status_code == 503

    async def test_response_body(self):
        exc = DataSourceError("FRED", "API rate limit exceeded")
        resp = await data_source_error_handler(_make_mock_request(), exc)
        body = resp.body.decode()
        assert "FRED" in body
        assert "API rate limit exceeded" in body


# ---------------------------------------------------------------------------
# Exception handler registration on the FastAPI app
# ---------------------------------------------------------------------------


class TestExceptionHandlerRegistration:
    """Verify that custom exception handlers are registered on the app."""

    def test_not_found_handler_registered(self):
        from main import app

        assert NotFoundError in app.exception_handlers

    def test_validation_error_handler_registered(self):
        from main import app

        assert ValidationError in app.exception_handlers

    def test_data_source_error_handler_registered(self):
        from main import app

        assert DataSourceError in app.exception_handlers
