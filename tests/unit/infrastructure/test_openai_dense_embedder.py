from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from openai import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    RateLimitError,
)

from src.application.exceptions import (
    EmbedderAPIError,
    EmbedderAuthenticationError,
    EmbedderConnectionError,
    EmbedderContextLengthError,
)
from src.infrastructure.services.embeddings.openai_dense_embedder import (
    OpenAIDenseEmbedder,
)


class FakeEmbeddingClient:
    """Duck-typed AsyncOpenAI whose embedding endpoint is mockable."""

    def __init__(self, *, response=None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.create_calls: list[dict] = []

    @property
    def embeddings(self) -> SimpleNamespace:
        return SimpleNamespace(create=self.create)

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


def _make_dummy_response(vectors: list[list[float]]):
    data = [
        SimpleNamespace(index=i, embedding=vec)
        for i, vec in enumerate(vectors)
    ]
    return SimpleNamespace(data=data)


@pytest.mark.asyncio
async def test_embed_documents_success():
    client = FakeEmbeddingClient(response=_make_dummy_response([[0.1, 0.2], [0.3, 0.4]]))
    embedder = OpenAIDenseEmbedder(
        client=client,  # type: ignore
        model_name="test-model",
        dimension=2,
    )
    result = await embedder.embed_documents(["hello", "world"])
    assert result == [[0.1, 0.2], [0.3, 0.4]]
    assert len(client.create_calls) == 1
    assert client.create_calls[0]["input"] == ["hello", "world"]


@pytest.mark.asyncio
async def test_embed_authentication_error_mapped():
    req = httpx.Request("POST", "http://test/v1/embeddings")
    res = httpx.Response(401, request=req, json={"error": {"message": "Invalid API key"}})
    err = AuthenticationError("Invalid API key", response=res, body=None)

    client = FakeEmbeddingClient(error=err)
    embedder = OpenAIDenseEmbedder(
        client=client,  # type: ignore
        model_name="test-model",
        dimension=2,
    )

    with pytest.raises(EmbedderAuthenticationError) as exc_info:
        await embedder.embed_documents(["hello"])
    assert "Authentication failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_embed_context_length_error_mapped():
    req = httpx.Request("POST", "http://test/v1/embeddings")
    res = httpx.Response(422, request=req, json={"error": {"message": "context length exceeded"}})
    err = APIStatusError("context length exceeded", response=res, body={"message": "context length exceeded"})
    err.code = "context_length_exceeded"

    client = FakeEmbeddingClient(error=err)
    embedder = OpenAIDenseEmbedder(
        client=client,  # type: ignore
        model_name="test-model",
        dimension=2,
    )

    with pytest.raises(EmbedderContextLengthError) as exc_info:
        await embedder.embed_documents(["huge text"])
    assert "Context length exceeded" in str(exc_info.value)


@pytest.mark.asyncio
async def test_embed_connection_error_mapped():
    req = httpx.Request("POST", "http://test/v1/embeddings")
    err = APIConnectionError(request=req)

    client = FakeEmbeddingClient(error=err)
    embedder = OpenAIDenseEmbedder(
        client=client,  # type: ignore
        model_name="test-model",
        dimension=2,
    )

    with pytest.raises(EmbedderConnectionError):
        await embedder.embed_documents(["hello"])


@pytest.mark.asyncio
async def test_embed_generic_api_error_mapped():
    req = httpx.Request("POST", "http://test/v1/embeddings")
    res = httpx.Response(500, request=req, json={"error": {"message": "Internal server error"}})
    err = APIStatusError("Internal server error", response=res, body={"message": "Internal server error"})

    client = FakeEmbeddingClient(error=err)
    embedder = OpenAIDenseEmbedder(
        client=client,  # type: ignore
        model_name="test-model",
        dimension=2,
    )

    with pytest.raises(EmbedderAPIError):
        await embedder.embed_documents(["hello"])
