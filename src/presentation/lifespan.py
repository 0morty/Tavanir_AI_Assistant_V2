from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from src.containers import Container

from src.infrastructure.configs.logging_setup import configure_logging
from src.infrastructure.mocks.container_overrides import apply_mock_overrides
from src.infrastructure.mocks.in_memory_suggestion_store import (
    InMemorySuggestionStore,
)

logger = structlog.get_logger(__name__)


def create_lifespan(
    is_mock: bool = False,
) -> Callable[[FastAPI], AsyncGenerator[None, None]]:
    """Factory creating application lifespan manager with mock or production wiring."""

    @asynccontextmanager
    async def app_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        configure_logging()

        if is_mock:
            await logger.ainfo(
                "Tavanir AI Assistant V2 is starting up in MOCK mode..."
            )
            store = InMemorySuggestionStore()
            container = Container()
            apply_mock_overrides(container, store)
            container.wire(packages=["src.presentation.routers"])
            app.state.container = container
            app.state.mock_store = store
            await logger.ainfo(
                "Mock presentation layer wired successfully (zero external dependencies)"
            )
            yield
            await logger.ainfo("Mock presentation layer shut down cleanly")
        else:
            await logger.ainfo("Tavanir AI Assistant V2 is starting up...")
            container = Container()
            await container.init_resources()  # type: ignore
            container.wire(packages=["src.presentation.routers"])
            app.state.container = container
            await logger.ainfo(
                "Dependency Injection container initialized and wired successfully"
            )
            yield
            await logger.ainfo("Tavanir AI Assistant V2 is shutting down...")
            await container.shutdown_resources()  # type: ignore
            await logger.ainfo(
                "Dependency Injection container resources shut down cleanly"
            )

    return app_lifespan


lifespan = create_lifespan(is_mock=False)

__all__ = ["create_lifespan", "lifespan"]
