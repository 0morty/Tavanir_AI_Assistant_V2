from types import SimpleNamespace

import pytest
from openai import APIConnectionError

from src.application.context import ContextBuilder
from src.application.exceptions import LLMConnectionError
from src.application.interfaces.i_llm_client import ILLMClient
from src.infrastructure.services.llm import OpenAILLMClient


class FakeCompletionClient:
    """Duck-typed AsyncOpenAI whose chat completion is scripted."""

    def __init__(self, content: str, *, error: Exception | None = None) -> None:
        self._content = content
        self._error = error
        self.kwargs: dict | None = None

    @property
    def chat(self) -> SimpleNamespace:
        return SimpleNamespace(completions=self)

    async def create(self, **kwargs):
        self.kwargs = kwargs
        if self._error is not None:
            raise self._error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))]
        )


def make_client(**kwargs) -> OpenAILLMClient:
    return OpenAILLMClient(
        FakeCompletionClient(kwargs.pop("content", "answer")),
        model=kwargs.pop("model", "m"),
        **kwargs,
    )


def test_openai_llm_client_implements_illm_client_port():
    assert isinstance(make_client(), ILLMClient)


def test_openai_llm_client_requires_a_client():
    with pytest.raises(TypeError):
        OpenAILLMClient()


def test_complete_returns_message_content():
    fake = FakeCompletionClient("done")
    client = OpenAILLMClient(fake, model="m")

    assert client.complete("prompt") == "done"


def test_complete_returns_empty_when_content_is_none():
    fake = FakeCompletionClient(None)
    client = OpenAILLMClient(fake, model="m")

    assert client.complete("prompt") == ""


def test_complete_passes_generation_parameters_through():
    fake = FakeCompletionClient("answer")
    client = OpenAILLMClient(
        fake, model="m", temperature=0.7, max_tokens=512
    )

    client.complete("prompt")

    assert fake.kwargs["model"] == "m"
    assert fake.kwargs["temperature"] == 0.7
    assert fake.kwargs["max_tokens"] == 512
    assert fake.kwargs["messages"] == [{"role": "user", "content": "prompt"}]


def test_complete_translates_connection_errors():
    fake = FakeCompletionClient("x", error=APIConnectionError(request=None))
    client = OpenAILLMClient(fake, model="m")

    with pytest.raises(LLMConnectionError):
        client.complete("prompt")