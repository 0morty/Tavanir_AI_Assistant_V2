import structlog
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from scalar_fastapi import DocumentDownloadType, Layout, Theme, get_scalar_api_reference

from src.infrastructure.configs.logging_setup import configure_logging
from src.infrastructure.configs.scalar_config import SCALAR_CONFIGURATION
from src.infrastructure.configs.settings import core_settings
from src.presentation.exception_handlers import register_exception_handlers
from src.presentation.lifespan import lifespan
from src.presentation.routers.router import master_router_v1

# Configure logging early at import time
configure_logging()
logger = structlog.get_logger(__name__)

app = FastAPI(
    title="Tavanir AI Assistant V2",
    description="Enterprise RAG & Suggestion Committee Assistant Service",
    version="2.0.0",
    lifespan=lifespan,
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


@app.get("/", tags=["Root"])
async def root():
    """Root metadata endpoint."""
    return {
        "service": "Tavanir AI Assistant V2",
        "version": "2.0.0",
        "documentation": "/scalar or /docs",
        "health": "/health",
    }


@app.get("/health", tags=["Health"])
async def health():
    """Health check endpoint verifying service liveness."""
    await logger.ainfo("Health check requested")
    return {"status": "ok", "service": "tavanir-ai-assistant-v2"}


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
