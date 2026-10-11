"""One error envelope for every failure: {"error": {"code", "message", "details"}}."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.utils.safety import DatabaseUnavailableError

logger = logging.getLogger('VEKA.api')


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers or {}


def error_response(status: int, code: str, message: str, details: dict | None = None, headers=None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={'error': {'code': code, 'message': message, 'details': details or {}}},
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError):
        return error_response(exc.status, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError):
        problems = [{'loc': list(e.get('loc', ())), 'msg': e.get('msg', '')} for e in exc.errors()][:20]
        return error_response(422, 'validation_error', 'The request is invalid.', {'problems': problems})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, exc: StarletteHTTPException):
        code = {404: 'not_found', 405: 'method_not_allowed'}.get(exc.status_code, 'http_error')
        return error_response(exc.status_code, code, str(exc.detail) if exc.detail else code)

    @app.exception_handler(DatabaseUnavailableError)
    async def _db(_request: Request, exc: DatabaseUnavailableError):
        # Query errors are a subclass; neither message is shown (it never contains row values, but stay terse).
        logger.warning('Database error in API request: %s', type(exc).__name__)
        return error_response(503, 'database_unavailable', 'The database is unavailable. Try again shortly.')

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception):
        logger.error('Unhandled API error: %s', type(exc).__name__, exc_info=True)
        return error_response(500, 'internal_error', 'Internal error.')
