import asyncio
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, NotFoundError

from src.application.context import ContextBuilder
from src.application.exceptions import LLMAPIError, LLMConnectionError
from src.application.interfaces.i_llm_client import ILLMClient
from src.infrastructure.services.llm import OpenAILLMClient

_created_clients: list[OpenAILLMClient] = []


@pytest.fixture(autouse=True)
def _close_created_clients():
    """Every OpenAILLMClient owns a loop thread; close them all after each test."""
    _created_clients.clear()
    yield
    for client in _created_clients:
        client.close()
    _created_clients.clear()


class FakeCompletionClient:
    """Duck-typed AsyncOpenAI whose chat completion and post are scripted."""

    def __init__(
        self,
        content=None,
        *,
        error: Exception | None = None,
        post_error: Exception | None = None,
        batch_contents: list[str] | None = None,
    ) -> None:
        self._content = content
        self._error = error
        self._post_error = post_error
        self._batch_contents = list(batch_contents or [])
        self.kwargs: dict | None = None
        self.create_calls: list[dict] = []
        self.post_path: str | None = None
        self.post_body: dict | None = None

    @property
    def chat(self) -> SimpleNamespace:
        return SimpleNamespace(completions=self)

    async def create(self, **kwargs):
        self.kwargs = kwargs
        self.create_calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))]
        )

    async def post(self, path, *, cast_to=None, body=None, **kwargs):
        self.post_path = path
        self.post_body = body
        if self._post_error is not None:
            raise self._post_error
        count = len(body["messages"])
        contents = self._batch_contents + [""] * count
        return {
            "choices": [
                {"index": i, "message": {"content": contents[i]}} for i in range(count)
            ]
        }


class LoopBindingClient(FakeCompletionClient):
    """Simulates the real ``AsyncOpenAI`` transport: site-bound to the first
    event loop it runs on, failing with ``RuntimeError: Event loop is closed``
    once a later call runs on a different (fresh) loop."""

    def __init__(self, *, content="answer", batch_contents=None, **kwargs) -> None:
        super().__init__(content=content, batch_contents=batch_contents, **kwargs)
        self._bound_loop: asyncio.AbstractEventLoop | None = None

    def _verify_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._bound_loop is None:
            self._bound_loop = loop
        elif self._bound_loop is not loop:
            raise RuntimeError("Event loop is closed")

    async def create(self, **kwargs):
        self._verify_loop()
        return await super().create(**kwargs)

    async def post(self, path, *, cast_to=None, body=None, **kwargs):
        self._verify_loop()
        return await super().post(path, cast_to=cast_to, body=body, **kwargs)


class InvertedBatchClient(FakeCompletionClient):
    """Returns batch choices in reverse index order."""

    async def post(self, path, *, cast_to=None, body=None, **kwargs):
        self.post_path = path
        self.post_body = body
        count = len(body["messages"])
        return {
            "choices": [
                {"index": count - 1 - i, "message": {"content": f"s{count - i}"}}
                for i in range(count)
            ]
        }


class ChoiceBatchClient(FakeCompletionClient):
    """Returns a fixed list of batch choices."""

    def __init__(self, choices: list[dict]) -> None:
        super().__init__("x")
        self._choices = choices

    async def post(self, path, *, cast_to=None, body=None, **kwargs):
        self.post_path = path
        self.post_body = body
        return {"choices": list(self._choices)}


def make_client(client=None, **kwargs) -> OpenAILLMClient:
    if client is None:
        client = FakeCompletionClient(kwargs.pop("content", "answer"))
    tracked = OpenAILLMClient(client, model=kwargs.pop("model", "m"), **kwargs)
    _created_clients.append(tracked)
    return tracked


def test_openai_llm_client_implements_illm_client_port():
    assert isinstance(make_client(), ILLMClient)


def test_openai_llm_client_requires_a_client():
    with pytest.raises(TypeError):
        OpenAILLMClient()


def test_complete_returns_message_content():
    fake = FakeCompletionClient("done")
    client = make_client(client=fake, model="m")

    assert client.complete("prompt") == "done"


@pytest.mark.asyncio
async def test_async_chat_reuses_transport_loop_and_preserves_roles():
    fake = LoopBindingClient(content="done")
    client = make_client(client=fake, model="m")
    assert await asyncio.to_thread(client.complete, "helper prompt") == "done"

    messages = [
        {"role": "system", "content": "instructions"},
        {"role": "user", "content": "suggestion"},
    ]
    assert await client.complete_chat(messages) == "done"
    assert fake.create_calls[1]["messages"] == messages
    assert fake._bound_loop is client._loop


def test_complete_returns_empty_when_content_is_none():
    fake = FakeCompletionClient(None)
    client = make_client(client=fake, model="m")

    assert client.complete("prompt") == ""


def test_complete_passes_generation_parameters_through():
    fake = FakeCompletionClient("answer")
    client = make_client(client=fake, model="m", temperature=0.7, max_tokens=512)

    client.complete("prompt")

    assert fake.kwargs["model"] == "m"
    assert fake.kwargs["temperature"] == 0.7
    assert fake.kwargs["max_tokens"] == 512
    assert fake.kwargs["messages"] == [{"role": "user", "content": "prompt"}]


def test_complete_translates_connection_errors():
    fake = FakeCompletionClient("x", error=APIConnectionError(request=None))
    client = make_client(client=fake, model="m")

    with pytest.raises(LLMConnectionError):
        client.complete("prompt")


def test_complete_many_returns_empty_for_no_prompts():
    fake = FakeCompletionClient("x")
    client = make_client(client=fake, model="m")

    assert client.complete_many([]) == []
    assert fake.post_path is None
    assert fake.create_calls == []


def test_complete_many_sends_one_batch_request_one_conversation_per_prompt():
    fake = FakeCompletionClient("x", batch_contents=["s1", "s2"])
    client = make_client(client=fake, model="m", temperature=0.5, max_tokens=128)

    result = client.complete_many(["p1", "p2"])

    assert result == ["s1", "s2"]
    assert fake.post_path == "/chat/completions/batch"
    assert fake.post_body["model"] == "m"
    assert fake.post_body["temperature"] == 0.5
    assert fake.post_body["max_tokens"] == 128
    assert fake.post_body["messages"] == [
        [{"role": "user", "content": "p1"}],
        [{"role": "user", "content": "p2"}],
    ]
    assert fake.create_calls == []


def test_complete_many_maps_choices_back_to_prompts_by_index():
    fake = InvertedBatchClient("x")
    client = make_client(client=fake, model="m")

    result = client.complete_many(["p1", "p2", "p3"])

    assert result == ["s1", "s2", "s3"]
    assert len(fake.create_calls) == 0


def test_complete_many_falls_back_to_concurrency_when_batch_is_unsupported():
    not_found = NotFoundError(
        "batch endpoint not found",
        response=httpx.Response(
            404,
            request=httpx.Request(
                "POST", "http://localhost/v1/chat/completions/batch"
            ),
        ),
        body=None,
    )
    fake = FakeCompletionClient("canned", post_error=not_found)
    client = make_client(client=fake, model="m", max_concurrency=2)

    result = client.complete_many(["p1", "p2", "p3"])

    assert result == ["canned", "canned", "canned"]
    assert fake.post_path == "/chat/completions/batch"
    assert len(fake.create_calls) == 3
    for call, prompt in zip(fake.create_calls, ["p1", "p2", "p3"]):
        assert call["messages"] == [{"role": "user", "content": prompt}]


def test_complete_many_translates_batch_connection_errors():
    fake = FakeCompletionClient("x", post_error=APIConnectionError(request=None))
    client = make_client(client=fake, model="m")

    with pytest.raises(LLMConnectionError):
        client.complete_many(["p1", "p2"])


def test_complete_many_rejects_choice_count_mismatch():
    fake = ChoiceBatchClient([{"index": 0, "message": {"content": "only-one"}}])
    client = make_client(client=fake, model="m")

    with pytest.raises(LLMAPIError):
        client.complete_many(["p1", "p2"])


def test_complete_many_rejects_out_of_range_choice_index():
    fake = ChoiceBatchClient(
        [
            {"index": 5, "message": {"content": "first"}},
            {"index": 1, "message": {"content": "second"}},
        ]
    )
    client = make_client(client=fake, model="m")

    with pytest.raises(LLMAPIError):
        client.complete_many(["p1", "p2"])


def test_complete_many_returns_empty_for_missing_content():
    fake = ChoiceBatchClient(
        [
            {"index": 0, "message": {"content": None}},
            {"index": 1},
        ]
    )
    client = make_client(client=fake, model="m")

    assert client.complete_many(["p1", "p2"]) == ["", ""]


def test_complete_then_complete_many_reuses_one_event_loop():
    """Regression: two sequential calls on the SAME client must reuse one
    persistent event loop. The site-bound fake fails (``Event loop is
    closed``) if the client bridges with a fresh ``asyncio.run`` loop per
    call, and succeeds once the client owns a long-lived loop."""
    fake = LoopBindingClient(content="done", batch_contents=["b1", "b2"])
    client = make_client(client=fake, model="m")

    assert client.complete("first prompt") == "done"
    assert client.complete_many(["p1", "p2"]) == ["b1", "b2"]
    assert len(fake.create_calls) == 1
    assert fake.post_path == "/chat/completions/batch"


def test_close_is_idempotent():
    client = make_client(content="x")
    client.close()
    client.close()  # second close must be a no-op


def test_complete_after_close_fails_fast():
    client = make_client(content="x")
    client.close()

    with pytest.raises(RuntimeError):
        client.complete("prompt")

@pytest.mark.parametrize('indexes', [(0, 0), (1, 1), (False, True)])
def test_complete_many_rejects_ambiguous_batch_indexes(indexes):
    """Each returned summary must have one unambiguous input position."""
    fake = ChoiceBatchClient([
        {'index': index, 'message': {'content': f'summary-{position}'}}
        for position, index in enumerate(indexes)
    ])
    client = make_client(client=fake)
    with pytest.raises(LLMAPIError, match='choice index'):
        client.complete_many(['evidence-A', 'evidence-B'])
