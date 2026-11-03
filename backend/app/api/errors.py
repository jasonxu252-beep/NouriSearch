"""One error shape for every failure, so clients handle errors in one place."""

import structlog
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

log = structlog.get_logger()


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: list[dict[str, object]] | None = None


class NotFoundError(Exception):
    def __init__(self, resource: str, identifier: object) -> None:
        super().__init__(f"{resource} {identifier!r} was not found.")
        self.resource = resource
        self.identifier = identifier


class InvalidRequestError(Exception):
    """A well-formed request that cannot apply to the thing it names."""


def _error(
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, object]] | None = None,
) -> JSONResponse:
    body = ErrorResponse(code=code, message=message, details=details)
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body, exclude_none=True))


async def _not_found(_: Request, exc: Exception) -> JSONResponse:
    return _error(status.HTTP_404_NOT_FOUND, "not_found", str(exc))


async def _invalid_request(_: Request, exc: Exception) -> JSONResponse:
    return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_request", str(exc))


async def _validation(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details: list[dict[str, object]] = [
        {"field": ".".join(str(part) for part in e["loc"]), "problem": e["msg"]}
        for e in exc.errors()
    ]
    return _error(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "invalid_request",
        "The request has invalid fields.",
        details,
    )


async def _http(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    return _error(exc.status_code, f"http_{exc.status_code}", str(exc.detail))


async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled_exception", exc_info=exc)
    return _error(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "internal_error",
        "Something went wrong on our side.",
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NotFoundError, _not_found)
    app.add_exception_handler(InvalidRequestError, _invalid_request)
    app.add_exception_handler(RequestValidationError, _validation)
    app.add_exception_handler(HTTPException, _http)
    app.add_exception_handler(Exception, _unhandled)
