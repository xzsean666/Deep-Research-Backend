from fastapi import Request
from fastapi.responses import JSONResponse

from app.schemas.error import ErrorDetail, ErrorResponse
from app.services.crawl.errors import CrawlBlockedError
from app.services.research import SemanticSearchNotImplementedError


class ApiError(Exception):
    code = "INTERNAL_ERROR"
    status_code = 500

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class InvalidRequestError(ApiError):
    code = "INVALID_REQUEST"
    status_code = 400


class NotFoundError(ApiError):
    code = "NOT_FOUND"
    status_code = 404


class UnauthorizedError(ApiError):
    code = "UNAUTHORIZED"
    status_code = 401


class UpstreamUnavailableError(ApiError):
    code = "UPSTREAM_UNAVAILABLE"
    status_code = 502


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _envelope(code: str, message: str, request_id: str) -> dict:
    detail = ErrorDetail(code=code, message=message, request_id=request_id)
    return ErrorResponse(error=detail).model_dump()


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(exc.code, exc.message, _request_id(request)),
    )


async def crawl_blocked_handler(request: Request, exc: CrawlBlockedError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content=_envelope("CRAWL_BLOCKED", exc.reason, _request_id(request)),
    )


async def not_implemented_handler(
    request: Request, exc: SemanticSearchNotImplementedError
) -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content=_envelope(
            "NOT_IMPLEMENTED",
            "mode='semantic' requires an embedding provider, not yet implemented"
            " (see docs/nextsession.md)",
            _request_id(request),
        ),
    )


EXCEPTION_HANDLERS = {
    ApiError: api_error_handler,
    CrawlBlockedError: crawl_blocked_handler,
    SemanticSearchNotImplementedError: not_implemented_handler,
}
