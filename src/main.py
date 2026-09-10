import structlog
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.infrastructure.configs.logging_setup import configure_logging
from src.presentation.lifespan import lifespan

# Configure logging at import time for early log capture
configure_logging()
logger = structlog.get_logger(__name__)

app = FastAPI(
    title="Tavanir AI Assistant V2",
    version="2.0.0",
    lifespan=lifespan,
)

# Tracing & CORS Middleware
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["Health"])
async def health():
    """Health check endpoint to verify service liveness."""
    await logger.ainfo("Health check requested")
    return {"status": "ok", "service": "tavanir-ai-assistant-v2"}
