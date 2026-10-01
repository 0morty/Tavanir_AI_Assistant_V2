from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.containers import Container
from src.infrastructure.configs.settings import (
    DBSettings,
    MssqlSettings,
    qdrant_settings,
)
from src.infrastructure.db.repositories import (
    QdrantSuggestionRepository,
)


def test_db_settings_aliases():
    # Direct field
    db1 = DBSettings(POSTGRES_SERVER="pg_direct", POSTGRES_PORT=5432)
    assert db1.POSTGRES_SERVER == "pg_direct"
    assert "pg_direct:5432" in db1.POSTGRES_URL

    # Alias field POSTGRES_HOST
    db2 = DBSettings(POSTGRES_HOST="pg_alias", POSTGRES_PORT=5432)  # type: ignore[call-arg]
    assert db2.POSTGRES_SERVER == "pg_alias"
    assert "pg_alias:5432" in db2.POSTGRES_URL


def test_mssql_settings_aliases_and_timeout():
    # Direct fields
    m1 = MssqlSettings(
        MSSQL_SERVER="sql_direct",
        MSSQL_PORT=1433,
        MSSQL_USER="usr",
        MSSQL_PASSWORD="pwd",
        MSSQL_DATABASE="db_direct",
        MSSQL_BATCH_SIZE=150,
        MSSQL_QUERY_TIMEOUT=90,
    )
    assert m1.MSSQL_SERVER == "sql_direct"
    assert m1.MSSQL_PORT == 1433
    assert m1.MSSQL_DATABASE == "db_direct"
    assert m1.MSSQL_BATCH_SIZE == 150
    assert m1.MSSQL_QUERY_TIMEOUT == 90

    # Alias fields MSSQL_HOST and MSSQL_DB_NAME
    m2 = MssqlSettings(
        MSSQL_HOST="sql_alias",  # type: ignore[call-arg]
        MSSQL_DB_NAME="db_alias",  # type: ignore[call-arg]
    )
    assert m2.MSSQL_SERVER == "sql_alias"
    assert m2.MSSQL_DATABASE == "db_alias"
    assert m2.MSSQL_QUERY_TIMEOUT == 120  # default


def test_container_vector_repositories_binding():
    container = Container()

    # Active suggestion repository points to ALIAS
    active_repo = container.suggestion_vector_repository()
    assert isinstance(active_repo, QdrantSuggestionRepository)
    assert active_repo._collection_name == qdrant_settings.QDRANT_SUGGESTION_ALIAS

    # Staging suggestion repository points to PHYSICAL target collection
    staging_repo = container.staging_suggestion_vector_repository()
    assert isinstance(staging_repo, QdrantSuggestionRepository)
    assert staging_repo._collection_name == qdrant_settings.QDRANT_SUGGESTION_COLLECTION


@pytest.mark.asyncio
async def test_container_historical_ingest_use_case_wires_staging_repo():
    container = Container()

    # Verify provider kwargs declaration points to staging_suggestion_vector_repository
    assert (
        container.extract_and_ingest_historical_suggestions_use_case.kwargs[
            "vector_repo"
        ]
        is container.staging_suggestion_vector_repository
    )

    mock_client = AsyncMock()
    with patch(
        "src.infrastructure.configs.llm_provider_configs.AsyncOpenAIClientFactory.create_client",
        return_value=mock_client,
    ):
        await container.client_registry.init()
        await container.embedding_client.init()
        try:
            raw_use_case = (
                container.extract_and_ingest_historical_suggestions_use_case()
            )
            use_case = (
                await raw_use_case
                if inspect.isawaitable(raw_use_case)
                else raw_use_case
            )

            # The use case's vector_repo collaborator must point to physical staging collection
            assert (
                use_case._vector_repo._collection_name
                == qdrant_settings.QDRANT_SUGGESTION_COLLECTION
            )
        finally:
            await container.embedding_client.shutdown()
            await container.client_registry.shutdown()


@pytest.mark.asyncio
async def test_container_selective_async_resource_lifecycle():
    container = Container()

    mock_client = AsyncMock()
    with patch(
        "src.infrastructure.configs.llm_provider_configs.AsyncOpenAIClientFactory.create_client",
        return_value=mock_client,
    ):
        await container.client_registry.init()
        await container.embedding_client.init()

        assert container.client_registry() is not None
        assert container.embedding_client() is not None

        await container.embedding_client.shutdown()
        await container.client_registry.shutdown()


def test_docker_entrypoint_script_exists_and_has_unix_newlines():
    entrypoint_path = (
        Path(__file__).resolve().parents[3] / "scripts" / "docker_entrypoint.sh"
    )
    assert entrypoint_path.exists(), f"{entrypoint_path} does not exist"

    raw_bytes = entrypoint_path.read_bytes()
    assert b"\r\n" not in raw_bytes, (
        "docker_entrypoint.sh must use Unix LF line endings"
    )
    content = raw_bytes.decode("utf-8")
    assert "alembic upgrade head" in content
    assert "scripts/setup_postgres.py" in content
    assert "scripts/extract_and_ingest_historical_suggestions.py" in content


@pytest.mark.asyncio
async def test_run_pipeline_handles_awaitable_providers_cleanly():
    from scripts.extract_and_ingest_historical_suggestions import run_pipeline

    from src.application.dtos import HistoricalIngestionResultDTO

    mock_container = MagicMock()
    mock_container.client_registry.init = AsyncMock()
    mock_container.client_registry.shutdown = AsyncMock()
    mock_container.embedding_client.init = AsyncMock()
    mock_container.embedding_client.shutdown = AsyncMock()

    mock_admin = AsyncMock()
    mock_container.qdrant_admin_service.return_value = mock_admin

    mock_repo = AsyncMock()
    mock_container.staging_suggestion_vector_repository.return_value = mock_repo

    mock_use_case = AsyncMock()
    mock_use_case.execute.return_value = HistoricalIngestionResultDTO(
        total_extracted=10,
        total_ingested=10,
        total_chunks=20,
        total_skipped=0,
        last_offset=10,
        last_processed_id="10",
        execution_time_seconds=1.5,
    )

    # Simulate dependency_injector returning a coroutine/future for async-dependent provider
    async def get_awaitable_use_case():
        return mock_use_case

    mock_container.extract_and_ingest_historical_suggestions_use_case.side_effect = (
        get_awaitable_use_case
    )

    with patch(
        "scripts.extract_and_ingest_historical_suggestions.Container",
        return_value=mock_container,
    ):
        await run_pipeline(
            batch_size=10,
            resume=True,
            reset=False,
            skip_gatekeeper=True,
        )

    mock_admin.wait_until_ready.assert_awaited_once()
    mock_repo.provision_collection.assert_awaited_once()
    mock_admin.set_indexing_threshold.assert_any_await(
        qdrant_settings.QDRANT_SUGGESTION_COLLECTION, threshold=0
    )
    mock_admin.set_indexing_threshold.assert_any_await(
        qdrant_settings.QDRANT_SUGGESTION_COLLECTION, threshold=20000
    )
    mock_use_case.execute.assert_awaited_once()
    mock_admin.switch_alias.assert_awaited_once()
    mock_container.embedding_client.shutdown.assert_awaited_once()
    mock_container.client_registry.shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_pipeline_gatekeeper_handles_awaitable_embedders():
    from scripts.extract_and_ingest_historical_suggestions import run_pipeline

    from src.application.dtos import HistoricalIngestionResultDTO

    mock_container = MagicMock()
    mock_container.client_registry.init = AsyncMock()
    mock_container.client_registry.shutdown = AsyncMock()
    mock_container.embedding_client.init = AsyncMock()
    mock_container.embedding_client.shutdown = AsyncMock()

    mock_admin = AsyncMock()
    mock_container.qdrant_admin_service.return_value = mock_admin

    mock_repo = AsyncMock()
    mock_repo.search_suggestions.return_value = ["mock_result"]
    mock_container.staging_suggestion_vector_repository.return_value = mock_repo

    mock_use_case = AsyncMock()
    mock_use_case.execute.return_value = HistoricalIngestionResultDTO(
        total_extracted=5,
        total_ingested=5,
        total_chunks=10,
        total_skipped=0,
        last_offset=5,
        last_processed_id="5",
        execution_time_seconds=1.0,
    )
    mock_container.extract_and_ingest_historical_suggestions_use_case.return_value = (
        mock_use_case
    )

    mock_dense = AsyncMock()
    mock_dense.embed_query.return_value = [0.1] * 768

    async def get_dense():
        return mock_dense

    mock_container.dense_embedder.side_effect = get_dense

    mock_sparse = AsyncMock()
    mock_sparse.embed_query.return_value = MagicMock()

    async def get_sparse():
        return mock_sparse

    mock_container.sparse_embedder.side_effect = get_sparse

    with patch(
        "scripts.extract_and_ingest_historical_suggestions.Container",
        return_value=mock_container,
    ):
        await run_pipeline(
            batch_size=5,
            resume=True,
            reset=False,
            skip_gatekeeper=False,
        )

    assert mock_dense.embed_query.await_count == 3
    assert mock_sparse.embed_query.await_count == 3
    assert mock_repo.search_suggestions.await_count == 3
    mock_admin.switch_alias.assert_awaited_once()
