"""Integration tests for the test database seeder and golden benchmark scenarios.

Verifies:
1. End-to-end population of PostgreSQL and Qdrant with cross-store referential integrity.
2. Clean wipe-before-seed semantics removing stale/dummy data while strictly preserving environment guards.
3. Accurate retrieval for golden benchmark scenarios via Qdrant hybrid search.
"""

from __future__ import annotations

import uuid

import pytest
from qdrant_client import AsyncQdrantClient, models
from sqlalchemy import text

from src.domain.enums import SuggestionChunkType, SuggestionStatus
from src.infrastructure.configs import settings
from src.infrastructure.db import create_db_engine
from src.infrastructure.db.repositories.qdrant.regulatory_repository import (
    QdrantRegulatoryRepository,
)
from src.infrastructure.db.repositories.qdrant.suggestion_repository import (
    QdrantSuggestionRepository,
)
from tests.database_safety import verify_postgres_connection, verify_qdrant_client
from tests.support.seeding import (
    BENCHMARK_QUERIES,
    DeterministicVectorGenerator,
    TestDatabaseSeeder,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.db,
    pytest.mark.usefixtures("postgres_test_database", "qdrant_test_database"),
]


async def test_seeder_populates_both_stores_and_maintains_referential_integrity(
    test_database_config,
) -> None:
    """Verifies that the seeder populates both stores with exact counts and referential integrity."""
    seeder = TestDatabaseSeeder(test_database_config)
    report = await seeder.seed()

    assert report.sql_suggestions_count == 20
    assert report.sql_active_count == 19
    assert report.sql_deleted_count == 1
    assert report.qdrant_suggestion_chunks_count == 82
    assert report.qdrant_regulatory_chunks_count == 10
    assert report.referential_integrity_verified is True

    # 1. Directly inspect PostgreSQL
    engine = create_db_engine(test_database_config.postgres_url)
    try:
        async with engine.connect() as conn:
            await verify_postgres_connection(conn, test_database_config)
            rows = (
                await conn.execute(
                    text("SELECT id, title, is_deleted, status_id FROM suggestions")
                )
            ).mappings().all()

            sql_ids = {r["id"] for r in rows}
            assert len(sql_ids) == 20

            # Verify edge case: soft-deleted suggestion
            deleted_rows = [r for r in rows if r["is_deleted"]]
            assert len(deleted_rows) == 1
            assert deleted_rows[0]["id"] == "sugg-cyber-004"

            # Verify edge case: multi-chunk essay suggestion
            essay_row = next((r for r in rows if r["id"] == "sugg-dist-001"), None)
            assert essay_row is not None
            assert essay_row["status_id"] == SuggestionStatus.APPROVED.status_id
    finally:
        await engine.dispose()

    # 2. Directly inspect Qdrant
    client = AsyncQdrantClient(
        url=test_database_config.qdrant_url,
        api_key=test_database_config.q_api_key,
        check_compatibility=False,
    )
    sugg_col = settings.qdrant_settings.QDRANT_SUGGESTION_COLLECTION
    reg_col = settings.qdrant_settings.QDRANT_REGULATORY_COLLECTION

    try:
        await verify_qdrant_client(client, test_database_config)

        # Retrieve distinct parent_ids from Qdrant
        qdrant_parent_ids = set()
        offset = None
        while True:
            scroll_res, offset = await client.scroll(
                collection_name=sugg_col,
                limit=100,
                offset=offset,
                with_payload=["parent_id"],
                with_vectors=False,
            )
            for pt in scroll_res:
                if pt.payload and "parent_id" in pt.payload:
                    qdrant_parent_ids.add(pt.payload["parent_id"])
            if offset is None:
                break

        # Referential integrity: all Qdrant parent_ids MUST exist in PostgreSQL
        assert qdrant_parent_ids.issubset(sql_ids)

        # Check regulatory chunk count
        reg_count = (await client.count(reg_col, exact=True)).count
        assert reg_count == 10
    finally:
        await client.close()


async def test_seeder_wipes_previous_data_cleanly(test_database_config) -> None:
    """Verifies wipe-first semantics: previous dummy data is deleted, guards survive intact."""
    engine = create_db_engine(test_database_config.postgres_url)
    client = AsyncQdrantClient(
        url=test_database_config.qdrant_url,
        api_key=test_database_config.q_api_key,
        check_compatibility=False,
    )
    sugg_col = settings.qdrant_settings.QDRANT_SUGGESTION_COLLECTION
    reg_col = settings.qdrant_settings.QDRANT_REGULATORY_COLLECTION

    dummy_sql_id = f"dummy-sugg-{uuid.uuid4().hex[:8]}"
    dummy_sugg_chunk_id = str(uuid.uuid4())
    dummy_reg_chunk_id = str(uuid.uuid4())

    try:
        # 1. Insert dummy record into PostgreSQL
        async with engine.begin() as conn:
            await verify_postgres_connection(conn, test_database_config)
            await conn.execute(
                text(
                    "INSERT INTO suggestions (id, title, problem, solution, status_id) "
                    "VALUES (:id, 'عنوان ساختگی موقت', 'مشکل ساختگی موقت', 'راهکار ساختگی موقت', 1)"
                ),
                {"id": dummy_sql_id},
            )

        # 2. Insert dummy points into Qdrant
        await client.upsert(
            collection_name=sugg_col,
            points=[
                models.PointStruct(
                    id=dummy_sugg_chunk_id,
                    vector={
                        settings.qdrant_settings.QDRANT_DENSE_VECTOR_NAME: [0.01] * 768,
                        settings.qdrant_settings.QDRANT_SPARSE_VECTOR_NAME: models.SparseVector(
                            indices=[1], values=[1.0]
                        ),
                    },
                    payload={
                        "parent_id": dummy_sql_id,
                        "chunk_status": "active",
                        "chunk_type": "title",
                        "content": "عنوان ساختگی موقت",
                    },
                )
            ],
            wait=True,
        )

        await client.upsert(
            collection_name=reg_col,
            points=[
                models.PointStruct(
                    id=dummy_reg_chunk_id,
                    vector={
                        settings.qdrant_settings.QDRANT_DENSE_VECTOR_NAME: [0.01] * 768,
                        settings.qdrant_settings.QDRANT_SPARSE_VECTOR_NAME: models.SparseVector(
                            indices=[2], values=[1.0]
                        ),
                    },
                    payload={
                        "parent_id": "dummy-reg-parent",
                        "chunk_status": "active",
                        "content": "مستند قانونی آزمایشی موقت",
                        "document_title": "مستند آزمایشی",
                        "document_type": "statute",
                        "is_binding": True,
                        "authority_level": "binding",
                    },
                )
            ],
            wait=True,
        )

        # Verify dummy records are present
        async with engine.connect() as conn:
            val = await conn.scalar(
                text("SELECT count(*) FROM suggestions WHERE id = :id"),
                {"id": dummy_sql_id},
            )
            assert val == 1

        assert (
            await client.retrieve(sugg_col, ids=[dummy_sugg_chunk_id])
        )

        # 3. Re-run Seeder
        seeder = TestDatabaseSeeder(test_database_config)
        report = await seeder.seed()

        assert report.sql_suggestions_count == 20
        assert report.qdrant_suggestion_chunks_count == 82
        assert report.qdrant_regulatory_chunks_count == 10

        # 4. Verify dummy records are completely wiped
        async with engine.connect() as conn:
            val = await conn.scalar(
                text("SELECT count(*) FROM suggestions WHERE id = :id"),
                {"id": dummy_sql_id},
            )
            assert val == 0

        assert not (
            await client.retrieve(sugg_col, ids=[dummy_sugg_chunk_id])
        )
        assert not (
            await client.retrieve(reg_col, ids=[dummy_reg_chunk_id])
        )

        # 5. Verify environment guards were preserved throughout
        async with engine.connect() as conn:
            await verify_postgres_connection(conn, test_database_config)
        await verify_qdrant_client(client, test_database_config)

    finally:
        await engine.dispose()
        await client.close()


@pytest.mark.parametrize(
    "benchmark",
    BENCHMARK_QUERIES,
    ids=[b.name for b in BENCHMARK_QUERIES],
)
async def test_golden_benchmark_queries_retrieve_expected_suggestions(
    test_database_config,
    benchmark,
) -> None:
    """Verifies that each golden benchmark query successfully retrieves its expected suggestions."""
    client = AsyncQdrantClient(
        url=test_database_config.qdrant_url,
        api_key=test_database_config.q_api_key,
        check_compatibility=False,
    )
    sugg_col = settings.qdrant_settings.QDRANT_SUGGESTION_COLLECTION
    reg_col = settings.qdrant_settings.QDRANT_REGULATORY_COLLECTION

    generator = DeterministicVectorGenerator(dimension=768)
    sugg_repo = QdrantSuggestionRepository(
        client=client,
        collection_name=sugg_col,
        default_dense_dim=768,
    )
    reg_repo = QdrantRegulatoryRepository(
        client=client,
        collection_name=reg_col,
        default_dense_dim=768,
    )

    try:
        dense_q, sparse_q = await generator.generate_query_vectors(
            benchmark.query_text, benchmark.target_cluster
        )

        # 1. Search Suggestions
        sugg_hits = await sugg_repo.search_suggestions(
            dense_vector=dense_q,
            sparse_vector=sparse_q,
            limit=10,
            statuses=[benchmark.filter_status] if benchmark.filter_status else None,
            context_title=benchmark.filter_context,
        )

        assert len(sugg_hits) > 0, f"Expected hits for benchmark '{benchmark.name}', got 0"

        retrieved_parent_ids = [hit.parent_id for hit in sugg_hits]

        # Assert at least one expected suggestion is in top 3 ranks
        top_3_parents = retrieved_parent_ids[:3]
        matched_expected = [
            exp_id for exp_id in benchmark.expected_suggestion_ids if exp_id in top_3_parents
        ]
        assert len(matched_expected) > 0, (
            f"Benchmark '{benchmark.name}' failed to rank expected suggestions {benchmark.expected_suggestion_ids} "
            f"in top 3. Found: {top_3_parents}"
        )

        # Assert negative distractors do not surpass the best expected hit
        best_expected_rank = min(
            (
                retrieved_parent_ids.index(exp_id)
                for exp_id in benchmark.expected_suggestion_ids
                if exp_id in retrieved_parent_ids
            ),
            default=999,
        )

        for neg_id in benchmark.negative_suggestion_ids:
            if neg_id in retrieved_parent_ids:
                neg_rank = retrieved_parent_ids.index(neg_id)
                assert neg_rank > best_expected_rank, (
                    f"Distractor '{neg_id}' (rank {neg_rank}) outranked expected hit (rank {best_expected_rank}) "
                    f"in scenario '{benchmark.name}'"
                )

        # 2. Search Regulatory Knowledge
        reg_hits = await reg_repo.search_regulatory_documents(
            dense_vector=dense_q,
            sparse_vector=sparse_q,
            limit=5,
        )

        if benchmark.expected_regulatory_chunk_ids:
            assert len(reg_hits) > 0
            retrieved_reg_chunk_ids = [hit.chunk.chunk_id for hit in reg_hits]
            matched_reg = [
                exp_chunk_id
                for exp_chunk_id in benchmark.expected_regulatory_chunk_ids
                if exp_chunk_id in retrieved_reg_chunk_ids
            ]
            assert len(matched_reg) > 0, (
                f"Benchmark '{benchmark.name}' failed to retrieve expected regulatory chunks: "
                f"{benchmark.expected_regulatory_chunk_ids}. Retrieved: {retrieved_reg_chunk_ids}"
            )

    finally:
        await client.close()
