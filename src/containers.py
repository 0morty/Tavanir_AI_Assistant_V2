import asyncio
from collections.abc import AsyncGenerator

import httpx
from dependency_injector import containers, providers
from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient

from src.application.interfaces import (
    IDenseEmbedder,
    IHistoricalSuggestionExtractor,
    IHybridEmbeddingService,
    IQdrantAdminService,
    IReranker,
    ISparseEmbedder,
    ITextNormalizer,
    IUnitOfWork,
)
from src.application.services import HybridEmbeddingService
from src.application.use_cases import (
    BulkDeleteSuggestionsUseCase,
    DeleteSuggestionUseCase,
    ExtractAndIngestHistoricalSuggestionsUseCase,
    IngestSuggestionUseCase,
    UpdateSuggestionUseCase,
)
from src.domain.interfaces import (
    IRegulatoryVectorRepository,
    ISuggestionChunker,
    ISuggestionVectorRepository,
)
from src.infrastructure.configs.settings import (
    bm25_settings,
    db_settings,
    embedding_settings,
    historical_ingestion_settings,
    mssql_settings,
    qdrant_settings,
    reranker_settings,
)
from src.infrastructure.db import (
    SqlUnitOfWork,
    create_db_engine,
    create_session_factory,
)
from src.infrastructure.db.repositories import (
    QdrantRegulatoryRepository,
    QdrantSuggestionRepository,
    SqlCheckpointRepository,
    SqlSkippedSuggestionRepository,
    SqlSuggestionRepository,
)
from src.infrastructure.services.chunkers import FieldAwareSuggestionChunker
from src.infrastructure.services.embeddings.openai_dense_embedder import (
    OpenAIDenseEmbedder,
)
from src.infrastructure.services.embeddings.persian_bm25_embedder import (
    PersianBm25Embedder,
)
from src.infrastructure.services.extractors import MssqlSuggestionExtractor
from src.infrastructure.services.llm.llm_client_registry import LLMClientRegistry
from src.infrastructure.services.qdrant import QdrantAdminService
from src.infrastructure.services.reranker import TEIReranker
from src.infrastructure.services.text_processing.shekar_text_normalizer import (
    ShekarTextNormalizer,
)


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


async def init_reranker_client(
    connect_timeout: float, read_timeout: float
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Initializes a pooled httpx.AsyncClient for TEI reranker with graceful shutdown."""
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=2.0,
            pool=1.0,
        ),
        limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
    )
    try:
        yield client
    finally:
        await client.aclose()


class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(
        packages=["src.presentation.routers"],
    )

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

    # 4. Sparse Embedder Service (BM25)
    sparse_embedder: providers.Provider[ISparseEmbedder] = providers.Singleton(
        PersianBm25Embedder,
        config=bm25_settings,
    )

    # 5. Text Normalizer Service
    text_normalizer: providers.Provider[ITextNormalizer] = providers.Singleton(
        ShekarTextNormalizer
    )

    # 6. Hybrid Embedding Service (Application Service)
    hybrid_embedding_service: providers.Provider[IHybridEmbeddingService] = (
        providers.Factory(
            HybridEmbeddingService,
            dense_embedder=dense_embedder,
            sparse_embedder=sparse_embedder,
        )
    )

    # 6. Qdrant Client (Singleton)
    qdrant_client: providers.Provider[AsyncQdrantClient] = providers.Singleton(
        AsyncQdrantClient,
        host=qdrant_settings.QDRANT_HOST,
        port=qdrant_settings.QDRANT_PORT,
        grpc_port=qdrant_settings.QDRANT_GRPC_PORT,
        api_key=qdrant_settings.QDRANT_API_KEY,
        prefer_grpc=qdrant_settings.QDRANT_PREFER_GRPC,
        https=qdrant_settings.QDRANT_HTTPS,
        check_compatibility=False,
    )

    # 5. Suggestion Vector Repository
    suggestion_vector_repository: providers.Provider[ISuggestionVectorRepository] = (
        providers.Singleton(
            QdrantSuggestionRepository,
            client=qdrant_client,
            collection_name=qdrant_settings.QDRANT_SUGGESTION_ALIAS,
            dense_vector_name=qdrant_settings.QDRANT_DENSE_VECTOR_NAME,
            sparse_vector_name=qdrant_settings.QDRANT_SPARSE_VECTOR_NAME,
            default_dense_dim=embedding_settings.EMBEDDING_DIMENSION,
            batch_size=qdrant_settings.QDRANT_BATCH_SIZE,
            dense_score_threshold=qdrant_settings.QDRANT_DENSE_SCORE_THRESHOLD,
            sparse_score_threshold=qdrant_settings.QDRANT_SPARSE_SCORE_THRESHOLD,
            max_retries=qdrant_settings.QDRANT_MAX_RETRIES,
            retry_base_delay=qdrant_settings.QDRANT_RETRY_BASE_DELAY,
            retry_max_delay=qdrant_settings.QDRANT_RETRY_MAX_DELAY,
        )
    )

    # 6. Qdrant Admin Service
    qdrant_admin_service: providers.Provider[IQdrantAdminService] = providers.Singleton(
        QdrantAdminService,
        client=qdrant_client,
    )

    # 7. Regulatory Vector Repository
    regulatory_vector_repository: providers.Provider[IRegulatoryVectorRepository] = (
        providers.Singleton(
            QdrantRegulatoryRepository,
            client=qdrant_client,
            collection_name=qdrant_settings.QDRANT_REGULATORY_COLLECTION,
            dense_vector_name=qdrant_settings.QDRANT_DENSE_VECTOR_NAME,
            sparse_vector_name=qdrant_settings.QDRANT_SPARSE_VECTOR_NAME,
            default_dense_dim=embedding_settings.EMBEDDING_DIMENSION,
            batch_size=qdrant_settings.QDRANT_BATCH_SIZE,
            dense_score_threshold=qdrant_settings.QDRANT_DENSE_SCORE_THRESHOLD,
            sparse_score_threshold=qdrant_settings.QDRANT_SPARSE_SCORE_THRESHOLD,
            max_retries=qdrant_settings.QDRANT_MAX_RETRIES,
            retry_base_delay=qdrant_settings.QDRANT_RETRY_BASE_DELAY,
            retry_max_delay=qdrant_settings.QDRANT_RETRY_MAX_DELAY,
        )
    )

    # 8. Relational Database Engine & Session Factory
    db_engine = providers.Singleton(create_db_engine, url=db_settings.POSTGRES_URL)
    db_session_factory = providers.Singleton(create_session_factory, engine=db_engine)

    # 9. Unit of Work Factory
    unit_of_work: providers.Provider[IUnitOfWork] = providers.Factory(
        SqlUnitOfWork,
        session_factory=db_session_factory,
        suggestion_repo_factory=providers.Object(SqlSuggestionRepository),
        checkpoint_repo_factory=providers.Object(SqlCheckpointRepository),
        skipped_repo_factory=providers.Object(SqlSkippedSuggestionRepository),
    )

    # 10. Suggestion Chunker Strategy
    suggestion_chunker: providers.Provider[ISuggestionChunker] = providers.Factory(
        FieldAwareSuggestionChunker
    )

    # 11. Suggestion Ingestion Use Case
    ingest_suggestion_use_case: providers.Provider[IngestSuggestionUseCase] = (
        providers.Factory(
            IngestSuggestionUseCase,
            uow=unit_of_work,
            normalizer=text_normalizer,
            chunker=suggestion_chunker,
            embedding_service=hybrid_embedding_service,
            vector_repo=suggestion_vector_repository,
        )
    )

    # 12. Historical Suggestion Extractor
    historical_extractor: providers.Provider[IHistoricalSuggestionExtractor] = (
        providers.Singleton(
            MssqlSuggestionExtractor,
            config=mssql_settings,
        )
    )

    # 13. Historical Suggestion Ingestion Use Case
    extract_and_ingest_historical_suggestions_use_case: providers.Provider[
        ExtractAndIngestHistoricalSuggestionsUseCase
    ] = providers.Factory(
        ExtractAndIngestHistoricalSuggestionsUseCase,
        uow=unit_of_work,
        extractor=historical_extractor,
        normalizer=text_normalizer,
        chunker=suggestion_chunker,
        embedding_service=hybrid_embedding_service,
        vector_repo=suggestion_vector_repository,
        job_name=historical_ingestion_settings.CHECKPOINT_JOB_NAME,
    )

    # 14. Suggestion Update Use Case
    update_suggestion_use_case: providers.Provider[UpdateSuggestionUseCase] = (
        providers.Factory(
            UpdateSuggestionUseCase,
            uow=unit_of_work,
            normalizer=text_normalizer,
            chunker=suggestion_chunker,
            embedding_service=hybrid_embedding_service,
            vector_repo=suggestion_vector_repository,
        )
    )

    # 15. Suggestion Delete Use Case
    delete_suggestion_use_case: providers.Provider[DeleteSuggestionUseCase] = (
        providers.Factory(
            DeleteSuggestionUseCase,
            uow=unit_of_work,
            vector_repo=suggestion_vector_repository,
        )
    )

    # 16. Suggestion Bulk Delete Use Case
    bulk_delete_suggestions_use_case: providers.Provider[
        BulkDeleteSuggestionsUseCase
    ] = providers.Factory(
        BulkDeleteSuggestionsUseCase,
        delete_use_case=delete_suggestion_use_case,
    )

    # 17. Reranker Infrastructure & Port
    reranker_semaphore = providers.Singleton(
        asyncio.Semaphore,
        value=reranker_settings.RERANKER_MAX_CONCURRENT_REQUESTS,
    )

    reranker_client = providers.Resource(
        init_reranker_client,
        connect_timeout=reranker_settings.RERANKER_CONNECT_TIMEOUT,
        read_timeout=reranker_settings.RERANKER_READ_TIMEOUT,
    )

    reranker: providers.Provider[IReranker] = providers.Singleton(
        TEIReranker,
        client=reranker_client,
        settings=reranker_settings,
        semaphore=reranker_semaphore,
    )
