from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse
from src.infrastructure.db.repositories.qdrant.regulatory_repository import (
    QdrantRegulatoryRepository,
)
from src.infrastructure.db.repositories.qdrant.suggestion_repository import (
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
from src.domain.exceptions import (
    VectorCollectionProvisioningError,
    VectorSearchError,
    VectorStorageError,
)

pytestmark = pytest.mark.asyncio


# region Fixtures
@pytest.fixture
def mock_qdrant_client() -> AsyncMock:
    client = AsyncMock(spec=AsyncQdrantClient)
    client.collection_exists.return_value = True
    client.create_collection.return_value = True
    client.create_payload_index.return_value = True
    client.upsert.return_value = True
    client.delete.return_value = True
    client.set_payload.return_value = True
    return client


@pytest.fixture
def suggestion_repo(mock_qdrant_client: AsyncMock) -> QdrantSuggestionRepository:
    return QdrantSuggestionRepository(
        client=mock_qdrant_client,
        collection_name="test_suggestion_v1",
        dense_vector_name="dense",
        sparse_vector_name="sparse",
        default_dense_dim=768,
        batch_size=2,
        max_retries=3,
        retry_base_delay=0.01,
        retry_max_delay=0.05,
    )


@pytest.fixture
def regulatory_repo(mock_qdrant_client: AsyncMock) -> QdrantRegulatoryRepository:
    return QdrantRegulatoryRepository(
        client=mock_qdrant_client,
        collection_name="test_regulatory_v1",
        dense_vector_name="dense",
        sparse_vector_name="sparse",
        default_dense_dim=768,
        batch_size=2,
        max_retries=3,
        retry_base_delay=0.01,
        retry_max_delay=0.05,
    )


@pytest.fixture
def sample_suggestion_chunk() -> Chunk[SuggestionChunkMetadata]:
    return Chunk[SuggestionChunkMetadata](
        chunk_id="sugg-chunk-001",
        parent_id="sugg-parent-001",
        content="راهکار کاهش مصرف برق در ساعات اوج بار",
        metadata=SuggestionChunkMetadata(
            chunk_type=SuggestionChunkType.SOLUTION,
            status=SuggestionStatus.APPROVED,
            context_title="معاونت انتقال و تجارت خارجی",
            date=ShamsiDate("1404/05/15"),
        ),
        dense_vector=[0.1] * 768,
        sparse_vector=SparseVector(indices=[1, 5], values=[0.8, 1.2]),
        chunk_status=ChunkStatus.ACTIVE,
    )


@pytest.fixture
def sample_regulatory_chunk() -> Chunk[RegulatoryChunkMetadata]:
    return Chunk[RegulatoryChunkMetadata](
        chunk_id="reg-chunk-001",
        parent_id="reg-parent-001",
        content="ماده ۴: کلیه مشترکین صنعتی موظف به رعایت سقف مصرف هستند.",
        metadata=RegulatoryChunkMetadata(
            document_title="دستورالعمل مدیریت مصرف صنایع",
            document_type=RegulatoryDocumentType.DIRECTIVE,
            is_binding=True,
            authority_level=AuthorityLevel.BINDING,
        ),
        parent_content="| صنعت | سقف مگاوات |\n| فولاد | ۵۰ |",
        dense_vector=[0.2] * 768,
        sparse_vector=SparseVector(indices=[3, 9], values=[0.5, 2.1]),
        chunk_status=ChunkStatus.ACTIVE,
    )


# endregion


# region Base / Lifecycle Tests
async def test_provision_collection_when_collection_not_exists(
    suggestion_repo: QdrantSuggestionRepository, mock_qdrant_client: AsyncMock
) -> None:
    mock_qdrant_client.collection_exists.return_value = False
    await suggestion_repo.provision_collection()

    mock_qdrant_client.create_collection.assert_awaited_once()
    assert (
        mock_qdrant_client.create_collection.call_args.kwargs["on_disk_payload"] is True
    )
    assert mock_qdrant_client.create_payload_index.await_count == 4


async def test_provision_collection_raises_domain_error_on_fatal_failure(
    suggestion_repo: QdrantSuggestionRepository, mock_qdrant_client: AsyncMock
) -> None:
    mock_qdrant_client.collection_exists.side_effect = RuntimeError("Network partition")
    with pytest.raises(VectorCollectionProvisioningError):
        await suggestion_repo.provision_collection()


async def test_upsert_chunk_success(
    suggestion_repo: QdrantSuggestionRepository,
    mock_qdrant_client: AsyncMock,
    sample_suggestion_chunk: Chunk[SuggestionChunkMetadata],
) -> None:
    await suggestion_repo.upsert_chunk(sample_suggestion_chunk)

    mock_qdrant_client.upsert.assert_awaited_once()
    call_kwargs = mock_qdrant_client.upsert.call_args.kwargs
    assert call_kwargs["collection_name"] == "test_suggestion_v1"
    points = call_kwargs["points"]
    assert len(points) == 1
    point = points[0]
    assert point.id == "sugg-chunk-001"
    assert point.vector["dense"] == [0.1] * 768
    assert point.vector["sparse"].indices == [1, 5]
    assert point.payload["status"] == "مصوب"
    assert point.payload["chunk_type"] == "solution"
    assert point.payload["date"] == "1404/05/15"


async def test_upsert_chunk_wraps_error(
    suggestion_repo: QdrantSuggestionRepository,
    mock_qdrant_client: AsyncMock,
    sample_suggestion_chunk: Chunk[SuggestionChunkMetadata],
) -> None:
    mock_qdrant_client.upsert.side_effect = RuntimeError("Disk full")
    with pytest.raises(VectorStorageError) as exc_info:
        await suggestion_repo.upsert_chunk(sample_suggestion_chunk)
    assert "Failed to upsert chunk" in str(exc_info.value)


async def test_upsert_chunks_batch_slices_correctly(
    suggestion_repo: QdrantSuggestionRepository,
    mock_qdrant_client: AsyncMock,
    sample_suggestion_chunk: Chunk[SuggestionChunkMetadata],
) -> None:
    # 5 chunks with batch_size=2 -> 3 upsert calls (2, 2, 1)
    chunks = [sample_suggestion_chunk for _ in range(5)]
    await suggestion_repo.upsert_chunks_batch(chunks)

    assert mock_qdrant_client.upsert.await_count == 3


async def test_upsert_chunks_batch_retries_transient_error_and_succeeds(
    suggestion_repo: QdrantSuggestionRepository,
    mock_qdrant_client: AsyncMock,
    sample_suggestion_chunk: Chunk[SuggestionChunkMetadata],
) -> None:
    # Attempt 1 raises ConnectError (transient), attempt 2 succeeds
    mock_qdrant_client.upsert.side_effect = [
        httpx.ConnectError("Connection refused by Qdrant"),
        True,
    ]
    await suggestion_repo.upsert_chunks_batch([sample_suggestion_chunk])

    assert mock_qdrant_client.upsert.await_count == 2


async def test_upsert_chunks_batch_fails_fast_on_poison_pill(
    suggestion_repo: QdrantSuggestionRepository,
    mock_qdrant_client: AsyncMock,
    sample_suggestion_chunk: Chunk[SuggestionChunkMetadata],
) -> None:
    # HTTP 400 is a poison-pill error; must fail fast without consuming retries
    mock_qdrant_client.upsert.side_effect = UnexpectedResponse(
        status_code=400,
        reason_phrase="Bad Request",
        content=b"Invalid vector dimension",
        headers=httpx.Headers(),
    )
    with pytest.raises(VectorStorageError):
        await suggestion_repo.upsert_chunks_batch([sample_suggestion_chunk])

    # Exactly 1 attempt made (0 extra retries)
    assert mock_qdrant_client.upsert.await_count == 1


async def test_upsert_chunks_batch_exhausts_retries_and_raises_storage_error(
    suggestion_repo: QdrantSuggestionRepository,
    mock_qdrant_client: AsyncMock,
    sample_suggestion_chunk: Chunk[SuggestionChunkMetadata],
) -> None:
    # Continuously raise TimeoutException
    mock_qdrant_client.upsert.side_effect = httpx.TimeoutException("Read timeout")
    with pytest.raises(VectorStorageError) as exc_info:
        await suggestion_repo.upsert_chunks_batch([sample_suggestion_chunk])

    assert "Failed to upsert batch" in str(exc_info.value)
    # Exactly max_retries attempts made
    assert mock_qdrant_client.upsert.await_count == 3


async def test_delete_chunks_by_parent_id(
    suggestion_repo: QdrantSuggestionRepository, mock_qdrant_client: AsyncMock
) -> None:
    await suggestion_repo.delete_chunks_by_parent_id("parent-xyz")

    mock_qdrant_client.delete.assert_awaited_once()
    filter_selector = mock_qdrant_client.delete.call_args.kwargs["points_selector"]
    cond = filter_selector.filter.must[0]
    assert cond.key == "parent_id"
    assert cond.match.value == "parent-xyz"


async def test_delete_chunks_by_parent_ids(
    suggestion_repo: QdrantSuggestionRepository, mock_qdrant_client: AsyncMock
) -> None:
    await suggestion_repo.delete_chunks_by_parent_ids(["parent-1", "parent-2"])

    mock_qdrant_client.delete.assert_awaited_once()
    filter_selector = mock_qdrant_client.delete.call_args.kwargs["points_selector"]
    cond = filter_selector.filter.must[0]
    assert cond.key == "parent_id"
    assert cond.match.any == ["parent-1", "parent-2"]


async def test_activate_staging_chunks_batch(
    suggestion_repo: QdrantSuggestionRepository, mock_qdrant_client: AsyncMock
) -> None:
    await suggestion_repo.activate_staging_chunks_batch(["parent-1", "parent-2"])

    assert mock_qdrant_client.set_payload.await_count == 2

    # Step 1: Demote ACTIVE to DEPRECATED
    first_call = mock_qdrant_client.set_payload.call_args_list[0].kwargs
    assert first_call["payload"]["chunk_status"] == "deprecated"
    assert first_call["points"].must[0].key == "parent_id"
    assert first_call["points"].must[0].match.any == ["parent-1", "parent-2"]
    assert first_call["points"].must[1].key == "chunk_status"
    assert first_call["points"].must[1].match.value == "active"

    # Step 2: Promote STAGING to ACTIVE
    second_call = mock_qdrant_client.set_payload.call_args_list[1].kwargs
    assert second_call["payload"]["chunk_status"] == "active"
    assert second_call["points"].must[0].key == "parent_id"
    assert second_call["points"].must[0].match.any == ["parent-1", "parent-2"]
    assert second_call["points"].must[1].key == "chunk_status"
    assert second_call["points"].must[1].match.value == "staging"


async def test_delete_staging_chunks(
    suggestion_repo: QdrantSuggestionRepository, mock_qdrant_client: AsyncMock
) -> None:
    await suggestion_repo.delete_staging_chunks("parent-xyz")

    mock_qdrant_client.delete.assert_awaited_once()
    filter_selector = mock_qdrant_client.delete.call_args.kwargs["points_selector"]
    keys = {cond.key: cond.match.value for cond in filter_selector.filter.must}
    assert keys["parent_id"] == "parent-xyz"
    assert keys["chunk_status"] == "staging"


async def test_activate_staging_chunks_two_step_promotion(
    suggestion_repo: QdrantSuggestionRepository, mock_qdrant_client: AsyncMock
) -> None:
    await suggestion_repo.activate_staging_chunks("parent-xyz")

    assert mock_qdrant_client.set_payload.await_count == 2

    # Step 1: Demote ACTIVE to DEPRECATED
    first_call = mock_qdrant_client.set_payload.call_args_list[0].kwargs
    assert first_call["payload"]["chunk_status"] == "deprecated"
    first_filter_keys = {
        cond.key: cond.match.value for cond in first_call["points"].must
    }
    assert first_filter_keys["parent_id"] == "parent-xyz"
    assert first_filter_keys["chunk_status"] == "active"

    # Step 2: Promote STAGING to ACTIVE
    second_call = mock_qdrant_client.set_payload.call_args_list[1].kwargs
    assert second_call["payload"]["chunk_status"] == "active"
    second_filter_keys = {
        cond.key: cond.match.value for cond in second_call["points"].must
    }
    assert second_filter_keys["parent_id"] == "parent-xyz"
    assert second_filter_keys["chunk_status"] == "staging"


async def test_delete_deprecated_chunks(
    suggestion_repo: QdrantSuggestionRepository, mock_qdrant_client: AsyncMock
) -> None:
    await suggestion_repo.delete_deprecated_chunks("parent-xyz")

    mock_qdrant_client.delete.assert_awaited_once()
    filter_selector = mock_qdrant_client.delete.call_args.kwargs["points_selector"]
    keys = {cond.key: cond.match.value for cond in filter_selector.filter.must}
    assert keys["parent_id"] == "parent-xyz"
    assert keys["chunk_status"] == "deprecated"


# endregion


# region Suggestion Repository Search Tests
async def test_search_suggestions_filter_construction_and_result_mapping(
    suggestion_repo: QdrantSuggestionRepository, mock_qdrant_client: AsyncMock
) -> None:
    # Setup mock query response with a ScoredPoint
    scored_point = models.ScoredPoint(
        id="sugg-chunk-001",
        version=1,
        score=0.032,
        payload={
            "chunk_id": "sugg-chunk-001",
            "parent_id": "sugg-parent-001",
            "content": "راهکار پیشنهادی بهینه‌سازی بار",
            "chunk_status": "active",
            "chunk_type": "solution",
            "status": "مصوب",
            "context_title": "توزیع برق شیراز",
            "date": "1403/10/20",
        },
    )
    mock_qdrant_client.query_points.return_value = MagicMock(points=[scored_point])

    results = await suggestion_repo.search_suggestions(
        dense_vector=[0.05] * 768,
        sparse_vector=SparseVector(indices=[10], values=[1.5]),
        limit=5,
        chunk_types=[SuggestionChunkType.SOLUTION, SuggestionChunkType.PROBLEM],
        statuses=[SuggestionStatus.APPROVED],
        context_title="توزیع برق شیراز",
        score_threshold=0.01,
    )

    # Verify query_points invocation
    mock_qdrant_client.query_points.assert_awaited_once()
    call_kwargs = mock_qdrant_client.query_points.call_args.kwargs
    assert call_kwargs["collection_name"] == "test_suggestion_v1"
    assert call_kwargs["limit"] == 5
    assert call_kwargs["score_threshold"] == 0.01
    assert isinstance(call_kwargs["query"], models.FusionQuery)
    assert call_kwargs["query"].fusion == models.Fusion.RRF

    # Verify prefetch filters
    prefetch = call_kwargs["prefetch"]
    assert len(prefetch) == 2
    dense_prefetch, sparse_prefetch = prefetch[0], prefetch[1]
    assert dense_prefetch.limit == 10
    assert sparse_prefetch.limit == 10

    q_filter = dense_prefetch.filter
    field_conds = {c.key: c.match for c in q_filter.must}
    assert field_conds["chunk_status"].value == "active"
    assert field_conds["chunk_type"].any == ["solution", "problem"]
    assert field_conds["status"].any == ["مصوب"]
    assert field_conds["context_title"].value == "توزیع برق شیراز"

    # Verify hydrated domain model
    assert len(results) == 1
    hit = results[0]
    assert hit.score == 0.032
    assert hit.parent_id == "sugg-parent-001"
    assert hit.chunk.chunk_id == "sugg-chunk-001"
    assert hit.chunk.content == "راهکار پیشنهادی بهینه‌سازی بار"
    assert hit.chunk.metadata.chunk_type == SuggestionChunkType.SOLUTION
    assert hit.chunk.metadata.status == SuggestionStatus.APPROVED
    assert str(hit.chunk.metadata.date) == "1403/10/20"


async def test_search_suggestions_wraps_error(
    suggestion_repo: QdrantSuggestionRepository, mock_qdrant_client: AsyncMock
) -> None:
    mock_qdrant_client.query_points.side_effect = RuntimeError(
        "Timeout communicating with Qdrant"
    )
    with pytest.raises(VectorSearchError):
        await suggestion_repo.search_suggestions(
            dense_vector=[0.01] * 768,
            sparse_vector=SparseVector(indices=[1], values=[1.0]),
        )


# endregion


# region Regulatory Repository Search Tests
async def test_search_regulatory_documents_filters_exclusion_and_parent_content(
    regulatory_repo: QdrantRegulatoryRepository, mock_qdrant_client: AsyncMock
) -> None:
    scored_point = models.ScoredPoint(
        id="reg-chunk-001",
        version=1,
        score=0.028,
        payload={
            "chunk_id": "reg-chunk-001",
            "parent_id": "reg-parent-001",
            "content": "ماده ۱۰: تعرفه‌های جدید مصرف صنعتی برق",
            "parent_content": "| پله مصرف | تعرفه ریال |\n| ۰ تا ۱۰۰ | ۱۵۰۰ |",
            "chunk_status": "active",
            "document_title": "آیین‌نامه تعرفه‌های سال ۱۴۰۴",
            "document_type": "regulation",
            "is_binding": True,
            "authority_level": "binding",
        },
    )
    mock_qdrant_client.query_points.return_value = MagicMock(points=[scored_point])

    results = await regulatory_repo.search_regulatory_documents(
        dense_vector=[0.02] * 768,
        sparse_vector=SparseVector(indices=[20], values=[2.0]),
        limit=5,
        document_types=[
            RegulatoryDocumentType.REGULATION,
            RegulatoryDocumentType.STATUTE,
        ],
        is_binding=True,
        authority_level=AuthorityLevel.BINDING,
        exclude_chunk_ids=["exclude-chunk-a", "exclude-chunk-b"],
    )

    mock_qdrant_client.query_points.assert_awaited_once()
    call_kwargs = mock_qdrant_client.query_points.call_args.kwargs
    prefetch = call_kwargs["prefetch"]
    q_filter = prefetch[0].filter

    must_conds = {c.key: c.match for c in q_filter.must}
    assert must_conds["chunk_status"].value == "active"
    assert must_conds["document_type"].any == ["regulation", "statute"]
    assert must_conds["is_binding"].value is True
    assert must_conds["authority_level"].value == "binding"

    # Verify Hop-1 exclusion in must_not
    assert q_filter.must_not is not None
    assert len(q_filter.must_not) == 1
    assert q_filter.must_not[0].has_id == ["exclude-chunk-a", "exclude-chunk-b"]

    # Verify domain model and parent_content preservation
    assert len(results) == 1
    hit = results[0]
    assert hit.score == 0.028
    assert hit.parent_id == "reg-parent-001"
    assert hit.chunk.parent_content == "| پله مصرف | تعرفه ریال |\n| ۰ تا ۱۰۰ | ۱۵۰۰ |"
    assert hit.chunk.metadata.document_type == RegulatoryDocumentType.REGULATION
    assert hit.chunk.metadata.authority_level == AuthorityLevel.BINDING
    assert hit.chunk.metadata.is_binding is True


async def test_search_regulatory_documents_wraps_error(
    regulatory_repo: QdrantRegulatoryRepository, mock_qdrant_client: AsyncMock
) -> None:
    mock_qdrant_client.query_points.side_effect = RuntimeError("GRPC stream broken")
    with pytest.raises(VectorSearchError):
        await regulatory_repo.search_regulatory_documents(
            dense_vector=[0.01] * 768,
            sparse_vector=SparseVector(indices=[1], values=[1.0]),
        )


# endregion
