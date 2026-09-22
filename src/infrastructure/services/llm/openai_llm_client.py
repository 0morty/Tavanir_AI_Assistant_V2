import asyncio

from openai import AsyncOpenAI

from src.application.exceptions import (
    ApplicationAPIError,
    LLMAPIError,
    LLMAuthenticationError,
    LLMConnectionError,
)
from src.application.interfaces.i_llm_client import ILLMClient
from src.infrastructure.services.base_openai_service import BaseOpenAIService


class OpenAILLMClient(BaseOpenAIService, ILLMClient):
    """OpenAI-compatible concrete adapter for :class:`ILLMClient`.

    Drives chat completions through an injected ``AsyncOpenAI`` client (the one
    pooled by :class:`~src.infrastructure.services.llm.llm_client_registry.LLMClientRegistry`)
    and reuses :class:`BaseOpenAIService` error translation, mapping provider
    failures onto the LLM exception hierarchy (:class:`LLMConnectionError` /
    :class:`LLMAPIError` / :class:`LLMAuthenticationError`).

    ``complete`` is synchronous by contract (the whole Generation pipeline is
    synchronous). It bridges the async client with ``asyncio.run`` and must
    therefore be invoked from a thread without a running event loop (e.g. a
    FastAPI sync endpoint or ``run_in_executor``) -- the same constraint the
    rest of the sync Generation API carries.
    """

    def __init__(
        self,
        client: AsyncOpenAI,
        *,
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> None:
        self._client = client
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    @property
    def _connection_error_cls(self) -> type[Exception]:
        return LLMConnectionError

    @property
    def _api_error_cls(self) -> type[ApplicationAPIError]:
        return LLMAPIError

    @property
    def _auth_error_cls(self) -> type[Exception]:
        return LLMAuthenticationError

    async def _generate(self, prompt: str) -> str:
        async with self._handle_api_call_scope("chat completion"):
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
            return response.choices[0].message.content or ""

    def complete(self, prompt: str) -> str:
        """Return the model's raw completion for ``prompt``."""
        return asyncio.run(self._generate(prompt))