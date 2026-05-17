from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError

from backend.app.api.v1.router import api_router
from backend.app.core.config import get_settings
from backend.app.core.errors import AppError
from backend.app.core.logging import configure_logging
from backend.app.core.responses import error_json
from backend.app.db.connection import get_connection
from backend.app.db.migrations import init_database


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    @app.on_event("startup")
    def startup() -> None:
        with get_connection() as conn:
            init_database(conn)

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError):
        return error_json(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(_: Request, exc: RequestValidationError):
        message = "; ".join(
            f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        return error_json(422, "VALIDATION_ERROR", message)

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception):
        return error_json(500, "INTERNAL_SERVER_ERROR", str(exc))

    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.default_cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
