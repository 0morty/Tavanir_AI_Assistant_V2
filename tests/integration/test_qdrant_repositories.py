from __future__ import annotations

import uuid

import pytest
from qdrant_client import AsyncQdrantClient, models
from src.containers import Container
from src.infrastructure.configs.settings import embedding_settings, qdrant_settings
from src.infrastructure.db.repositories import (
    QdrantRegulatoryRepository,
    QdrantSuggestionRepository,
)

from src.domain.entities import (
    Chunk,
    RegulatoryChunkMetadata,
    ShamsiDate,
    SparseVector,
    SuggestionChunkMetadata,
)
from src.domain.enums import (
    AuthorityLevel,
    ChunkStatus,
    RegulatoryDocumentType,
    SuggestionChunkType,
    SuggestionStatus,
)
from src.domain.interfaces import (
    IRegulatoryVectorRepository,
    ISuggestionVectorRepository,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.db, pytest.mark.usefixtures("qdrant_test_database")]


@pytest.fixture
def auth_client() -> AsyncQdrantClient:
    return AsyncQdrantClient(
        host=qdrant_settings.QDRANT_HOST,
        port=qdrant_settings.QDRANT_PORT,
        grpc_port=qdrant_settings.QDRANT_GRPC_PORT,
        api_key=qdrant_settings.QDRANT_API_KEY,
        prefer_grpc=False,
        https=qdrant_settings.QDRANT_HTTPS,
        check_compatibility=False,
    )


@pytest.fixture
def suggestion_repo(auth_client: AsyncQdrantClient) -> QdrantSuggestionRepository:
    return QdrantSuggestionRepository(
        client=auth_client,
        collection_name=qdrant_settings.QDRANT_SUGGESTION_COLLECTION,
        dense_vector_name=qdrant_settings.QDRANT_DENSE_VECTOR_NAME,
        sparse_vector_name=qdrant_settings.QDRANT_SPARSE_VECTOR_NAME,
        default_dense_dim=embedding_settings.EMBEDDING_DIMENSION,
    )


@pytest.fixture
def regulatory_repo(auth_client: AsyncQdrantClient) -> QdrantRegulatoryRepository:
    return QdrantRegulatoryRepository(
        client=auth_client,
        collection_name=qdrant_settings.QDRANT_REGULATORY_COLLECTION,
        dense_vector_name=qdrant_settings.QDRANT_DENSE_VECTOR_NAME,
        sparse_vector_name=qdrant_settings.QDRANT_SPARSE_VECTOR_NAME,
        default_dense_dim=embedding_settings.EMBEDDING_DIMENSION,
    )


async def test_container_di_resolution() -> None:
    """Verify that repositories are properly resolved from the DI container."""
    container = Container()
    try:
        sugg_repo = container.suggestion_vector_repository()
        reg_repo = container.regulatory_vector_repository()

        assert isinstance(sugg_repo, ISuggestionVectorRepository)
        assert isinstance(sugg_repo, QdrantSuggestionRepository)
        assert isinstance(reg_repo, IRegulatoryVectorRepository)
        assert isinstance(reg_repo, QdrantRegulatoryRepository)
    finally:
        client = container.qdrant_client()
        await client.close()


async def test_provision_collections_live(
    suggestion_repo: QdrantSuggestionRepository,
    regulatory_repo: QdrantRegulatoryRepository,
    auth_client: AsyncQdrantClient,
) -> None:
    """Verify that calling provision_collection on live repositories ensures collections and indexes."""
    try:
        await suggestion_repo.provision_collection()
        await regulatory_repo.provision_collection()

        sugg_info = await auth_client.get_collection(suggestion_repo.collection_name)
        assert sugg_info.status == models.CollectionStatus.GREEN
        assert sugg_info.config.params.on_disk_payload is True
        assert "status" in sugg_info.payload_schema

        reg_info = await auth_client.get_collection(regulatory_repo.collection_name)
        assert reg_info.status == models.CollectionStatus.GREEN
        assert reg_info.config.params.on_disk_payload is True
        assert "authority_level" in reg_info.payload_schema
        assert (
            reg_info.payload_schema["authority_level"].data_type
            == models.PayloadSchemaType.KEYWORD
        )
    finally:
        await auth_client.close()


async def test_suggestion_repository_live_crud_and_hybrid_search(
    suggestion_repo: QdrantSuggestionRepository,
    auth_client: AsyncQdrantClient,
) -> None:
    """Upsert, search with hybrid RRF and Persian filter, then delete by parent ID."""
    parent_id = f"sugg-test-{uuid.uuid4()}"
    chunk_id = str(uuid.uuid4())
    dim = embedding_settings.EMBEDDING_DIMENSION

    chunk = Chunk[SuggestionChunkMetadata](
        chunk_id=chunk_id,
        parent_id=parent_id,
        content="راهکار هوشمندسازی پایش مصرف انرژی در شبکه توزیع",
        metadata=SuggestionChunkMetadata(
            chunk_type=SuggestionChunkType.SOLUTION,
            status=SuggestionStatus.APPROVED,
            context_title="شرکت توزیع نیروی برق تبریز",
            date=ShamsiDate("1404/02/10"),
        ),
        dense_vector=[0.05] * dim,
        sparse_vector=SparseVector(indices=[10, 20], values=[1.5, 2.5]),
        chunk_status=ChunkStatus.ACTIVE,
    )

    try:
        # 1. Upsert chunk
        await suggestion_repo.upsert_chunk(chunk)

        # 2. Hybrid search with filters
        results = await suggestion_repo.search_suggestions(
            dense_vector=[0.05] * dim,
            sparse_vector=SparseVector(indices=[10, 20], values=[1.5, 2.5]),
            limit=5,
            chunk_types=[SuggestionChunkType.SOLUTION],
            statuses=[SuggestionStatus.APPROVED],
            context_title="شرکت توزیع نیروی برق تبریز",
        )

        matching = [r for r in results if r.chunk.chunk_id == chunk_id]
        assert len(matching) == 1
        hit = matching[0]
        assert hit.parent_id == parent_id
        meta = hit.chunk.metadata
        assert isinstance(meta, SuggestionChunkMetadata)
        assert meta.chunk_type == SuggestionChunkType.SOLUTION
        assert meta.status == SuggestionStatus.APPROVED
        assert str(meta.date) == "1404/02/10"
        assert hit.score > 0.0

        # 3. Clean up by parent_id
        await suggestion_repo.delete_chunks_by_parent_id(parent_id)

        # Verify deletion
        results_after = await suggestion_repo.search_suggestions(
            dense_vector=[0.05] * dim,
            sparse_vector=SparseVector(indices=[10, 20], values=[1.5, 2.5]),
            limit=10,
        )
        assert not any(r.chunk.chunk_id == chunk_id for r in results_after)

    finally:
        await auth_client.close()


async def test_suggestion_staging_lifecycle_live(
    suggestion_repo: QdrantSuggestionRepository,
    auth_client: AsyncQdrantClient,
) -> None:
    """Verify zero-downtime staging promotion lifecycle (ACTIVE -> DEPRECATED, STAGING -> ACTIVE)."""
    parent_id = f"sugg-staging-{uuid.uuid4()}"
    active_chunk_id = str(uuid.uuid4())
    staging_chunk_id = str(uuid.uuid4())
    dim = embedding_settings.EMBEDDING_DIMENSION

    active_chunk = Chunk[SuggestionChunkMetadata](
        chunk_id=active_chunk_id,
        parent_id=parent_id,
        content="نسخه اولیه طرح کاهش تلفات شبکه",
        metadata=SuggestionChunkMetadata(
            chunk_type=SuggestionChunkType.PROBLEM,
            status=SuggestionStatus.EXECUTED,
        ),
        dense_vector=[0.03] * dim,
        sparse_vector=SparseVector(indices=[5], values=[1.0]),
        chunk_status=ChunkStatus.ACTIVE,
    )

    staging_chunk = Chunk[SuggestionChunkMetadata](
        chunk_id=staging_chunk_id,
        parent_id=parent_id,
        content="نسخه بازنگری شده و تفصیلی طرح کاهش تلفات",
        metadata=SuggestionChunkMetadata(
            chunk_type=SuggestionChunkType.SOLUTION,
            status=SuggestionStatus.APPROVED,
        ),
        dense_vector=[0.03] * dim,
        sparse_vector=SparseVector(indices=[5], values=[1.0]),
        chunk_status=ChunkStatus.STAGING,
    )

    try:
        await suggestion_repo.upsert_chunk(active_chunk)
        await suggestion_repo.upsert_chunk(staging_chunk)

        # Active search must find ONLY active chunk
        results = await suggestion_repo.search_suggestions(
            dense_vector=[0.03] * dim,
            sparse_vector=SparseVector(indices=[5], values=[1.0]),
            limit=10,
        )
        parent_results = [r for r in results if r.parent_id == parent_id]
        assert len(parent_results) == 1
        assert parent_results[0].chunk.chunk_id == active_chunk_id

        # Activate staging chunks
        await suggestion_repo.activate_staging_chunks(parent_id)

        # Search must now find the promoted staging chunk as ACTIVE
        results_after_promo = await suggestion_repo.search_suggestions(
            dense_vector=[0.03] * dim,
            sparse_vector=SparseVector(indices=[5], values=[1.0]),
            limit=10,
        )
        parent_results_after = [
            r for r in results_after_promo if r.parent_id == parent_id
        ]
        assert len(parent_results_after) == 1
        assert parent_results_after[0].chunk.chunk_id == staging_chunk_id

        # Clean up deprecated and remaining
        await suggestion_repo.delete_deprecated_chunks(parent_id)
        await suggestion_repo.delete_chunks_by_parent_id(parent_id)

    finally:
        await auth_client.close()


async def test_suggestion_batch_staging_lifecycle_and_batch_delete_live(
    suggestion_repo: QdrantSuggestionRepository,
    auth_client: AsyncQdrantClient,
) -> None:
    """Verify batch staging promotion and batch parent deletion on live Qdrant."""
    p1 = f"sugg-batch-1-{uuid.uuid4()}"
    p2 = f"sugg-batch-2-{uuid.uuid4()}"
    dim = embedding_settings.EMBEDDING_DIMENSION

    c1 = Chunk[SuggestionChunkMetadata](
        chunk_id=str(uuid.uuid4()),
        parent_id=p1,
        content="راهکار اول بهینه‌سازی دیسپاچینگ",
        metadata=SuggestionChunkMetadata(
            chunk_type=SuggestionChunkType.SOLUTION,
            status=SuggestionStatus.APPROVED,
        ),
        dense_vector=[0.05] * dim,
        sparse_vector=SparseVector(indices=[10], values=[2.0]),
        chunk_status=ChunkStatus.STAGING,
    )

    c2 = Chunk[SuggestionChunkMetadata](
        chunk_id=str(uuid.uuid4()),
        parent_id=p2,
        content="راهکار دوم بهینه‌سازی دیسپاچینگ",
        metadata=SuggestionChunkMetadata(
            chunk_type=SuggestionChunkType.SOLUTION,
            status=SuggestionStatus.APPROVED,
        ),
        dense_vector=[0.05] * dim,
        sparse_vector=SparseVector(indices=[10], values=[2.0]),
        chunk_status=ChunkStatus.STAGING,
    )

    try:
        # Upsert both chunks as STAGING
        await suggestion_repo.upsert_chunks_batch([c1, c2])

        # Step 1: Staging isolation - search should NOT find either chunk
        results_pre = await suggestion_repo.search_suggestions(
            dense_vector=[0.05] * dim,
            sparse_vector=SparseVector(indices=[10], values=[2.0]),
            limit=10,
        )
        found_pre = [r for r in results_pre if r.parent_id in (p1, p2)]
        assert len(found_pre) == 0, "STAGING chunks must be invisible to search"

        # Step 2: Batch promote STAGING -> ACTIVE
        await suggestion_repo.activate_staging_chunks_batch([p1, p2])

        # Search should now find both chunks
        results_post = await suggestion_repo.search_suggestions(
            dense_vector=[0.05] * dim,
            sparse_vector=SparseVector(indices=[10], values=[2.0]),
            limit=10,
        )
        found_post = [r for r in results_post if r.parent_id in (p1, p2)]
        assert len(found_post) == 2, "Promoted chunks must now be visible in search"

        # Step 3: Batch delete chunks by parent IDs
        await suggestion_repo.delete_chunks_by_parent_ids([p1, p2])

        results_deleted = await suggestion_repo.search_suggestions(
            dense_vector=[0.05] * dim,
            sparse_vector=SparseVector(indices=[10], values=[2.0]),
            limit=10,
        )
        found_deleted = [r for r in results_deleted if r.parent_id in (p1, p2)]
        assert len(found_deleted) == 0, "Deleted chunks must no longer exist in search"

    finally:
        await auth_client.close()


async def test_regulatory_repository_live_crud_filters_and_exclusion(
    regulatory_repo: QdrantRegulatoryRepository,
    auth_client: AsyncQdrantClient,
) -> None:
    """Verify batch upsert, authority filtering, Hop-1 ID exclusion, and raw table parent_content."""
    parent_id = f"reg-test-{uuid.uuid4()}"
    chunk1_id = str(uuid.uuid4())
    chunk2_id = str(uuid.uuid4())
    dim = embedding_settings.EMBEDDING_DIMENSION

    table_markdown = "| صنعت | دیماند (مگاوات) |\n| فولاد | ۱۰۰ |\n| پتروشیمی | ۵۰ |"

    chunk1 = Chunk[RegulatoryChunkMetadata](
        chunk_id=chunk1_id,
        parent_id=parent_id,
        content="ماده ۲۵: کلیه واحدهای صنعتی فولادی موظف به رعایت سقف مصرف در ساعات پیک می‌باشند.",
        parent_content=table_markdown,
        metadata=RegulatoryChunkMetadata(
            document_title="قانون مدیریت مصرف بار صنایع سنگین",
            document_type=RegulatoryDocumentType.STATUTE,
            is_binding=True,
            authority_level=AuthorityLevel.BINDING,
        ),
        dense_vector=[0.08] * dim,
        sparse_vector=SparseVector(indices=[15], values=[3.0]),
        chunk_status=ChunkStatus.ACTIVE,
    )

    chunk2 = Chunk[RegulatoryChunkMetadata](
        chunk_id=chunk2_id,
        parent_id=parent_id,
        content="راهنمای پیشنهادی مدیریت بهینه بار تجهیزات اداری و روشنایی",
        metadata=RegulatoryChunkMetadata(
            document_title="شیوه‌نامه بهینه‌سازی بار اداری",
            document_type=RegulatoryDocumentType.GUIDELINE,
            is_binding=False,
            authority_level=AuthorityLevel.GUIDANCE,
        ),
        dense_vector=[0.08] * dim,
        sparse_vector=SparseVector(indices=[15], values=[3.0]),
        chunk_status=ChunkStatus.ACTIVE,
    )

    try:
        # Batch upsert
        await regulatory_repo.upsert_chunks_batch([chunk1, chunk2])

        # 1. Filter test: only BINDING
        binding_results = await regulatory_repo.search_regulatory_documents(
            dense_vector=[0.08] * dim,
            sparse_vector=SparseVector(indices=[15], values=[3.0]),
            limit=5,
            is_binding=True,
            authority_level=AuthorityLevel.BINDING,
        )
        binding_matches = [r for r in binding_results if r.parent_id == parent_id]
        assert len(binding_matches) == 1
        hit = binding_matches[0]
        assert hit.chunk.chunk_id == chunk1_id
        assert hit.chunk.parent_content == table_markdown
        reg_meta = hit.chunk.metadata
        assert isinstance(reg_meta, RegulatoryChunkMetadata)
        assert reg_meta.document_type == RegulatoryDocumentType.STATUTE

        # 2. Hop-1 exclusion test: exclude chunk1_id
        excluded_results = await regulatory_repo.search_regulatory_documents(
            dense_vector=[0.08] * dim,
            sparse_vector=SparseVector(indices=[15], values=[3.0]),
            limit=10,
            exclude_chunk_ids=[chunk1_id],
        )
        excluded_parent_matches = [
            r for r in excluded_results if r.parent_id == parent_id
        ]
        assert len(excluded_parent_matches) == 1
        assert excluded_parent_matches[0].chunk.chunk_id == chunk2_id

        # Clean up
        await regulatory_repo.delete_chunks_by_parent_id(parent_id)

    finally:
        await auth_client.close()
