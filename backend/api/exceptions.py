"""Custom exception classes and handlers for the API."""

from fastapi import Request
from fastapi.responses import JSONResponse


class NotFoundError(Exception):
    """Raised when a requested resource is not found."""

    def __init__(self, resource: str, identifier: str | int | None = None):
        self.resource = resource
        self.identifier = identifier
        message = f"{resource} not found"
        if identifier is not None:
            message = f"{resource} with id '{identifier}' not found"
        super().__init__(message)


class ValidationError(Exception):
    """Raised when request validation fails."""

    def __init__(self, message: str, field: str | None = None):
        self.message = message
        self.field = field
        super().__init__(message)


class DataSourceError(Exception):
    """Raised when an external data source fails."""

    def __init__(self, source: str, message: str | None = None):
        self.source = source
        detail = f"Data source '{source}' error"
        if message:
            detail = f"{detail}: {message}"
        super().__init__(detail)


async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    """Handle NotFoundError exceptions."""
    return JSONResponse(
        status_code=404,
        content={
            "success": False,
            "message": str(exc),
            "resource": exc.resource,
            "identifier": exc.identifier,
        },
    )


async def validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    """Handle ValidationError exceptions."""
    content = {
        "success": False,
        "message": exc.message,
    }
    if exc.field:
        content["field"] = exc.field
    return JSONResponse(
        status_code=422,
        content=content,
    )


async def data_source_error_handler(request: Request, exc: DataSourceError) -> JSONResponse:
    """Handle DataSourceError exceptions."""
    return JSONResponse(
        status_code=503,
        content={
            "success": False,
            "message": str(exc),
            "source": exc.source,
        },
    )
