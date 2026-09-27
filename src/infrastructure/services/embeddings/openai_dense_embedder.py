from collections.abc import Sequence
from typing import Any

from openai import AsyncOpenAI

from src.application.exceptions import (
    EmbedderAPIError,
    EmbedderConnectionError,
)
from src.application.interfaces.i_dense_embedder import IDenseEmbedder
from src.infrastructure.services.base_openai_service import BaseOpenAIService


class OpenAIDenseEmbedder(IDenseEmbedder, BaseOpenAIService):
    """
    OpenAI-compatible dense vector embedder for TEI (Text Embeddings Inference),
    vLLM, Ollama, and OpenAI API endpoints.
    """

    def __init__(
        self,
        client: AsyncOpenAI,
        model_name: str,
        dimension: int,
        batch_size: int = 512,
        query_prefix: str = "",
        document_prefix: str = "",
        send_dimensions_param: bool = False,
    ):
        if dimension <= 0:
            raise ValueError(f"dimension must be a positive integer, got {dimension}")
        if batch_size <= 0:
            raise ValueError(f"batch_size must be a positive integer, got {batch_size}")

        self._client = client
        self._model_name = model_name
        self._dimension = dimension
        self._batch_size = batch_size
        self._query_prefix = query_prefix
        self._document_prefix = document_prefix
        self._send_dimensions_param = send_dimensions_param

    @property
    def _connection_error_cls(self) -> type[EmbedderConnectionError]:
        return EmbedderConnectionError

    @property
    def _api_error_cls(self) -> type[EmbedderAPIError]:
        return EmbedderAPIError

    @property
    def embedding_dimension(self) -> int:
        """Returns the dimensional size of the vectors produced by this embedder."""
        return self._dimension

    def _prepare_request_kwargs(self, input_data: str | list[str]) -> dict[str, Any]:
        """Constructs the request payload compatible with TEI and OpenAI endpoints."""
        kwargs: dict[str, Any] = {
            "model": self._model_name,
            "input": input_data,
        }
        if self._send_dimensions_param:
            kwargs["dimensions"] = self._dimension
        return kwargs

    async def embed_documents(
        self, texts: Sequence[str], truncate: bool = True
    ) -> list[list[float]]:
        """
        Generates embeddings for a batch of document texts.
        Processed sequentially in sub-batches of size `batch_size`.
        """
        texts_list = list(texts)
        total_texts = len(texts_list)

        if total_texts == 0:
            return []

        # Sanitize empty strings and apply document prefix
        processed_texts = [
            f"{self._document_prefix}{text if text.strip() else ' '}"
            for text in texts_list
        ]

        all_embeddings: list[list[float]] = []

        for i in range(0, total_texts, self._batch_size):
            batch = processed_texts[i : i + self._batch_size]
            req_kwargs = self._prepare_request_kwargs(batch)

            async_request = self._client.embeddings.create(**req_kwargs)
            response = await self._handle_api_call(
                async_request, "embed_documents_batch"
            )

            sorted_items = sorted(response.data, key=lambda item: item.index)
            all_embeddings.extend(item.embedding for item in sorted_items)

        return all_embeddings

    async def embed_query(self, query: str, truncate: bool = True) -> list[float]:
        """Generates an embedding for a search query (asymmetric query mode)."""
        if not query or not query.strip():
            raise ValueError("Query cannot be empty or whitespace.")

        processed_query = f"{self._query_prefix}{query}"
        req_kwargs = self._prepare_request_kwargs(processed_query)

        async_request = self._client.embeddings.create(**req_kwargs)
        response = await self._handle_api_call(async_request, "embed_query")

        return response.data[0].embedding
