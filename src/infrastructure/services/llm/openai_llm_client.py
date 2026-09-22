import asyncio
from collections.abc import Sequence

from openai import AsyncOpenAI, NotFoundError

from src.application.exceptions import (
    ApplicationAPIError,
    LLMAPIError,
    LLMAuthenticationError,
    LLMConnectionError,
)
from src.application.interfaces.i_llm_client import ILLMClient
from src.infrastructure.services.base_openai_service import BaseOpenAIService

_BATCH_PATH = "/chat/completions/batch"
_DEFAULT_MAX_CONCURRENCY = 32


class OpenAILLMClient(BaseOpenAIService, ILLMClient):
    """OpenAI-compatible concrete adapter for :class:`ILLMClient`.

    Drives chat completions through an injected ``AsyncOpenAI`` client (the one
    pooled by :class:`~src.infrastructure.services.llm.llm_client_registry.LLMClientRegistry`)
    and reuses :class:`BaseOpenAIService` error translation, mapping provider
    failures onto the LLM exception hierarchy (:class:`LLMConnectionError` /
    :class:`LLMAPIError` / :class:`LLMAuthenticationError`).

    :meth:`complete_many` prefers vLLM's OpenAI-compatible batch endpoint
    (``POST /v1/chat/completions/batch``): all prompts are sent in one HTTP
    request, each prompt as its own conversation, and the response carries one
    choice per conversation indexed ``0..N-1``. Providers that expose no batch
    endpoint answer with a 404, in which case the client falls back to issuing
    the prompts concurrently (continuous batching) with the completion calls
    bounded by ``max_concurrency``.

    ``complete``/``complete_many`` are synchronous by contract (the whole
    Generation pipeline is synchronous). They bridge the async client with
    ``asyncio.run`` and must therefore be invoked from a thread without a
    running event loop (e.g. a FastAPI sync endpoint or ``run_in_executor``) --
    the same constraint the rest of the sync Generation API carries.
    """

    def __init__(
        self,
        client: AsyncOpenAI,
        *,
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        max_concurrency: int = _DEFAULT_MAX_CONCURRENCY,
    ) -> None:
        self._client = client
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._max_concurrency = max_concurrency

    @property
    def _connection_error_cls(self) -> type[Exception]:
        return LLMConnectionError

    @property
    def _api_error_cls(self) -> type[ApplicationAPIError]:
        return LLMAPIError

    @property
    def _auth_error_cls(self) -> type[Exception]:
        return LLMAuthenticationError

    async def _create(self, prompt: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        return response.choices[0].message.content or ""

    async def _generate(self, prompt: str) -> str:
        async with self._handle_api_call_scope("chat completion"):
            return await self._create(prompt)

    def complete(self, prompt: str) -> str:
        """Return the model's raw completion for ``prompt``."""
        return asyncio.run(self._generate(prompt))

    def complete_many(self, prompts: Sequence[str]) -> list[str]:
        """Return one completion per prompt, preserving ``prompts`` order.

        When the provider supports it, all prompts go through the batch endpoint
        in a single HTTP request; otherwise they fall back to concurrent
        completions bounded by ``max_concurrency``.
        """
        prompts = list(prompts)
        if not prompts:
            return []
        return asyncio.run(self._generate_many(prompts))

    async def _generate_many(self, prompts: list[str]) -> list[str]:
        async with self._handle_api_call_scope("chat completion batch"):
            try:
                data = await self._client.post(
                    _BATCH_PATH,
                    cast_to=dict,
                    body={
                        "model": self._model,
                        "messages": [
                            [{"role": "user", "content": prompt}] for prompt in prompts
                        ],
                        "temperature": self._temperature,
                        "max_tokens": self._max_tokens,
                    },
                )
            except NotFoundError:
                return await self._generate_concurrently(prompts)
            return _extract_batch_results(data, len(prompts))

    async def _generate_concurrently(self, prompts: list[str]) -> list[str]:
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def one(prompt: str) -> str:
            async with semaphore:
                return await self._create(prompt)

        return list(await asyncio.gather(*(one(prompt) for prompt in prompts)))


def _extract_batch_results(data: object, expected: int) -> list[str]:
    """Map each choice of a batch response back onto its prompt by ``index``."""
    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list):
        raise LLMAPIError(f"Unexpected batch response shape: {type(data).__name__}.")
    if len(choices) != expected:
        raise LLMAPIError(
            f"Expected {expected} batch responses but received {len(choices)}."
        )

    results: list[str] = [""] * expected
    for choice in choices:
        if not isinstance(choice, dict):
            raise LLMAPIError("Unexpected batch response choice.")
        index = choice.get("index")
        if not isinstance(index, int) or not 0 <= index < expected:
            raise LLMAPIError(f"Invalid choice index in batch response: {index!r}.")
        message = choice.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        results[index] = content if isinstance(content, str) else ""
    return results