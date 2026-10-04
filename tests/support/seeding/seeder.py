"""Automated, idempotent test database seeder for PostgreSQL and Qdrant.

Populates the dedicated test stack (tavanir_test_db and test_tavanir_* collections)
with a curated RAG golden benchmark dataset with cross-store referential integrity,
fail-closed safety checks, and deterministic offline vectors (or optional live TEI embeddings).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from qdrant_client import AsyncQdrantClient, models
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.infrastructure.configs import settings
from src.infrastructure.db import create_db_engine
from src.infrastructure.db.repositories.qdrant.regulatory_repository import (
    QdrantRegulatoryRepository,
)
from src.infrastructure.db.repositories.qdrant.suggestion_repository import (
    QdrantSuggestionRepository,
)
from src.infrastructure.db.repositories.sql.suggestion_repository import (
    SqlSuggestionRepository,
)
from src.infrastructure.services.chunkers.field_aware_suggestion_chunker import (
    FieldAwareSuggestionChunker,
)
from tests.database_safety import (
    DatabaseTestConfig,
    TestDatabaseSafetyError,
    assert_application_settings,
    verify_postgres_connection,
    verify_qdrant_client,
)
from tests.support.seeding.corpus import (
    get_regulatory_cluster,
    get_seed_regulatory_chunks,
    get_seed_suggestions,
    get_suggestion_cluster,
)
from tests.support.seeding.vectors import (
    DeterministicVectorGenerator,
    IVectorGenerator,
    LiveVectorGenerator,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SeedingReport:
    """Report of the executed database seeding run."""

    sql_suggestions_count: int
    sql_active_count: int
    sql_deleted_count: int
    qdrant_suggestion_chunks_count: int
    qdrant_regulatory_chunks_count: int
    referential_integrity_verified: bool


class TestDatabaseSeeder:
    """
    Coordinates fail-closed, idempotent test database seeding across PostgreSQL and Qdrant.
    """

    __test__ = False

    def __init__(
        self,
        config: DatabaseTestConfig,
        vector_generator: IVectorGenerator | None = None,
        live_embeddings: bool = False,
    ) -> None:
        self.config = config
        self.live_embeddings = live_embeddings

        if vector_generator is not None:
            self.vector_generator = vector_generator
        elif live_embeddings:
            from openai import AsyncOpenAI
            from src.infrastructure.services.embeddings import OpenAIDenseEmbedder

            openai_client = AsyncOpenAI(
                base_url=settings.embedding_settings.OPENAI_API_BASE,
                api_key=settings.embedding_settings.OPENAI_API_KEY or "EMPTY",
            )
            dense = OpenAIDenseEmbedder(
                client=openai_client,
                model_name=settings.embedding_settings.EMBEDDING_MODEL,
                dimension=settings.embedding_settings.EMBEDDING_DIMENSION,
                batch_size=settings.embedding_settings.EMBEDDING_BATCH_SIZE,
            )
            self.vector_generator = LiveVectorGenerator(dense_embedder=dense)
        else:
            self.vector_generator = DeterministicVectorGenerator(dimension=768)

    async def seed(self) -> SeedingReport:
        """
        Executes the complete end-to-end seeding pipeline:
        1. Safety verification on PostgreSQL and Qdrant test endpoints.
        2. Postgres data wipe (TRUNCATE data tables, preserving test_environment_guard).
        3. Qdrant data wipe (delete points in test collections, preserving guard collection).
        4. SQL ingestion of 20 golden suggestions.
        5. Field-aware chunking pipeline decomposing suggestions into child chunks.
        6. Deterministic/live vector generation (dense + sparse).
        7. Batch upsert into Qdrant suggestion and regulatory collections.
        8. Cross-store referential integrity verification.
        """
        assert_application_settings(settings, self.config)

        engine = create_db_engine(self.config.postgres_url)
        client = AsyncQdrantClient(
            url=self.config.qdrant_url,
            api_key=self.config.q_api_key,
            check_compatibility=False,
        )

        suggestion_collection = self.config.application_environment()["QDRANT_SUGGESTION_COLLECTION"]
        regulatory_collection = self.config.application_environment()["QDRANT_REGULATORY_COLLECTION"]

        try:
            # 1. Safety Assertions
            async with engine.connect() as conn:
                await verify_postgres_connection(conn, self.config)
            await verify_qdrant_client(client, self.config)

            # 2. Postgres Flush (preserve test_environment_guard)
            logger.info("Wiping previous test data from PostgreSQL tables...")
            async with engine.begin() as conn:
                await verify_postgres_connection(conn, self.config)
                await conn.execute(
                    text(
                        "TRUNCATE TABLE suggestions, ingestion_checkpoints, skipped_suggestions "
                        "RESTART IDENTITY CASCADE"
                    )
                )

            # 3. Qdrant Flush (delete points in test collections, preserve guard collection)
            logger.info("Wiping previous test points from Qdrant collections...")
            for col_name in (suggestion_collection, regulatory_collection):
                if await client.collection_exists(col_name):
                    await client.delete(
                        collection_name=col_name,
                        points_selector=models.FilterSelector(filter=models.Filter()),
                        wait=True,
                    )

            # 4. SQL Ingestion
            logger.info("Ingesting golden suggestions into PostgreSQL...")
            suggestions = get_seed_suggestions()
            session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
            async with session_factory() as session:
                sql_repo = SqlSuggestionRepository(session)
                await sql_repo.save_batch(suggestions)
                await session.commit()

            # 5. Chunking Pipeline
            logger.info("Chunking suggestions using FieldAwareSuggestionChunker...")
            chunker = FieldAwareSuggestionChunker()
            suggestion_chunks = []
            for suggestion in suggestions:
                chunks = await chunker.chunk(suggestion)
                suggestion_chunks.extend(chunks)

            # 6. Vector Assignment (Dense + Sparse)
            logger.info(
                f"Generating embeddings for {len(suggestion_chunks)} suggestion chunks "
                f"via {type(self.vector_generator).__name__}..."
            )
            for chunk in suggestion_chunks:
                cluster = get_suggestion_cluster(chunk.parent_id)
                dense, sparse = await self.vector_generator.generate_chunk_vectors(
                    content=chunk.content, cluster=cluster, chunk_id=chunk.chunk_id
                )
                chunk.dense_vector = dense
                chunk.sparse_vector = sparse

            regulatory_chunks = get_seed_regulatory_chunks()
            logger.info(
                f"Generating embeddings for {len(regulatory_chunks)} regulatory chunks..."
            )
            for chunk in regulatory_chunks:
                cluster = get_regulatory_cluster(chunk.chunk_id)
                dense, sparse = await self.vector_generator.generate_chunk_vectors(
                    content=chunk.content, cluster=cluster, chunk_id=chunk.chunk_id
                )
                chunk.dense_vector = dense
                chunk.sparse_vector = sparse

            # 7. Qdrant Ingestion
            logger.info("Batch upserting suggestion and regulatory points to Qdrant...")
            sugg_repo = QdrantSuggestionRepository(
                client=client,
                collection_name=suggestion_collection,
                default_dense_dim=768,
            )
            reg_repo = QdrantRegulatoryRepository(
                client=client,
                collection_name=regulatory_collection,
                default_dense_dim=768,
            )

            await sugg_repo.upsert_chunks_batch(suggestion_chunks)
            await reg_repo.upsert_chunks_batch(regulatory_chunks)

            # 8. Referential Integrity & Validation
            logger.info("Verifying cross-store referential integrity and counts...")
            async with engine.connect() as conn:
                await verify_postgres_connection(conn, self.config)
                sql_rows = (
                    await conn.execute(
                        text(
                            "SELECT id, is_deleted FROM suggestions"
                        )
                    )
                ).mappings().all()

            sql_ids = {row["id"] for row in sql_rows}
            sql_active_count = sum(1 for row in sql_rows if not row["is_deleted"])
            sql_deleted_count = sum(1 for row in sql_rows if row["is_deleted"])

            if len(sql_ids) != len(suggestions):
                raise TestDatabaseSafetyError(
                    f"PostgreSQL suggestion count mismatch: expected {len(suggestions)}, found {len(sql_ids)}"
                )

            # Retrieve distinct parent_ids from Qdrant suggestions
            qdrant_parent_ids: set[str] = set()
            offset = None
            while True:
                scroll_res, offset = await client.scroll(
                    collection_name=suggestion_collection,
                    limit=100,
                    offset=offset,
                    with_payload=["parent_id"],
                    with_vectors=False,
                )
                for point in scroll_res:
                    if point.payload and "parent_id" in point.payload:
                        qdrant_parent_ids.add(point.payload["parent_id"])
                if offset is None:
                    break

            if not qdrant_parent_ids.issubset(sql_ids):
                orphans = qdrant_parent_ids - sql_ids
                raise TestDatabaseSafetyError(
                    f"Referential integrity failure: Qdrant points reference non-existent SQL parent IDs: {orphans}"
                )

            q_sugg_count = (await client.count(suggestion_collection, exact=True)).count
            q_reg_count = (await client.count(regulatory_collection, exact=True)).count

            if q_sugg_count != len(suggestion_chunks):
                raise TestDatabaseSafetyError(
                    f"Qdrant suggestion chunk count mismatch: expected {len(suggestion_chunks)}, found {q_sugg_count}"
                )
            if q_reg_count != len(regulatory_chunks):
                raise TestDatabaseSafetyError(
                    f"Qdrant regulatory chunk count mismatch: expected {len(regulatory_chunks)}, found {q_reg_count}"
                )

            report = SeedingReport(
                sql_suggestions_count=len(sql_ids),
                sql_active_count=sql_active_count,
                sql_deleted_count=sql_deleted_count,
                qdrant_suggestion_chunks_count=q_sugg_count,
                qdrant_regulatory_chunks_count=q_reg_count,
                referential_integrity_verified=True,
            )
            logger.info(
                f"Seeding completed successfully: {report.sql_suggestions_count} SQL suggestions "
                f"({report.sql_active_count} active, {report.sql_deleted_count} deleted), "
                f"{report.qdrant_suggestion_chunks_count} suggestion chunks, "
                f"{report.qdrant_regulatory_chunks_count} regulatory chunks. "
                f"Referential integrity: verified."
            )
            return report

        finally:
            await engine.dispose()
            await client.close()


async def run_seeder(
    config: DatabaseTestConfig, live_embeddings: bool = False
) -> SeedingReport:
    """Convenience entry point for running the test database seeder."""
    seeder = TestDatabaseSeeder(config, live_embeddings=live_embeddings)
    return await seeder.seed()
