from __future__ import annotations

import structlog

from src.application.dtos import (
    BulkDeleteErrorItemDTO,
    BulkDeleteResultDTO,
    BulkDeleteSuggestionsDTO,
)
from src.application.use_cases.delete_suggestion_use_case import (
    DeleteSuggestionUseCase,
)
from src.domain.exceptions import (
    DomainError,
    SuggestionNotFoundError,
    SuggestionProcessingConflictError,
)

logger = structlog.get_logger(__name__)


class BulkDeleteSuggestionsUseCase:
    """
    Orchestrates bulk suggestion soft-deletion with sequential execution,
    per-item error isolation, and RFC 6901 pointer mapping for partial failures.

    Sequential execution prevents connection pool exhaustion and deadlocks
    across multiple concurrent transactions while guaranteeing partial success
    can be reported via HTTP 207 Multi-Status.
    """

    def __init__(self, delete_use_case: DeleteSuggestionUseCase) -> None:
        self._delete_use_case = delete_use_case

    async def execute(self, dto: BulkDeleteSuggestionsDTO) -> BulkDeleteResultDTO:
        deleted_ids: list[str] = []
        errors: list[BulkDeleteErrorItemDTO] = []

        total_requested = len(dto.suggestion_ids)

        for index, suggestion_id in enumerate(dto.suggestion_ids):
            pointer = f"/data/suggestionIds/{index}"
            try:
                await self._delete_use_case.execute(suggestion_id)
                deleted_ids.append(suggestion_id)
            except SuggestionNotFoundError as exc:
                errors.append(
                    BulkDeleteErrorItemDTO(
                        suggestion_id=suggestion_id,
                        index=index,
                        code="SUGGESTION_NOT_FOUND",
                        detail=str(exc),
                        source_pointer=pointer,
                    )
                )
            except SuggestionProcessingConflictError as exc:
                errors.append(
                    BulkDeleteErrorItemDTO(
                        suggestion_id=suggestion_id,
                        index=index,
                        code="SUGGESTION_IN_PROCESSING",
                        detail=str(exc),
                        source_pointer=pointer,
                    )
                )
            except DomainError as exc:
                errors.append(
                    BulkDeleteErrorItemDTO(
                        suggestion_id=suggestion_id,
                        index=index,
                        code="DOMAIN_ERROR",
                        detail=str(exc),
                        source_pointer=pointer,
                    )
                )
            except Exception as exc:
                await logger.aerror(
                    "Unexpected error during bulk deletion item execution",
                    suggestion_id=suggestion_id,
                    index=index,
                    error=str(exc),
                    exc_info=True,
                )
                errors.append(
                    BulkDeleteErrorItemDTO(
                        suggestion_id=suggestion_id,
                        index=index,
                        code="INTERNAL_ERROR",
                        detail="An unexpected error occurred while deleting this suggestion.",
                        source_pointer=pointer,
                    )
                )

        await logger.ainfo(
            "Bulk delete completed",
            total_requested=total_requested,
            total_deleted=len(deleted_ids),
            total_failed=len(errors),
        )

        return BulkDeleteResultDTO(
            deleted_ids=deleted_ids,
            errors=errors,
            total_requested=total_requested,
            total_deleted=len(deleted_ids),
            total_failed=len(errors),
        )


__all__ = ["BulkDeleteSuggestionsUseCase"]
