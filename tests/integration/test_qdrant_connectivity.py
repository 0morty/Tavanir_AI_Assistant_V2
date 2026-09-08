from __future__ import annotations

import uuid

import pytest
from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from src.infrastructure.configs.settings import embedding_settings, qdrant_settings

pytestmark = pytest.mark.asyncio


@pytest.fixture
def auth_client() -> AsyncQdrantClient:
    """Returns an authenticated AsyncQdrantClient matching settings."""
    return AsyncQdrantClient(
        host=qdrant_settings.QDRANT_HOST,
        port=qdrant_settings.QDRANT_PORT,
        grpc_port=qdrant_settings.QDRANT_GRPC_PORT,
        api_key=qdrant_settings.QDRANT_API_KEY,
        prefer_grpc=False,
        https=qdrant_settings.QDRANT_HTTPS,
    )


async def test_qdrant_connection_with_api_key(auth_client: AsyncQdrantClient) -> None:
    """Verify that an authenticated client successfully queries Qdrant telemetry."""
    try:
        collections = await auth_client.get_collections()
        assert collections is not None
        collection_names = [c.name for c in collections.collections]
        assert qdrant_settings.QDRANT_SUGGESTION_COLLECTION in collection_names
        assert qdrant_settings.QDRANT_REGULATORY_COLLECTION in collection_names
    finally:
        await auth_client.close()


async def test_qdrant_authentication_enforcement() -> None:
    """Verify that unauthenticated or invalid-key requests are rejected (401/403)."""
    unauth_client = AsyncQdrantClient(
        host=qdrant_settings.QDRANT_HOST,
        port=qdrant_settings.QDRANT_PORT,
        api_key=None,
        prefer_grpc=False,
        https=qdrant_settings.QDRANT_HTTPS,
    )
    try:
        with pytest.raises((UnexpectedResponse, ResponseHandlingException)) as exc_info:
            await unauth_client.get_collections()
        assert any(
            status in str(exc_info.value)
            for status in ["401", "403", "Forbidden", "Unauthorized"]
        )
    finally:
        await unauth_client.close()

    wrong_key_client = AsyncQdrantClient(
        host=qdrant_settings.QDRANT_HOST,
        port=qdrant_settings.QDRANT_PORT,
        api_key="invalid_malformed_key_xyz",
        prefer_grpc=False,
        https=qdrant_settings.QDRANT_HTTPS,
    )
    try:
        with pytest.raises((UnexpectedResponse, ResponseHandlingException)) as exc_info:
            await wrong_key_client.get_collections()
        assert any(
            status in str(exc_info.value)
            for status in ["401", "403", "Forbidden", "Unauthorized"]
        )
    finally:
        await wrong_key_client.close()


async def test_qdrant_collections_configuration(auth_client: AsyncQdrantClient) -> None:
    """Verify that collections have on-disk 768-dim dense and IDF sparse vectors."""
    try:
        for coll_name in [
            qdrant_settings.QDRANT_SUGGESTION_COLLECTION,
            qdrant_settings.QDRANT_REGULATORY_COLLECTION,
        ]:
            info = await auth_client.get_collection(collection_name=coll_name)
            assert info.status == models.CollectionStatus.GREEN

            # Verify Dense Vector
            vectors_cfg = info.config.params.vectors
            assert isinstance(vectors_cfg, dict)
            assert qdrant_settings.QDRANT_DENSE_VECTOR_NAME in vectors_cfg
            dense_params = vectors_cfg[qdrant_settings.QDRANT_DENSE_VECTOR_NAME]
            assert dense_params.size == embedding_settings.EMBEDDING_DIMENSION
            assert dense_params.distance == models.Distance.COSINE
            assert dense_params.on_disk is True

            # Verify Sparse Vector
            sparse_cfg = info.config.params.sparse_vectors
            assert isinstance(sparse_cfg, dict)
            assert qdrant_settings.QDRANT_SPARSE_VECTOR_NAME in sparse_cfg
            sparse_params = sparse_cfg[qdrant_settings.QDRANT_SPARSE_VECTOR_NAME]
            assert sparse_params.modifier == models.Modifier.IDF
    finally:
        await auth_client.close()


async def test_qdrant_payload_indexes(auth_client: AsyncQdrantClient) -> None:
    """Verify that expected payload indexes exist on both collections."""
    try:
        # 1. Suggestions Collection Indexes
        sugg_info = await auth_client.get_collection(
            qdrant_settings.QDRANT_SUGGESTION_COLLECTION
        )
        sugg_schema = sugg_info.payload_schema
        for expected_field in [
            "parent_id",
            "chunk_status",
            "chunk_type",
            "status",
        ]:
            assert expected_field in sugg_schema, (
                f"Missing index for {expected_field} in suggestions"
            )

        # 2. Regulatory Collection Indexes
        reg_info = await auth_client.get_collection(
            qdrant_settings.QDRANT_REGULATORY_COLLECTION
        )
        reg_schema = reg_info.payload_schema
        for expected_field in [
            "parent_id",
            "chunk_status",
            "document_type",
            "authority_level",
            "is_binding",
        ]:
            assert expected_field in reg_schema, (
                f"Missing index for {expected_field} in regulatory knowledge"
            )
    finally:
        await auth_client.close()


async def test_qdrant_point_crud_roundtrip(auth_client: AsyncQdrantClient) -> None:
    """Perform temporary point upsert, filter query, and deletion under authentication."""
    test_chunk_id = str(uuid.uuid4())
    test_parent_id = "test-parent-001"
    coll_name = qdrant_settings.QDRANT_SUGGESTION_COLLECTION

    try:
        point = models.PointStruct(
            id=test_chunk_id,
            vector={
                qdrant_settings.QDRANT_DENSE_VECTOR_NAME: [0.01]
                * embedding_settings.EMBEDDING_DIMENSION,
                qdrant_settings.QDRANT_SPARSE_VECTOR_NAME: models.SparseVector(
                    indices=[10, 25, 42],
                    values=[0.5, 1.2, 0.8],
                ),
            },
            payload={
                "parent_id": test_parent_id,
                "chunk_status": "ACTIVE",
                "chunk_type": "TITLE",
                "status": "اجرا شده",
                "content": "آزمایش سامانه مدیریت هوشمند توانیر",
            },
        )

        # Upsert point
        await auth_client.upsert(collection_name=coll_name, points=[point])

        # Retrieve and verify
        retrieved = await auth_client.retrieve(
            collection_name=coll_name, ids=[test_chunk_id], with_payload=True
        )
        assert len(retrieved) == 1
        assert retrieved[0].payload is not None
        assert retrieved[0].payload["parent_id"] == test_parent_id
        assert retrieved[0].payload["status"] == "اجرا شده"

        # Filter query test
        search_res = await auth_client.scroll(
            collection_name=coll_name,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="parent_id",
                        match=models.MatchValue(value=test_parent_id),
                    )
                ]
            ),
            limit=1,
        )
        points, _ = search_res
        assert len(points) == 1
        assert points[0].id == test_chunk_id

    finally:
        # Clean up test point
        await auth_client.delete(
            collection_name=coll_name,
            points_selector=models.PointIdsList(points=[test_chunk_id]),
        )
        await auth_client.close()
