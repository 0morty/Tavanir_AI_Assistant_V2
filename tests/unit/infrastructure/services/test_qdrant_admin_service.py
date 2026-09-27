from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from qdrant_client import models
from src.infrastructure.services.qdrant.qdrant_admin_service import (
    QdrantAdminService,
)


@pytest.mark.asyncio
async def test_wait_until_ready_success():
    mock_client = AsyncMock()
    mock_client.get_collections.return_value = MagicMock()

    service = QdrantAdminService(client=mock_client)
    await service.wait_until_ready(max_retries=3, delay=0.01)

    mock_client.get_collections.assert_awaited_once()


@pytest.mark.asyncio
async def test_wait_until_ready_timeout_raises_connection_error():
    mock_client = AsyncMock()
    mock_client.get_collections.side_effect = RuntimeError("Connection refused")

    service = QdrantAdminService(client=mock_client)

    with pytest.raises(
        ConnectionError, match="Failed to connect to Qdrant cluster after 3 attempts"
    ):
        await service.wait_until_ready(max_retries=3, delay=0.01)

    assert mock_client.get_collections.await_count == 3


@pytest.mark.asyncio
async def test_delete_collection_if_exists_when_present():
    mock_client = AsyncMock()
    mock_client.collection_exists.return_value = True

    service = QdrantAdminService(client=mock_client)
    await service.delete_collection_if_exists("test_col")

    mock_client.collection_exists.assert_awaited_once_with("test_col")
    mock_client.delete_collection.assert_awaited_once_with("test_col")


@pytest.mark.asyncio
async def test_delete_collection_if_exists_when_absent():
    mock_client = AsyncMock()
    mock_client.collection_exists.return_value = False

    service = QdrantAdminService(client=mock_client)
    await service.delete_collection_if_exists("test_col")

    mock_client.collection_exists.assert_awaited_once_with("test_col")
    mock_client.delete_collection.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_indexing_threshold():
    mock_client = AsyncMock()

    service = QdrantAdminService(client=mock_client)
    await service.set_indexing_threshold("test_col", threshold=0)

    mock_client.update_collection.assert_awaited_once()
    args, kwargs = mock_client.update_collection.call_args
    assert kwargs.get("collection_name") == "test_col"
    optimizer_config = kwargs.get("optimizer_config")
    assert isinstance(optimizer_config, models.OptimizersConfigDiff)
    assert optimizer_config.indexing_threshold == 0


@pytest.mark.asyncio
async def test_wait_for_indexing_settled_immediate_green():
    mock_client = AsyncMock()
    mock_info = MagicMock()
    mock_info.status = "green"
    mock_info.optimizer_status = "ok"
    mock_client.get_collection.return_value = mock_info

    service = QdrantAdminService(client=mock_client)
    await service.wait_for_indexing_settled("test_col", max_checks=3, interval=0.01)

    mock_client.get_collection.assert_awaited_once_with("test_col")


@pytest.mark.asyncio
async def test_wait_for_indexing_settled_polls_until_green():
    mock_client = AsyncMock()
    unsettled_info = MagicMock()
    unsettled_info.status = "yellow"
    unsettled_info.optimizer_status = "optimizing"

    settled_info = MagicMock()
    settled_info.status = "green"
    settled_info.optimizer_status = "ok"

    mock_client.get_collection.side_effect = [unsettled_info, settled_info]

    service = QdrantAdminService(client=mock_client)
    await service.wait_for_indexing_settled("test_col", max_checks=5, interval=0.01)

    assert mock_client.get_collection.await_count == 2


@pytest.mark.asyncio
async def test_wait_for_indexing_settled_timeout_warning():
    mock_client = AsyncMock()
    unsettled_info = MagicMock()
    unsettled_info.status = "yellow"
    unsettled_info.optimizer_status = "optimizing"
    mock_client.get_collection.return_value = unsettled_info

    service = QdrantAdminService(client=mock_client)
    # Does not raise error on timeout; logs warning and proceeds
    await service.wait_for_indexing_settled("test_col", max_checks=3, interval=0.01)

    assert mock_client.get_collection.await_count == 3


@pytest.mark.asyncio
async def test_switch_alias_when_no_existing_alias():
    mock_client = AsyncMock()
    mock_aliases_response = MagicMock()
    mock_aliases_response.aliases = []
    mock_client.get_aliases.return_value = mock_aliases_response

    service = QdrantAdminService(client=mock_client)
    await service.switch_alias("tavanir_suggestion_active", "tavanir_suggestion_v1")

    mock_client.get_aliases.assert_awaited_once()
    mock_client.update_collection_aliases.assert_awaited_once()

    args, kwargs = mock_client.update_collection_aliases.call_args
    operations = kwargs.get("change_aliases_operations")
    assert len(operations) == 1
    assert isinstance(operations[0], models.CreateAliasOperation)
    assert operations[0].create_alias.alias_name == "tavanir_suggestion_active"
    assert operations[0].create_alias.collection_name == "tavanir_suggestion_v1"


@pytest.mark.asyncio
async def test_switch_alias_when_alias_already_exists():
    mock_client = AsyncMock()
    existing_alias = MagicMock()
    existing_alias.alias_name = "tavanir_suggestion_active"
    mock_aliases_response = MagicMock()
    mock_aliases_response.aliases = [existing_alias]
    mock_client.get_aliases.return_value = mock_aliases_response

    service = QdrantAdminService(client=mock_client)
    await service.switch_alias("tavanir_suggestion_active", "tavanir_suggestion_v2")

    mock_client.update_collection_aliases.assert_awaited_once()

    args, kwargs = mock_client.update_collection_aliases.call_args
    operations = kwargs.get("change_aliases_operations")
    assert len(operations) == 2
    assert isinstance(operations[0], models.DeleteAliasOperation)
    assert operations[0].delete_alias.alias_name == "tavanir_suggestion_active"
    assert isinstance(operations[1], models.CreateAliasOperation)
    assert operations[1].create_alias.alias_name == "tavanir_suggestion_active"
    assert operations[1].create_alias.collection_name == "tavanir_suggestion_v2"


@pytest.mark.asyncio
async def test_switch_alias_propagates_exception():
    mock_client = AsyncMock()
    mock_client.get_aliases.side_effect = RuntimeError("Qdrant unreachable")

    service = QdrantAdminService(client=mock_client)

    with pytest.raises(RuntimeError, match="Qdrant unreachable"):
        await service.switch_alias("tavanir_suggestion_active", "tavanir_suggestion_v1")
