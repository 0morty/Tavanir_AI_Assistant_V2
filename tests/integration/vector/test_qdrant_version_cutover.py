from __future__ import annotations

import uuid

import pytest
from qdrant_client import AsyncQdrantClient
from src.infrastructure.configs.settings import embedding_settings, qdrant_settings
from src.infrastructure.db.repositories import QdrantSuggestionRepository

from src.domain.entities import Chunk, SparseVector, SuggestionChunkMetadata
from src.domain.enums import ChunkStatus, SuggestionChunkType, SuggestionStatus

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.db,
    pytest.mark.usefixtures("qdrant_test_database"),
]


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


def _make_chunk(
    chunk_id: str,
    parent_id: str,
    version: int,
    status: ChunkStatus,
) -> Chunk[SuggestionChunkMetadata]:
    dim = embedding_settings.EMBEDDING_DIMENSION
    return Chunk(
        chunk_id=chunk_id,
        parent_id=parent_id,
        content=f"متن تستی نسخه {version}",
        dense_vector=[0.1] * dim,
        sparse_vector=SparseVector(indices=[1, 2], values=[0.5, 0.8]),
        metadata=SuggestionChunkMetadata(
            chunk_type=SuggestionChunkType.TITLE,
            status=SuggestionStatus.APPROVED,
        ),
        chunk_status=status,
        version=version,
    )


async def test_qdrant_version_cutover_and_obsolete_purge(
    suggestion_repo: QdrantSuggestionRepository, auth_client: AsyncQdrantClient
):
    """
    Validates atomic version cutover in real Qdrant test instance:
    1. Seed version 1 as ACTIVE and version 2 as STAGING.
    2. activate_version_chunks(target_version=2) promotes v=2 to ACTIVE.
    3. Idempotent repeat of activate_version_chunks leaves v=2 ACTIVE (F-01 fix).
    4. delete_obsolete_version_chunks(max_version_exclusive=2) purges v=1 while preserving v=2.
    """
    parent_id = f"parent-cutover-{uuid.uuid4().hex[:8]}"
    c1_id = str(uuid.uuid4())
    c2_id = str(uuid.uuid4())

    chunk_v1 = _make_chunk(c1_id, parent_id, version=1, status=ChunkStatus.ACTIVE)
    chunk_v2 = _make_chunk(c2_id, parent_id, version=2, status=ChunkStatus.STAGING)

    try:
        # 1. Upsert both chunks
        await suggestion_repo.upsert_chunks_batch([chunk_v1, chunk_v2])

        # Verify initial states
        pts = await auth_client.retrieve(
            collection_name=qdrant_settings.QDRANT_SUGGESTION_COLLECTION,
            ids=[c1_id, c2_id],
            with_payload=True,
        )
        payload_map = {str(p.id): p.payload for p in pts}
        assert payload_map[c1_id]["chunk_status"] == ChunkStatus.ACTIVE.value
        assert payload_map[c1_id]["version"] == 1
        assert payload_map[c2_id]["chunk_status"] == ChunkStatus.STAGING.value
        assert payload_map[c2_id]["version"] == 2

        # 2. Cutover: Promote version 2 to ACTIVE
        await suggestion_repo.activate_version_chunks(
            parent_id=parent_id, target_version=2
        )

        pts_after_cutover = await auth_client.retrieve(
            collection_name=qdrant_settings.QDRANT_SUGGESTION_COLLECTION,
            ids=[c2_id],
            with_payload=True,
        )
        assert pts_after_cutover[0].payload["chunk_status"] == ChunkStatus.ACTIVE.value

        # 3. Idempotency test (F-01): Cutover retry must NEVER demote v=2
        await suggestion_repo.activate_version_chunks(
            parent_id=parent_id, target_version=2
        )
        pts_retry = await auth_client.retrieve(
            collection_name=qdrant_settings.QDRANT_SUGGESTION_COLLECTION,
            ids=[c2_id],
            with_payload=True,
        )
        assert pts_retry[0].payload["chunk_status"] == ChunkStatus.ACTIVE.value

        # 4. Purge obsolete chunks (< 2)
        await suggestion_repo.delete_obsolete_version_chunks(
            parent_id=parent_id, max_version_exclusive=2
        )

        # v1 should be deleted, v2 must survive
        pts_final = await auth_client.retrieve(
            collection_name=qdrant_settings.QDRANT_SUGGESTION_COLLECTION,
            ids=[c1_id, c2_id],
            with_payload=True,
        )
        remaining_ids = {str(p.id) for p in pts_final}
        assert c1_id not in remaining_ids
        assert c2_id in remaining_ids

    finally:
        await suggestion_repo.delete_chunks_by_parent_id(parent_id)
