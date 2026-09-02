from collections.abc import AsyncGenerator

from dependency_injector import containers, providers
from openai import AsyncOpenAI

from src.application.interfaces.i_dense_embedder import IDenseEmbedder
from src.infrastructure.configs.settings import embedding_settings
from src.infrastructure.services.embeddings.openai_dense_embedder import (
    OpenAIDenseEmbedder,
)
from src.infrastructure.services.llm.llm_client_registry import LLMClientRegistry


async def init_client_registry() -> AsyncGenerator[LLMClientRegistry, None]:
    """Initializes the LLMClientRegistry and guarantees graceful teardown."""
    registry = LLMClientRegistry()
    yield registry
    await registry.close_all()


async def init_embedding_client(
    registry: LLMClientRegistry, provider: str, timeout: float
) -> AsyncOpenAI:
    """Resolves or creates the AsyncOpenAI client for the embedding provider."""
    return await registry.get_client(provider, timeout=timeout)


class Container(containers.DeclarativeContainer):
    # 1. Centralized Registry (Shared across Embedding and future LLM services)
    client_registry = providers.Resource(init_client_registry)

    # 2. Embedding Client Resolution
    embedding_client = providers.Resource(
        init_embedding_client,
        registry=client_registry,
        provider=embedding_settings.EMBEDDING_PROVIDER,
        timeout=embedding_settings.EMBEDDING_TIMEOUT,
    )

    # 3. Dense Embedder Service
    dense_embedder: providers.Provider[IDenseEmbedder] = providers.Singleton(
        OpenAIDenseEmbedder,
        client=embedding_client,
        model_name=embedding_settings.EMBEDDING_MODEL,
        dimension=embedding_settings.EMBEDDING_DIMENSION,
        batch_size=embedding_settings.EMBEDDING_BATCH_SIZE,
        query_prefix=embedding_settings.EMBEDDING_QUERY_PREFIX,
        document_prefix=embedding_settings.EMBEDDING_DOCUMENT_PREFIX,
    )
