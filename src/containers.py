import asyncio
from collections.abc import AsyncGenerator, Callable

import httpx
from dependency_injector import containers, providers
from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient

from src.application.context.allocation import (
    CapacityAllocator,
    DemandAllocator,
    RedistributionAllocator,
)
from src.application.context.context_builder import ContextBuilder
from src.application.context.overflow_strategy_dispatcher import (
    OverflowStrategyDispatcher,
)
from src.application.interfaces import (
    ICapacityAllocator,
    IContextBuilder,
    IDemandAllocator,
    IDenseEmbedder,
    IHistoricalSuggestionExtractor,
    IHybridEmbeddingService,
    ILLMClient,
    IOverflowStrategyDispatcher,
    IQdrantAdminService,
    IRedistributionAllocator,
    IReferenceGenerator,
    IReranker,
    ISparseEmbedder,
    ISuggestionPromptPreparer,
    ITemplateValidator,
    ITextNormalizer,
    ITextSummarizer,
    IUnitOfWork,
)
from src.application.prompt import (
    SuggestionAnalysisPromptConfig,
    SuggestionPromptPreparer,
)
from src.application.reference.deterministic_reference_generator import (
    DeterministicReferenceGenerator,
)
from src.application.reference.reference_cache import ReferenceCache
from src.application.reference.template_validator import TemplateValidator
from src.application.services import HybridEmbeddingService
from src.application.use_cases import (
    AnalyzeSuggestionUseCase,
    BulkDeleteSuggestionsUseCase,
    DeleteSuggestionUseCase,
    ExtractAndIngestHistoricalSuggestionsUseCase,
    IngestSuggestionUseCase,
    UpdateSuggestionUseCase,
)
from src.domain.context.tokenizer import Tokenizer
from src.domain.interfaces import (
    IRegulatoryVectorRepository,
    ISuggestionChunker,
    ISuggestionVectorRepository,
)
from src.infrastructure.configs.llm_provider_configs import AsyncOpenAIClientFactory
from src.infrastructure.configs.settings import (
    bm25_settings,
    db_settings,
    embedding_settings,
    generation_settings,
    historical_ingestion_settings,
    mssql_settings,
    qdrant_settings,
    reranker_settings,
    suggestion_analysis_settings,
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
from src.infrastructure.services.llm import OpenAILLMClient
from src.infrastructure.services.llm.llm_client_registry import LLMClientRegistry
from src.infrastructure.services.qdrant import QdrantAdminService
from src.infrastructure.services.reranker import TEIReranker
from src.infrastructure.services.summarizers import LLMChunkSummarizer, LLMSummarizer
from src.infrastructure.services.text_processing.shekar_text_normalizer import (
    ShekarTextNormalizer,
)
from src.infrastructure.services.tokenizers.gemma_tokenizer import GemmaTokenizer


async def init_client_registry(
    client_factory: Callable[[str, float], AsyncOpenAI],
) -> AsyncGenerator[LLMClientRegistry, None]:
    """Initializes the LLMClientRegistry and guarantees graceful teardown."""
    registry = LLMClientRegistry(client_factory=client_factory)
    yield registry
    await registry.close_all()


async def init_embedding_client(
    registry: LLMClientRegistry, provider: str, timeout: float
) -> AsyncOpenAI:
    """Resolves or creates the AsyncOpenAI client for the embedding provider."""
    return await registry.get_client(provider, timeout=timeout)


async def init_generation_client(
    registry: LLMClientRegistry, provider: str, timeout: float
) -> AsyncOpenAI:
    """Resolves or creates the AsyncOpenAI client for the Generation provider."""
    return await registry.get_client(provider, timeout=timeout)


async def init_llm_client(
    client: AsyncOpenAI,
    model: str,
    temperature: float,
    max_tokens: int,
) -> AsyncGenerator[OpenAILLMClient, None]:
    """Builds the Generation OpenAILLMClient on the pooled provider client and
    guarantees its persistent event loop is shut down on teardown.

    The OpenAILLMClient owns a long-lived event loop (daemon thread) which must
    be closed explicitly; wrapping the client in a Resource makes that teardown
    part of :meth:`Container.init_resources`/``shutdown_resources`` instead of
    leaking the loop thread for the whole process lifetime.
    """
    llm_client = OpenAILLMClient(
        client=client,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    yield llm_client
    llm_client.close()


async def init_tokenizer() -> GemmaTokenizer:
    """Initialize the Hugging Face tokenizer for context overflow handling."""
    from transformers import AutoTokenizer, PreTrainedTokenizerFast

    try:
        raw = AutoTokenizer.from_pretrained(
            generation_settings.TOKENIZER_MODEL, use_fast=True
        )
    except Exception as err:
        raise RuntimeError(
            f"Failed to load tokenizer {generation_settings.TOKENIZER_MODEL!r}: {err}"
        ) from err
    if not isinstance(raw, PreTrainedTokenizerFast):
        raise RuntimeError(
            f"Tokenizer {generation_settings.TOKENIZER_MODEL!r} could not be loaded as a fast tokenizer."
        )
    return GemmaTokenizer(raw)


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
    client_registry = providers.Resource(
        init_client_registry,
        client_factory=providers.Object(AsyncOpenAIClientFactory.create_client),
    )

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

    # 9. Generation Context Allocation Engine
    demand_allocator: providers.Provider[IDemandAllocator] = providers.Singleton(
        DemandAllocator
    )
    redistribution_allocator: providers.Provider[IRedistributionAllocator] = (
        providers.Singleton(RedistributionAllocator)
    )
    capacity_allocator: providers.Provider[ICapacityAllocator] = providers.Singleton(
        CapacityAllocator,
        demand_allocator=demand_allocator,
        redistribution_allocator=redistribution_allocator,
    )

    # 10. Generation Overflow Strategy Dispatch
    overflow_strategy_dispatcher: providers.Provider[IOverflowStrategyDispatcher] = (
        providers.Singleton(OverflowStrategyDispatcher)
    )

    # 11. Generation Reference-Template Building Blocks
    deterministic_reference_generator: providers.Provider[IReferenceGenerator] = (
        providers.Singleton(DeterministicReferenceGenerator)
    )
    template_validator: providers.Provider[ITemplateValidator] = providers.Singleton(
        TemplateValidator
    )

    # 12. Generation Reference Template Cache
    reference_cache: providers.Provider[ReferenceCache] = providers.Singleton(
        ReferenceCache,
        cache_dir=providers.Object(".cache/references"),
    )

    # 13. Generation LLM Client (OpenAI-compatible, connection-pooled)
    generation_client = providers.Resource(
        init_generation_client,
        registry=client_registry,
        provider=generation_settings.LLM_PROVIDER,
        timeout=generation_settings.LLM_TIMEOUT,
    )
    llm_client: providers.Provider[ILLMClient] = providers.Resource(
        init_llm_client,
        client=generation_client,
        model=generation_settings.LLM_MODEL,
        temperature=generation_settings.LLM_TEMPERATURE,
        max_tokens=generation_settings.LLM_MAX_TOKENS,
    )

    # 14. Generation LLM Summarizer (Context overflow SUMMARIZE strategy)
    llm_summarizer: providers.Provider[ITextSummarizer] = providers.Singleton(
        LLMSummarizer,
        llm_client=llm_client,
    )

    # 15. Generation LLM Chunk Summarizer (batch inference, one prompt per chunk)
    chunk_summarizer: providers.Provider[ITextSummarizer] = providers.Singleton(
        LLMChunkSummarizer,
        llm_client=llm_client,
    )

    # 16. Tokenizer for context overflow handling
    tokenizer: providers.Provider[Tokenizer] = providers.Resource(init_tokenizer)

    # 17. Generation Context Builder
    context_builder: providers.Provider[IContextBuilder] = providers.Singleton(
        ContextBuilder,
        tokenizer=tokenizer,
        capacity_allocator=capacity_allocator,
        dispatcher=overflow_strategy_dispatcher,
    )

    # 17.1 Suggestion Analysis Prompt Config
    suggestion_analysis_prompt_config = providers.Object(
        SuggestionAnalysisPromptConfig()
    )

    # 17.2 Suggestion Prompt Preparer
    suggestion_prompt_preparer: providers.Provider[ISuggestionPromptPreparer] = (
        providers.Singleton(
            SuggestionPromptPreparer,
            context_builder=context_builder,
            tokenizer=tokenizer,
            config=suggestion_analysis_prompt_config,
        )
    )

    # 18. Reranker Infrastructure & Port
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

    # 19. Suggestion Analysis Use Case
    analyze_suggestion_use_case: providers.Provider[AnalyzeSuggestionUseCase] = (
        providers.Factory(
            AnalyzeSuggestionUseCase,
            normalizer=text_normalizer,
            embedding_service=hybrid_embedding_service,
            vector_repo=suggestion_vector_repository,
            reranker=reranker,
            uow=unit_of_work,
            prompt_preparer=suggestion_prompt_preparer,
            solution_global_limit=suggestion_analysis_settings.SUGGESTION_ANALYSIS_SOLUTION_LIMIT,
            problem_global_limit=suggestion_analysis_settings.SUGGESTION_ANALYSIS_PROBLEM_LIMIT,
            title_global_limit=suggestion_analysis_settings.SUGGESTION_ANALYSIS_TITLE_LIMIT,
            positive_probe_limit=suggestion_analysis_settings.SUGGESTION_ANALYSIS_POSITIVE_PROBE_LIMIT,
            pending_probe_limit=suggestion_analysis_settings.SUGGESTION_ANALYSIS_PENDING_PROBE_LIMIT,
            top_n_per_status=suggestion_analysis_settings.SUGGESTION_ANALYSIS_TOP_N_PER_STATUS,
            min_score_threshold=suggestion_analysis_settings.SUGGESTION_ANALYSIS_MIN_SCORE_THRESHOLD,
            max_prompt_tokens=suggestion_analysis_settings.SUGGESTION_ANALYSIS_MAX_PROMPT_TOKENS,
        )
    )
