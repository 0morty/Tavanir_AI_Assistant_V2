from __future__ import annotations

from uuid import uuid4

import structlog

from src.application.dtos import CreateSuggestionDTO, IngestSuggestionResponseDTO
from src.application.interfaces import ITaskQueueService, ITextNormalizer, IUnitOfWork
from src.application.services.suggestion_normalizer import normalize_suggestion
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
    SuggestionAlreadyExistsError,
    SuggestionChunkingError,
)
from src.domain.interfaces import ISuggestionChunker

logger = structlog.get_logger(__name__)


class IngestSuggestionUseCase:
    """
    Orchestrates ingestion of employee suggestions via Transactional Outbox (ADR-001, ADR-002).
    Saves suggestion entity and appends SUGGESTION_INGESTED outbox event in a single
    atomic PostgreSQL transaction, eliminating dual-write compensation failures (F-08 & F-09).
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

    async def execute(self, dto: CreateSuggestionDTO) -> IngestSuggestionResponseDTO:
        # Step 1: Pre-check duplicate existence within transaction (Gatekeeper)
        async with self._uow as uow:
            existing = await uow.suggestions.get_by_id(
                dto.suggestion_id, include_deleted=True
            )
            if existing is not None:
                raise SuggestionAlreadyExistsError(
                    f"Suggestion with ID '{dto.suggestion_id}' already exists.",
                    pointer="/data/suggestionId",
                )

        # Step 2: Build domain entities & validate invariants
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

        raw_suggestion = Suggestion(
            id=dto.suggestion_id,
            content=content,
            evaluation=evaluation,
            date=date,
            context_title=dto.context_title,
            secretariat_evaluation=secretariat_evaluation,
            is_deleted=False,
            version=1,
        )

        # Step 3: Normalize Persian text
        normalized_suggestion = normalize_suggestion(raw_suggestion, self._normalizer)

        # Step 4: Validate chunking decomposes cleanly in-memory
        chunks = await self._chunker.chunk(normalized_suggestion)
        if not chunks:
            raise SuggestionChunkingError(
                f"Chunking produced 0 chunks for suggestion '{dto.suggestion_id}'."
            )
        chunks_count = len(chunks)

        # Step 5: Single Atomic PostgreSQL Transaction (Entity + Outbox)
        event_id = uuid4()
        event = OutboxEvent(
            id=event_id,
            resource_type=OutboxResourceType.SUGGESTION,
            resource_id=dto.suggestion_id,
            event_type=OutboxEventType.SUGGESTION_INGESTED,
            version=normalized_suggestion.version,
            payload={
                "suggestion_id": dto.suggestion_id,
                "version": normalized_suggestion.version,
            },
        )

        async with self._uow as uow:
            await uow.suggestions.save(normalized_suggestion)
            await uow.outbox.append(event)
            await uow.commit()

        # Step 6: Asynchronous Dispatch via ARQ (fire-and-forget buffer)
        try:
            await self._task_queue.enqueue_task(
                "process_outbox_event_task",
                event_id=str(event_id),
                deduplication_id=str(event_id),
            )
        except Exception as queue_err:
            await logger.awarning(
                "Failed to enqueue outbox event to Redis; scheduled sweeper will recover it",
                event_id=str(event_id),
                error=str(queue_err),
            )

        await logger.ainfo(
            "Ingested suggestion with outbox event",
            suggestion_id=dto.suggestion_id,
            event_id=str(event_id),
            chunks_count=chunks_count,
        )

        return IngestSuggestionResponseDTO(
            suggestion_id=dto.suggestion_id,
            chunks_count=chunks_count,
            status="CREATED",
        )


__all__ = ["IngestSuggestionUseCase"]
