from __future__ import annotations

from uuid import uuid4

import structlog

from src.application.dtos import (
    PatchSuggestionDTO,
    UpdateSuggestionDTO,
    UpdateSuggestionResponseDTO,
)
from src.application.interfaces import (
    ITaskQueueService,
    ITextNormalizer,
    IUnitOfWork,
)
from src.application.services.suggestion_normalizer import normalize_suggestion
from src.application.utils.advisory_lock import suggestion_id_to_lock_key
from src.domain.entities import (
    CommitteeEvaluation,
    OutboxEvent,
    SecretariatEvaluation,
    ShamsiDate,
    Suggestion,
    SuggestionContent,
)
from src.domain.enums import OutboxEventType, OutboxResourceType
from src.domain.exceptions import (
    SuggestionChunkingError,
    SuggestionNotFoundError,
    SuggestionProcessingConflictError,
)
from src.domain.interfaces import ISuggestionChunker

logger = structlog.get_logger(__name__)


class UpdateSuggestionUseCase:
    """
    Orchestrates RESTful updates (PUT full replacement and PATCH partial update)
    via Transactional Outbox (ADR-001, ADR-002).
    Saves updated suggestion entity and appends SUGGESTION_UPDATED outbox event
    within a single atomic PostgreSQL transaction, permanently resolving dual-write
    inconsistencies (F-01, F-12, FIX-ME).
    """

    def __init__(
        self,
        uow: IUnitOfWork,
        normalizer: ITextNormalizer,
        chunker: ISuggestionChunker,
        task_queue: ITaskQueueService,
    ) -> None:
        self._uow = uow
        self._normalizer = normalizer
        self._chunker = chunker
        self._task_queue = task_queue

    async def execute_put(
        self, dto: UpdateSuggestionDTO
    ) -> UpdateSuggestionResponseDTO:
        """Execute full replacement update (PUT). Replaces state and reactivates soft-deleted record."""
        return await self._execute_mutation(dto, is_patch=False)

    async def execute_patch(
        self, dto: PatchSuggestionDTO
    ) -> UpdateSuggestionResponseDTO:
        """Execute partial update (PATCH). Overlays non-null fields; rejects soft-deleted records."""
        return await self._execute_mutation(dto, is_patch=True)

    async def execute(
        self, dto: UpdateSuggestionDTO | PatchSuggestionDTO
    ) -> UpdateSuggestionResponseDTO:
        """Polymorphic entry point for update execution."""
        if isinstance(dto, PatchSuggestionDTO):
            return await self.execute_patch(dto)
        return await self.execute_put(dto)

    async def _execute_mutation(
        self,
        dto: UpdateSuggestionDTO | PatchSuggestionDTO,
        *,
        is_patch: bool,
    ) -> UpdateSuggestionResponseDTO:
        suggestion_id = dto.suggestion_id
        lock_key = suggestion_id_to_lock_key(suggestion_id)

        # Single Atomic PostgreSQL Transaction with Advisory Mutex
        async with self._uow as uow:
            locked = await uow.try_acquire_advisory_lock(lock_key)
            if not locked:
                raise SuggestionProcessingConflictError(
                    f"Suggestion '{suggestion_id}' is currently being modified by another operation.",
                    pointer="/data/suggestionId",
                )

            # Re-verify current state inside lock
            current = await uow.suggestions.get_by_id(
                suggestion_id, include_deleted=True
            )
            if current is None:
                raise SuggestionNotFoundError(
                    f"Suggestion with ID '{suggestion_id}' not found.",
                    pointer="/data/suggestionId",
                )

            if is_patch and current.is_deleted:
                raise SuggestionNotFoundError(
                    f"Suggestion '{suggestion_id}' was deleted.",
                    pointer="/data/suggestionId",
                )

            # Assemble candidate domain entity
            if is_patch:
                assert isinstance(dto, PatchSuggestionDTO)
                candidate_suggestion = self._build_patched_suggestion(current, dto)
            else:
                assert isinstance(dto, UpdateSuggestionDTO)
                candidate_suggestion = self._build_put_suggestion(current, dto)

            # Normalize Persian text
            normalized_suggestion = normalize_suggestion(
                candidate_suggestion, self._normalizer
            )

            # Validate in-memory chunking
            chunks = await self._chunker.chunk(normalized_suggestion)
            if not chunks:
                raise SuggestionChunkingError(
                    f"Chunking produced 0 chunks for suggestion '{suggestion_id}'."
                )
            chunks_count = len(chunks)

            # Persist updated entity and append OutboxEvent atomically
            event_id = uuid4()
            event = OutboxEvent(
                id=event_id,
                resource_type=OutboxResourceType.SUGGESTION,
                resource_id=suggestion_id,
                event_type=OutboxEventType.SUGGESTION_UPDATED,
                version=normalized_suggestion.version,
                payload={
                    "suggestion_id": suggestion_id,
                    "version": normalized_suggestion.version,
                },
            )

            await uow.suggestions.save(normalized_suggestion)
            await uow.outbox.append(event)
            await uow.commit()

        # Asynchronous Dispatch via ARQ (fire-and-forget buffer)
        try:
            await self._task_queue.enqueue_task(
                "process_outbox_event_task",
                event_id=str(event_id),
                deduplication_id=str(event_id),
            )
        except Exception as queue_err:
            await logger.awarning(
                "Failed to enqueue update outbox event to Redis; sweeper will recover it",
                event_id=str(event_id),
                error=str(queue_err),
            )

        await logger.ainfo(
            "Suggestion updated with outbox event",
            suggestion_id=suggestion_id,
            event_id=str(event_id),
            chunks_count=chunks_count,
            version=normalized_suggestion.version,
            is_patch=is_patch,
        )

        return UpdateSuggestionResponseDTO(
            suggestion_id=suggestion_id,
            chunks_count=chunks_count,
            version=normalized_suggestion.version,
            status="UPDATED",
        )

    def _build_put_suggestion(
        self, existing: Suggestion, dto: UpdateSuggestionDTO
    ) -> Suggestion:
        """Construct full replacement Suggestion (PUT), reactivating deleted rows."""
        content = SuggestionContent(
            title=dto.title,
            problem=dto.problem,
            solution=dto.solution,
        )
        evaluation = CommitteeEvaluation(
            status=dto.status,
            scrutiny=dto.committee_scrutiny,
            description=dto.description,
            scrutiny_id=dto.committee_scrutiny_id,
        )
        secretariat_evaluation: SecretariatEvaluation | None = None
        if (
            dto.secretariat_scrutiny is not None
            or dto.secretariat_comment is not None
            or dto.secretariat_scrutiny_id is not None
        ):
            secretariat_evaluation = SecretariatEvaluation(
                scrutiny=dto.secretariat_scrutiny,
                comment=dto.secretariat_comment,
                scrutiny_id=dto.secretariat_scrutiny_id,
            )

        date = ShamsiDate(dto.shamsi_date) if dto.shamsi_date else None

        return Suggestion(
            id=dto.suggestion_id,
            content=content,
            evaluation=evaluation,
            date=date,
            context_title=dto.context_title,
            secretariat_evaluation=secretariat_evaluation,
            is_deleted=False,  # PUT restores/reactivates
            version=existing.version + 1,
        )

    def _build_patched_suggestion(
        self, existing: Suggestion, dto: PatchSuggestionDTO
    ) -> Suggestion:
        """Construct partially updated Suggestion (PATCH), keeping omitted or null fields."""
        title = dto.title if dto.title is not None else existing.content.title
        problem = dto.problem if dto.problem is not None else existing.content.problem
        solution = (
            dto.solution if dto.solution is not None else existing.content.solution
        )

        content = SuggestionContent(
            title=title,
            problem=problem,
            solution=solution,
        )

        status = dto.status if dto.status is not None else existing.evaluation.status
        committee_scrutiny = (
            dto.committee_scrutiny
            if dto.committee_scrutiny is not None
            else existing.evaluation.scrutiny
        )
        description = (
            dto.description
            if dto.description is not None
            else existing.evaluation.description
        )
        committee_scrutiny_id = (
            dto.committee_scrutiny_id
            if dto.committee_scrutiny_id is not None
            else existing.evaluation.scrutiny_id
        )

        evaluation = CommitteeEvaluation(
            status=status,
            scrutiny=committee_scrutiny,
            description=description,
            scrutiny_id=committee_scrutiny_id,
        )

        # Handle Secretariat Evaluation overlay
        sec_scrutiny = (
            dto.secretariat_scrutiny
            if dto.secretariat_scrutiny is not None
            else (
                existing.secretariat_evaluation.scrutiny
                if existing.secretariat_evaluation
                else None
            )
        )
        sec_comment = (
            dto.secretariat_comment
            if dto.secretariat_comment is not None
            else (
                existing.secretariat_evaluation.comment
                if existing.secretariat_evaluation
                else None
            )
        )
        sec_scrutiny_id = (
            dto.secretariat_scrutiny_id
            if dto.secretariat_scrutiny_id is not None
            else (
                existing.secretariat_evaluation.scrutiny_id
                if existing.secretariat_evaluation
                else None
            )
        )

        secretariat_evaluation: SecretariatEvaluation | None = None
        if (
            sec_scrutiny is not None
            or sec_comment is not None
            or sec_scrutiny_id is not None
        ):
            secretariat_evaluation = SecretariatEvaluation(
                scrutiny=sec_scrutiny,
                comment=sec_comment,
                scrutiny_id=sec_scrutiny_id,
            )

        # Shamsi Date
        date: ShamsiDate | None
        if dto.shamsi_date is not None:
            date = ShamsiDate(dto.shamsi_date)
        else:
            date = existing.date

        context_title = (
            dto.context_title
            if dto.context_title is not None
            else existing.context_title
        )

        return Suggestion(
            id=existing.id,
            content=content,
            evaluation=evaluation,
            date=date,
            context_title=context_title,
            secretariat_evaluation=secretariat_evaluation,
            is_deleted=False,
            version=existing.version + 1,
        )


__all__ = ["UpdateSuggestionUseCase"]
