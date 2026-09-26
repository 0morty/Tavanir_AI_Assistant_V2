import asyncio
from collections.abc import Callable

from openai import AsyncOpenAI


class LLMClientRegistry:
    """
    Enterprise-grade Client Registry.
    Manages HTTP connection pooling for AsyncOpenAI clients across different providers,
    ensuring thread-safety and graceful teardown upon application shutdown.
    """

    def __init__(
        self,
        client_factory: Callable[[str, float], AsyncOpenAI],
    ) -> None:
        self._client_factory = client_factory
        self._clients: dict[tuple[str, float], AsyncOpenAI] = {}
        self._lock = asyncio.Lock()

    async def get_client(self, provider_name: str, timeout: float) -> AsyncOpenAI:
        cache_key = (provider_name.lower().strip(), timeout)

        # 1. Fast read path (non-blocking)
        if cache_key in self._clients:
            return self._clients[cache_key]

        # 2. Synchronized write path
        async with self._lock:
            if cache_key not in self._clients:
                client = self._client_factory(provider_name, timeout)
                self._clients[cache_key] = client
            return self._clients[cache_key]

    async def close_all(self) -> None:
        """Closes all underlying HTTP connection pools concurrently and gracefully."""
        if not self._clients:
            return

        await asyncio.gather(
            *(client.close() for client in self._clients.values()),
            return_exceptions=True,
        )
        self._clients.clear()
