import structlog
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from scalar_fastapi import (
    DocumentDownloadType,
    Layout,
    Theme,
    get_scalar_api_reference,
)

from src.infrastructure.configs.logging_setup import configure_logging
from src.infrastructure.configs.scalar_config import SCALAR_CONFIGURATION
from src.infrastructure.configs.settings import core_settings
from src.presentation.exception_handlers import register_exception_handlers
from src.presentation.lifespan import create_lifespan
from src.presentation.routers.router import master_router_v1
from src.presentation.routers.v1.mock_admin import router as mock_admin_router

# Configure logging early at import time
configure_logging()
logger = structlog.get_logger(__name__)


def create_app(is_mock: bool | None = None) -> FastAPI:
    """Application factory constructing the FastAPI presentation host.

    When is_mock is True (or resolved from core_settings.IS_MOCK), activates
    the decoupled mock presentation layer:
    - Bypasses external driver initialization (PostgreSQL, Qdrant, TEI, Hugging Face).
    - Injects thread-safe in-memory use case doubles.
    - Dynamically mounts the mock administration router (/api/v1/mock/reset).
    - Preserves 100% parity across middleware, exception handlers, schemas, and routes.
    """
    if is_mock is None:
        is_mock = core_settings.IS_MOCK

    app_lifespan = create_lifespan(is_mock=is_mock)

    description = (
        "Enterprise RAG & Suggestion Committee Assistant Service (MOCK MODE)"
        if is_mock
        else "Enterprise RAG & Suggestion Committee Assistant Service"
    )

    app = FastAPI(
        title="Tavanir AI Assistant V2",
        description=description,
        version="2.0.0",
        lifespan=app_lifespan,
    )

    # 1. Tracing & Correlation ID Middleware (Contract 06)
    app.add_middleware(
        CorrelationIdMiddleware,
        header_name="X-Request-Id",
        update_request_header=True,
    )

    # 2. CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 3. Centralized JSON:API Exception Handlers
    register_exception_handlers(app)

    # 4. Static Files Mounting (Serving offline scalar.js bundle)
    app.mount(
        "/static",
        StaticFiles(directory=str(core_settings.STATIC_DIRECTORY)),
        name="static",
    )

    # 5. Route Inclusions
    app.include_router(master_router_v1)

    # Dynamic Mock Administrative Router (mounted only when is_mock is True)
    if is_mock:
        app.include_router(mock_admin_router, prefix="/api/v1")

    @app.get("/", tags=["Root"])
    async def root():
        """Root metadata endpoint."""
        return {
            "service": "Tavanir AI Assistant V2",
            "version": "2.0.0",
            "mockMode": is_mock,
            "documentation": "/scalar or /docs",
            "health": "/health",
        }

    @app.get("/health", tags=["Health"])
    async def health():
        """Health check endpoint verifying service liveness."""
        await logger.ainfo("Health check requested", is_mock=is_mock)
        return {
            "status": "ok",
            "service": "tavanir-ai-assistant-v2",
            "mockMode": is_mock,
        }

    @app.get("/scalar", include_in_schema=False)
    def get_scalar_docs():
        """Offline-capable Scalar interactive API reference."""
        if not app.openapi_url:
            raise ValueError("Scalar docs require an OpenAPI URL to be set.")
        return get_scalar_api_reference(
            openapi_url=app.openapi_url,
            title="Tavanir AI Assistant V2 API Reference",
            scalar_js_url="/static/scalar.js",
            layout=Layout.CLASSIC,
            theme=Theme.BLUE_PLANET,
            document_download_type=DocumentDownloadType.BOTH,
            **SCALAR_CONFIGURATION,
        )

    return app


# Default application instance
app = create_app()

__all__ = ["create_app", "app"]
