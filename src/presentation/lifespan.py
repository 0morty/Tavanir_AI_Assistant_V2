from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from src.containers import Container

from src.infrastructure.configs.logging_setup import configure_logging

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager initializing logging and dependency injection resources."""
    # 1. Startup phase
    configure_logging()
    await logger.ainfo("Tavanir AI Assistant V2 is starting up...")

    # 2. Bootstrapping Dependency Injection Container
    container = Container()
    await container.init_resources()  # type: ignore
    container.wire(packages=["src.presentation.routers"])
    app.state.container = container

    await logger.ainfo(
        "Dependency Injection container initialized and wired successfully"
    )

    yield

    # 3. Shutdown phase
    await logger.ainfo("Tavanir AI Assistant V2 is shutting down...")
    await container.shutdown_resources()  # type: ignore
    await logger.ainfo("Dependency Injection container resources shut down cleanly")
