from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from src.infrastructure.configs.logging_setup import configure_logging

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup and shutdown events."""
    configure_logging()
    await logger.ainfo("Tavanir AI Assistant V2 starting up...")

    yield

    await logger.ainfo("Tavanir AI Assistant V2 shutting down...")
