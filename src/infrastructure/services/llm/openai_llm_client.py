import asyncio
import threading
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import TypeVar

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
_LOOP_SHUTDOWN_TIMEOUT = 5.0

T = TypeVar("T")


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

    ``complete``/``complete_many`` serve synchronous helpers and bridge the async
    ``AsyncOpenAI`` API. Bridging with a throwaway ``asyncio.run`` per call is
    broken: it creates and closes one event loop per call, whereas the
    ``httpx.AsyncClient`` wrapped by ``AsyncOpenAI`` binds lazily to the *first*
    loop it runs on -- once that loop is closed, every later call using the same
    shared client fails with ``RuntimeError: Event loop is closed`` (reproduced
    as a real client lifecycle bug, independent of any test).

    Instead, this instance owns a single long-lived event loop running in a
    dedicated daemon thread. Every call submits its coroutine onto that loop via
    :func:`asyncio.run_coroutine_threadsafe` and blocks on the result, so
    repeated calls on the same ``OpenAILLMClient`` reuse one running loop and
    never touch a closed one. ``complete_chat`` schedules onto that same loop
    and awaits its result without blocking the caller's event loop. Call
    :meth:`close` from DI resource teardown; it is idempotent.
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
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever,
            name="OpenAILLMClient-loop",
            daemon=True,
        )
        self._loop_thread.start()
        self._closed = False

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

    def _run_on_loop(self, coro_factory: Callable[[], Awaitable[T]]) -> T:
        """Run the coroutine produced by ``coro_factory`` to completion on the
        client's persistent event loop."""
        if self._closed:
            raise RuntimeError(
                "OpenAILLMClient has been closed; its event loop is no longer running."
            )
        future = asyncio.run_coroutine_threadsafe(coro_factory(), self._loop)
        return future.result()

    async def complete_chat(self, messages: Sequence[Mapping[str, str]]) -> str:
        """Send chat messages without blocking the caller's event loop."""
        if self._closed:
            raise RuntimeError("OpenAILLMClient has been closed")
        if not messages:
            raise ValueError("Chat completion requires at least one message")
        chat_messages = [
            {"role": message["role"], "content": message["content"]}
            for message in messages
        ]
        future = asyncio.run_coroutine_threadsafe(
            self._complete_chat(chat_messages), self._loop
        )
        return await asyncio.wrap_future(future)

    async def _complete_chat(self, messages: list[dict[str, str]]) -> str:
        async with self._handle_api_call_scope("chat completion"):
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
            return response.choices[0].message.content or ""

    def complete(self, prompt: str) -> str:
        """Return the model's raw completion for ``prompt``."""
        return self._run_on_loop(lambda: self._generate(prompt))

    def complete_many(self, prompts: Sequence[str]) -> list[str]:
        """Return one completion per prompt, preserving ``prompts`` order.

        When the provider supports it, all prompts go through the batch endpoint
        in a single HTTP request; otherwise they fall back to concurrent
        completions bounded by ``max_concurrency``.
        """
        prompts = list(prompts)
        if not prompts:
            return []
        return self._run_on_loop(lambda: self._generate_many(prompts))

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

    def close(self) -> None:
        """Stop the persistent event loop and release its daemon thread.

        Idempotent: a second call is a no-op. Pending tasks are cancelled first
        so the loop can stop cleanly. After ``close``, further calls on this
        instance fail fast with a clear :class:`RuntimeError` instead of
        quietly reusing a closed event loop.
        """
        if self._closed:
            return
        self._closed = True

        # The injected AsyncOpenAI is pool-managed, but its internal httpx
        # transport is bound to THIS persistent loop (that is how the real
        # client keeps working across calls). It must therefore be closed here,
        # while the loop is still alive; the registry's later close_all() then
        # finds it already closed and becomes a no-op. Fakes without a ``close``
        # (used by unit tests) are tolerated.
        client_close = getattr(self._client, "close", None)
        if client_close is not None:
            try:
                asyncio.run_coroutine_threadsafe(client_close(), self._loop).result(
                    timeout=_LOOP_SHUTDOWN_TIMEOUT
                )
            except Exception:
                pass

        async def _finalize() -> None:
            current = asyncio.current_task()
            pending = [t for t in asyncio.all_tasks() if t is not current]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        try:
            future = asyncio.run_coroutine_threadsafe(_finalize(), self._loop)
            future.result(timeout=_LOOP_SHUTDOWN_TIMEOUT)
        except Exception:
            # The loop thread may be mid-request; it is daemon so it cannot hold
            # the process open. Stop and join anyway.
            pass
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop_thread.join(timeout=_LOOP_SHUTDOWN_TIMEOUT)
        if not self._loop.is_closed():
            self._loop.close()


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
    seen_indexes: set[int] = set()
    for choice in choices:
        if not isinstance(choice, dict):
            raise LLMAPIError("Unexpected batch response choice.")
        index = choice.get("index")
        if type(index) is not int or not 0 <= index < expected:
            raise LLMAPIError(f"Invalid choice index in batch response: {index!r}.")
        if index in seen_indexes:
            raise LLMAPIError(f"Duplicate choice index in batch response: {index}.")
        seen_indexes.add(index)
        message = choice.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        results[index] = content if isinstance(content, str) else ""
    return results