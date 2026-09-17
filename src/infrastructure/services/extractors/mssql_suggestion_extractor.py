from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any, cast

import pymssql

from src.application.dtos import RawSuggestionDataDTO
from src.application.interfaces.i_historical_suggestion_extractor import (
    IHistoricalSuggestionExtractor,
)
from src.infrastructure.configs.settings import MssqlSettings, mssql_settings

_logger = logging.getLogger(__name__)

EXTRACTION_QUERY = """
WITH LatestCommitteeResult AS (
    SELECT
        SuggestionCode,
        Description,
        ComitteeScrutinyId,
        ROW_NUMBER() OVER (
            PARTITION BY SuggestionCode
            ORDER BY Iteration DESC
        ) as rn
    FROM CommitteeSessionResult WITH (NOLOCK)
)
SELECT
    s.SuggestionId AS suggestion_id,
    s.Date AS date,
    s.Title AS title,
    s.CurrentProblem AS current_problem,
    s.Solution AS solution,
    sc.Name AS context_title,
    CASE
        WHEN si.LastSuggestionStatusID IN (10, 56) THEN N'رد'
        WHEN si.LastSuggestionStatusID IN (2, 15) THEN N'عدم پذیرش'
        WHEN si.LastSuggestionStatusID IN (11, 12, 18, 19, 30, 46, 47, 55) THEN N'مصوب'
        WHEN si.LastSuggestionStatusID IN (21, 27, 48) THEN N'در حال اجرا'
        ELSE N'اجرا شده'
    END AS status,
    CASE
        WHEN si.LastSuggestionStatusID IN (10, 56) THEN 2
        WHEN si.LastSuggestionStatusID IN (2, 15) THEN 1
        WHEN si.LastSuggestionStatusID IN (11, 12, 18, 19, 30, 46, 47, 55) THEN 3
        WHEN si.LastSuggestionStatusID IN (21, 27, 48) THEN 4
        ELSE 5
    END AS status_id,
    cs.Name AS committee_scrutiny,
    ISNULL(lcr.Description, '') AS committee_scrutiny_description
FROM SuggestionInfo si WITH (NOLOCK)
INNER JOIN suggestion s WITH (NOLOCK) ON s.SuggestionId = si.SuggestionInfoId
LEFT JOIN LatestCommitteeResult lcr WITH (NOLOCK) ON lcr.SuggestionCode = s.SuggestionId AND lcr.rn = 1
LEFT JOIN ComitteeScrutiny cs WITH (NOLOCK) ON cs.ComitteeScrutinyId = lcr.ComitteeScrutinyId
LEFT JOIN SuggestContext sc WITH (NOLOCK) ON sc.SuggestContextId = s.SuggestContextId
WHERE si.LastSuggestionStatusID IN (2, 10, 15, 56, 11, 12, 18, 19, 30, 46, 47, 55, 21, 27, 48, 13, 20)
ORDER BY s.SuggestionId ASC
OFFSET %s ROWS FETCH NEXT %s ROWS ONLY;
"""


class MssqlSuggestionExtractor(IHistoricalSuggestionExtractor):
    """
    MSSQL implementation of historical suggestion extractor.
    Extracts suggestions and committee evaluations adhering strictly to manager criteria.
    Uses offset-based pagination and auto-reconnect with exponential backoff.
    """

    def __init__(self, config: MssqlSettings | None = None) -> None:
        self._config = config or mssql_settings

    def _get_connection(self) -> pymssql.Connection[Any]:
        """Create a new connection to MSSQL database with configured timeout."""
        return pymssql.connect(
            server=self._config.MSSQL_SERVER,
            port=str(self._config.MSSQL_PORT),
            user=self._config.MSSQL_USER,
            password=self._config.MSSQL_PASSWORD,
            database=self._config.MSSQL_DATABASE,
            as_dict=True,
            login_timeout=15,
            timeout=30,
            charset="UTF-8",
        )

    def _fetch_page_sync(
        self, offset: int, batch_size: int
    ) -> list[RawSuggestionDataDTO]:
        """Synchronously execute offset query with retries on transient connection drops."""
        attempts = 0
        max_retries = self._config.MSSQL_MAX_RETRIES
        delay = self._config.MSSQL_RETRY_BASE_DELAY

        while attempts <= max_retries:
            attempts += 1
            conn: pymssql.Connection[Any] | None = None
            try:
                conn = self._get_connection()
                with conn.cursor() as cursor:
                    cursor.execute(EXTRACTION_QUERY, (offset, batch_size))
                    rows = cast(list[dict[str, Any]], cursor.fetchall())

                dtos: list[RawSuggestionDataDTO] = []
                for row in rows:
                    dtos.append(
                        RawSuggestionDataDTO(
                            suggestion_id=str(row["suggestion_id"]),
                            title=str(row["title"] or "").strip(),
                            problem=row.get("current_problem"),
                            solution=row.get("solution"),
                            status_id=int(row["status_id"]),
                            scrutiny=row.get("committee_scrutiny"),
                            description=row.get("committee_scrutiny_description"),
                            shamsi_date=str(row["date"]).strip()
                            if row.get("date")
                            else None,
                            context_title=row.get("context_title"),
                        )
                    )
                return dtos
            except (pymssql.OperationalError, pymssql.DatabaseError, OSError) as exc:
                if attempts > max_retries:
                    _logger.error(
                        f"MSSQL extraction query failed after {max_retries} retries: {exc}",
                        exc_info=True,
                    )
                    raise
                _logger.warning(
                    f"MSSQL connection error on attempt {attempts}/{max_retries}: {exc}. "
                    f"Retrying in {delay:.2f}s..."
                )
                time.sleep(delay)
                delay *= 2
            finally:
                if conn is not None:
                    with contextlib.suppress(Exception):
                        conn.close()
        return []

    async def stream_suggestions(
        self, batch_size: int, start_offset: int = 0
    ) -> AsyncGenerator[list[RawSuggestionDataDTO], None]:
        """
        Asynchronously stream pages of raw suggestions using offset-based pagination.
        Yields batches until no further records exist.
        """
        current_offset = max(0, start_offset)
        _logger.info(
            f"Starting MSSQL suggestion extraction streaming (start_offset={current_offset}, batch_size={batch_size})"
        )

        while True:
            batch = await asyncio.to_thread(
                self._fetch_page_sync, current_offset, batch_size
            )
            if not batch:
                _logger.info(
                    f"MSSQL suggestion extraction complete. Reached end of data at offset {current_offset}."
                )
                break

            current_offset += len(batch)
            yield batch


__all__ = ["MssqlSuggestionExtractor", "EXTRACTION_QUERY"]
