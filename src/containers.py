from collections.abc import AsyncGenerator, Callable

from dependency_injector import containers, providers
from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient

from src.application.context.allocation import (
    CapacityAllocator,
    DemandAllocator,
    RedistributionAllocator,
)
from src.application.context.overflow_strategy_dispatcher import (
    OverflowStrategyDispatcher,
)
from src.application.interfaces.i_capacity_allocator import ICapacityAllocator
from src.application.interfaces.i_demand_allocator import IDemandAllocator
from src.application.interfaces.i_dense_embedder import IDenseEmbedder
from src.application.interfaces.i_overflow_strategy_dispatcher import (
    IOverflowStrategyDispatcher,
)
from src.application.interfaces.i_redistribution_allocator import (
    IRedistributionAllocator,
)
from src.application.interfaces.i_reference_generator import IReferenceGenerator
from src.application.interfaces.i_sparse_embedder import ISparseEmbedder
from src.application.interfaces.i_template_validator import ITemplateValidator
from src.application.interfaces.i_text_normalizer import ITextNormalizer
from src.application.reference.deterministic_reference_generator import (
    DeterministicReferenceGenerator,
)
from src.application.reference.template_validator import TemplateValidator
from src.domain.interfaces import (
    IRegulatoryVectorRepository,
    ISuggestionVectorRepository,
    IUnitOfWork,
)
from src.infrastructure.configs.llm_provider_configs import AsyncOpenAIClientFactory
from src.infrastructure.configs.settings import (
    bm25_settings,
    db_settings,
    embedding_settings,
    qdrant_settings,
)
from src.infrastructure.db import (
    SqlUnitOfWork,
    create_db_engine,
    create_session_factory,
)
from src.infrastructure.db.repositories import (
    QdrantRegulatoryRepository,
    QdrantSuggestionRepository,
    SqlSuggestionRepository,
)
from src.infrastructure.services.embeddings.openai_dense_embedder import (
    OpenAIDenseEmbedder,
)
from src.infrastructure.services.embeddings.persian_bm25_embedder import (
    PersianBm25Embedder,
)
from src.infrastructure.services.llm.llm_client_registry import LLMClientRegistry
from src.infrastructure.services.text_processing.shekar_text_normalizer import (
    ShekarTextNormalizer,
)


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


class Container(containers.DeclarativeContainer):
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
            collection_name=qdrant_settings.QDRANT_SUGGESTION_COLLECTION,
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

    # 6. Regulatory Vector Repository
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

    # 7. Relational Database Engine & Session Factory
    db_engine = providers.Singleton(create_db_engine, url=db_settings.POSTGRES_URL)
    db_session_factory = providers.Singleton(create_session_factory, engine=db_engine)

    # 8. Unit of Work Factory
    unit_of_work: providers.Provider[IUnitOfWork] = providers.Factory(
        SqlUnitOfWork,
        session_factory=db_session_factory,
        suggestion_repo_factory=providers.Object(SqlSuggestionRepository),
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
