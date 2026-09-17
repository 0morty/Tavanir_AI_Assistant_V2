from __future__ import annotations

from unittest.mock import MagicMock, patch

import pymssql
import pytest
from src.infrastructure.configs.settings import MssqlSettings
from src.infrastructure.services.extractors.mssql_suggestion_extractor import (
    EXTRACTION_QUERY,
    MssqlSuggestionExtractor,
)

from src.application.dtos import RawSuggestionDataDTO


@pytest.fixture
def mock_mssql_settings() -> MssqlSettings:
    return MssqlSettings(
        MSSQL_SERVER="test-server",
        MSSQL_PORT=1433,
        MSSQL_USER="test-user",
        MSSQL_PASSWORD="test-password",
        MSSQL_DATABASE="test-db",
        MSSQL_BATCH_SIZE=100,
        MSSQL_MAX_RETRIES=2,
        MSSQL_RETRY_BASE_DELAY=0.01,
    )


def test_fetch_page_sync_success(mock_mssql_settings: MssqlSettings):
    extractor = MssqlSuggestionExtractor(config=mock_mssql_settings)

    mock_row_1 = {
        "suggestion_id": "20000//96",
        "title": " پیشنهاد تست کاهش مصرف ",
        "current_problem": "مشکل در ساعت پیک",
        "solution": "استفاده از باتری",
        "status": "مصوب",
        "status_id": 11,
        "committee_scrutiny": "تصویب در کارگروه",
        "committee_scrutiny_description": "مصوب گردید",
        "date": "1402/05/10",
        "context_title": "توزیع برق",
    }
    mock_row_2 = {
        "suggestion_id": "20002//97",
        "title": "سیستم پایش ترانس",
        "current_problem": None,
        "solution": None,
        "status": "رد",
        "status_id": 10,
        "committee_scrutiny": "رد شده",
        "committee_scrutiny_description": "",
        "date": None,
        "context_title": None,
    }

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [mock_row_1, mock_row_2]
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch.object(extractor, "_get_connection", return_value=mock_conn):
        results = extractor._fetch_page_sync(offset=1000, batch_size=50)

    assert len(results) == 2
    assert isinstance(results[0], RawSuggestionDataDTO)
    assert results[0].suggestion_id == "20000//96"
    assert results[0].title == "پیشنهاد تست کاهش مصرف"
    assert results[0].status_id == 11
    assert results[0].shamsi_date == "1402/05/10"
    assert results[0].context_title == "توزیع برق"

    assert results[1].suggestion_id == "20002//97"
    assert results[1].shamsi_date is None
    assert results[1].problem is None

    mock_cursor.execute.assert_called_once_with(EXTRACTION_QUERY, (1000, 50))
    mock_conn.close.assert_called_once()


def test_fetch_page_sync_retries_on_operational_error(
    mock_mssql_settings: MssqlSettings,
):
    extractor = MssqlSuggestionExtractor(config=mock_mssql_settings)

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    # Fail first time, succeed second time
    with patch.object(
        extractor,
        "_get_connection",
        side_effect=[pymssql.OperationalError("DB connection lost"), mock_conn],
    ):
        results = extractor._fetch_page_sync(offset=0, batch_size=10)

    assert results == []
    assert mock_conn.cursor.called


def test_fetch_page_sync_raises_when_retries_exceeded(
    mock_mssql_settings: MssqlSettings,
):
    extractor = MssqlSuggestionExtractor(config=mock_mssql_settings)

    with (
        patch.object(
            extractor,
            "_get_connection",
            side_effect=pymssql.OperationalError("Cannot connect"),
        ),
        pytest.raises(pymssql.OperationalError),
    ):
        extractor._fetch_page_sync(offset=0, batch_size=10)


@pytest.mark.asyncio
async def test_stream_suggestions_batches(mock_mssql_settings: MssqlSettings):
    extractor = MssqlSuggestionExtractor(config=mock_mssql_settings)

    batch_1 = [
        RawSuggestionDataDTO(
            suggestion_id="20000//96",
            title="Title 1",
            problem="P1",
            solution="S1",
            status_id=11,
            scrutiny="Scrutiny 1",
            description="Desc 1",
            shamsi_date="1402/01/01",
            context_title="Context",
        ),
        RawSuggestionDataDTO(
            suggestion_id="20002//97",
            title="Title 2",
            problem="P2",
            solution="S2",
            status_id=12,
            scrutiny="Scrutiny 2",
            description="Desc 2",
            shamsi_date="1402/01/02",
            context_title="Context",
        ),
    ]
    batch_2 = [
        RawSuggestionDataDTO(
            suggestion_id="20003//98",
            title="Title 3",
            problem="P3",
            solution="S3",
            status_id=21,
            scrutiny="Scrutiny 3",
            description="Desc 3",
            shamsi_date="1402/01/03",
            context_title="Context",
        ),
    ]

    with patch.object(
        extractor,
        "_fetch_page_sync",
        side_effect=[batch_1, batch_2, []],
    ) as mock_fetch:
        collected: list[list[RawSuggestionDataDTO]] = []
        async for batch in extractor.stream_suggestions(batch_size=2, start_offset=100):
            collected.append(batch)

        assert len(collected) == 2
        assert len(collected[0]) == 2
        assert len(collected[1]) == 1
        assert collected[0][1].suggestion_id == "20002//97"
        assert collected[1][0].suggestion_id == "20003//98"

        assert mock_fetch.call_count == 3
        # First call offset = 100
        assert mock_fetch.call_args_list[0][0] == (100, 2)
        # Second call offset = 102 (100 + 2)
        assert mock_fetch.call_args_list[1][0] == (102, 2)
        # Third call offset = 103 (102 + 1)
        assert mock_fetch.call_args_list[2][0] == (103, 2)

