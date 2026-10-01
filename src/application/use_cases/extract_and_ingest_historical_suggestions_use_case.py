from __future__ import annotations

import time
from collections.abc import Callable

import structlog

from src.application.dtos import (
    HistoricalIngestionResultDTO,
    SkippedRecordDTO,
)
from src.application.interfaces import IUnitOfWork
from src.application.interfaces.i_historical_suggestion_extractor import (
    IHistoricalSuggestionExtractor,
)
from src.application.interfaces.i_hybrid_embedding_service import (
    IHybridEmbeddingService,
)
from src.application.interfaces.i_text_normalizer import ITextNormalizer
from src.application.services.suggestion_normalizer import normalize_suggestion
from src.domain.entities import (
    Chunk,
    CommitteeEvaluation,
    SecretariatEvaluation,
    ShamsiDate,
    Suggestion,
    SuggestionChunkMetadata,
    SuggestionContent,
)
from src.domain.enums import (
    ChunkStatus,
    CommitteeScrutiny,
    SecretariatScrutiny,
    SuggestionStatus,
)
from src.domain.exceptions import (
    DomainError,
    InvalidSuggestionStatusError,
)
from src.domain.interfaces import (
    ISuggestionChunker,
    ISuggestionVectorRepository,
)
from src.infrastructure.configs.settings import (
    historical_ingestion_settings,
)

logger = structlog.get_logger(__name__)

# Translation table for Persian/Arabic numerals to ASCII
_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


_LEGACY_STATUS_MAP: dict[int, SuggestionStatus] = {
    # Direct domain status IDs (1..5 as emitted by EXTRACTION_QUERY)
    1: SuggestionStatus.NOT_ACCEPTED,
    2: SuggestionStatus.REJECTED,
    3: SuggestionStatus.APPROVED,
    4: SuggestionStatus.PENDING,
    5: SuggestionStatus.EXECUTED,
    # Raw legacy MSSQL LastSuggestionStatusIDs (fallback if un-normalized IDs are passed)
    10: SuggestionStatus.REJECTED,
    56: SuggestionStatus.REJECTED,
    15: SuggestionStatus.NOT_ACCEPTED,
    11: SuggestionStatus.APPROVED,
    12: SuggestionStatus.APPROVED,
    18: SuggestionStatus.APPROVED,
    19: SuggestionStatus.APPROVED,
    30: SuggestionStatus.APPROVED,
    46: SuggestionStatus.APPROVED,
    47: SuggestionStatus.APPROVED,
    55: SuggestionStatus.APPROVED,
    21: SuggestionStatus.PENDING,
    27: SuggestionStatus.PENDING,
    48: SuggestionStatus.PENDING,
    13: SuggestionStatus.EXECUTED,
    20: SuggestionStatus.EXECUTED,
}


def _resolve_suggestion_status(status_id: int) -> SuggestionStatus:
    """Resolve legacy MSSQL status ID or domain status ID into domain SuggestionStatus."""
    if status_id in _LEGACY_STATUS_MAP:
        return _LEGACY_STATUS_MAP[status_id]
    raise InvalidSuggestionStatusError(f"Unknown suggestion status ID: {status_id}")


def _normalize_legacy_shamsi_date(raw_date: str | None) -> ShamsiDate | None:
    """
    Safely normalizes legacy Persian date strings (converting Persian/Arabic numerals,
    padding single-digit months/days, replacing dashes with slashes).
    Returns None if date is empty or invalid, preserving domain invariants.
    """
    if not raw_date or not raw_date.strip():
        return None

    cleaned = raw_date.strip().translate(_PERSIAN_DIGITS)
    cleaned = cleaned.replace("-", "/").replace(".", "/")
    parts = cleaned.split("/")

    if len(parts) == 3:
        try:
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            formatted = f"{year:04d}/{month:02d}/{day:02d}"
            return ShamsiDate(formatted)
        except (ValueError, DomainError):
            return None
    return None


def _resolve_committee_scrutiny(
    scrutiny_id: int | None, raw_scrutiny: str | None
) -> tuple[CommitteeScrutiny | None, int | None]:
    """Resolve committee scrutiny strictly, raising InvalidCommitteeScrutinyError on unmapped codes or titles."""
    if scrutiny_id is not None:
        enum_val = CommitteeScrutiny.from_code(scrutiny_id)
        return enum_val, scrutiny_id
    if raw_scrutiny is not None and raw_scrutiny.strip():
        enum_val = CommitteeScrutiny.from_string(raw_scrutiny.strip())
        return enum_val, enum_val.code
    return None, None


def _resolve_secretariat_scrutiny(
    scrutiny_id: int | None, raw_scrutiny: str | None
) -> tuple[SecretariatScrutiny | None, int | None]:
    """Resolve secretariat scrutiny strictly, raising InvalidSecretariatScrutinyError on unmapped codes or titles."""
    if scrutiny_id is not None:
        enum_val = SecretariatScrutiny.from_code(scrutiny_id)
        return enum_val, scrutiny_id
    if raw_scrutiny is not None and raw_scrutiny.strip():
        enum_val = SecretariatScrutiny.from_string(raw_scrutiny.strip())
        return enum_val, enum_val.code
    return None, None


class ExtractAndIngestHistoricalSuggestionsUseCase:
    """
    Orchestrates Day 0 batch historical suggestion extraction and dual-write ingestion.
    Conforms to SOLID, Clean Architecture, and Pattern A persistence with compensating rollback.
    """

    def __init__(
        self,
        uow: IUnitOfWork,
        extractor: IHistoricalSuggestionExtractor,
        normalizer: ITextNormalizer,
        chunker: ISuggestionChunker,
        embedding_service: IHybridEmbeddingService,
        vector_repo: ISuggestionVectorRepository,
        job_name: str = historical_ingestion_settings.CHECKPOINT_JOB_NAME,
    ) -> None:
        self._uow = uow
        self._extractor = extractor
        self._normalizer = normalizer
        self._chunker = chunker
        self._embedding_service = embedding_service
        self._vector_repo = vector_repo
        self._job_name = job_name

    async def execute(
        self,
        batch_size: int = 200,
        resume: bool = True,
        reset: bool = False,
        on_progress: Callable[[int, int, int], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> HistoricalIngestionResultDTO:
        """
        Execute full batch ingestion pipeline.

        Args:
            batch_size: Offset query page size.
            resume: Whether to resume from saved watermark in PostgreSQL.
            reset: If True, clears existing watermark before beginning.
            on_progress: Optional callback invoked with (total_extracted, total_ingested, total_skipped).
            should_stop: Optional predicate returning True when a graceful shutdown is requested.
        """
        start_time = time.monotonic()
        total_extracted = 0
        total_ingested = 0
        total_chunks = 0
        total_skipped = 0
        last_processed_id: str | None = None
        start_offset = 0

        # 1. Checkpoint Reset or Watermark Resolution
        if reset:
            async with self._uow as uow:
                await uow.checkpoints.clear_checkpoint(self._job_name)
                await uow.commit()
            await logger.ainfo("checkpoint_reset", job_name=self._job_name)

        if resume and not reset:
            async with self._uow as uow:
                checkpoint = await uow.checkpoints.get_checkpoint(self._job_name)
            if checkpoint is not None:
                start_offset = checkpoint.last_offset
                last_processed_id = checkpoint.last_processed_id
                await logger.ainfo(
                    "checkpoint_resuming",
                    job_name=self._job_name,
                    start_offset=start_offset,
                    last_processed_id=last_processed_id,
                )

        current_offset = start_offset

        # 2. Main Offset Streaming Loop
        async for raw_batch in self._extractor.stream_suggestions(
            batch_size=batch_size, start_offset=start_offset
        ):
            if not raw_batch:
                break

            total_extracted += len(raw_batch)
            batch_valid_suggestions: list[Suggestion] = []
            batch_skipped_records: list[SkippedRecordDTO] = []
            batch_chunks: list[Chunk[SuggestionChunkMetadata]] = []

            # 3. Transform & In-Memory Validation
            for raw in raw_batch:
                try:
                    content = SuggestionContent(
                        title=raw.title,
                        problem=raw.problem or "",
                        solution=raw.solution or "",
                    )
                    com_scrutiny, com_id = _resolve_committee_scrutiny(
                        raw.committee_scrutiny_id, raw.committee_scrutiny
                    )
                    sec_scrutiny, sec_id = _resolve_secretariat_scrutiny(
                        raw.secretariat_scrutiny_id, raw.secretariat_scrutiny
                    )

                    evaluation = CommitteeEvaluation(
                        status=_resolve_suggestion_status(raw.status_id),
                        scrutiny=com_scrutiny,
                        description=raw.description,
                        scrutiny_id=com_id,
                    )

                    secretariat_evaluation: SecretariatEvaluation | None = None
                    if (
                        sec_scrutiny is not None
                        or raw.secretariat_comment is not None
                        or sec_id is not None
                    ):
                        secretariat_evaluation = SecretariatEvaluation(
                            scrutiny=sec_scrutiny,
                            comment=raw.secretariat_comment,
                            scrutiny_id=sec_id,
                        )

                    date = _normalize_legacy_shamsi_date(raw.shamsi_date)

                    raw_suggestion = Suggestion(
                        id=raw.suggestion_id,
                        content=content,
                        evaluation=evaluation,
                        date=date,
                        context_title=raw.context_title,
                        secretariat_evaluation=secretariat_evaluation,
                    )

                    # Text normalization
                    normalized_sug = normalize_suggestion(
                        raw_suggestion, self._normalizer
                    )

                    # Chunking
                    chunks = await self._chunker.chunk(normalized_sug)
                    if not chunks:
                        raise DomainError(
                            f"Chunker produced 0 chunks for suggestion {raw.suggestion_id}"
                        )

                    for c in chunks:
                        c.chunk_status = ChunkStatus.STAGING

                    batch_valid_suggestions.append(normalized_sug)
                    batch_chunks.extend(chunks)

                except Exception as exc:
                    reason = str(exc)
                    error_type = type(exc).__name__
                    await logger.awarning(
                        "skipping_invalid_suggestion",
                        suggestion_id=raw.suggestion_id,
                        reason=reason,
                        error_type=error_type,
                    )
                    batch_skipped_records.append(
                        SkippedRecordDTO(
                            suggestion_id=raw.suggestion_id,
                            reason=reason,
                            error_type=error_type,
                        )
                    )

            # 4. Generate Embeddings (Outside SQL Transaction)
            if batch_chunks:
                await self._embedding_service.embed_chunks(batch_chunks)

            # 5. Pattern A Persistence with Compensating Rollback
            # Step 5a: Short-Lived Relational Transaction
            async with self._uow as uow:
                if batch_valid_suggestions:
                    await uow.suggestions.save_batch(batch_valid_suggestions)
                if batch_skipped_records:
                    await uow.skipped_suggestions.save_batch(batch_skipped_records)
                await uow.commit()

            # Step 5b: Vector Upsert Outside SQL Transaction with Staging Lifecycle and Dual Compensation
            batch_last_id = str(raw_batch[-1].suggestion_id).strip()
            ids_to_delete = [s.id for s in batch_valid_suggestions]
            if batch_chunks:
                try:
                    await self._vector_repo.delete_chunks_by_parent_ids(ids_to_delete)
                    await self._vector_repo.upsert_chunks_batch(batch_chunks)
                    await self._vector_repo.activate_staging_chunks_batch(ids_to_delete)
                except Exception as qdrant_err:
                    await logger.aerror(
                        "qdrant_operation_failed_executing_rollback",
                        batch_last_id=batch_last_id,
                        error=str(qdrant_err),
                        exc_info=True,
                    )

                    # 1. Best-effort Qdrant cleanup (guarded against network drops to ensure SQL rollback runs)
                    try:
                        await self._vector_repo.delete_chunks_by_parent_ids(
                            ids_to_delete
                        )
                        await logger.ainfo(
                            "compensating_qdrant_rollback_completed",
                            rolled_back_count=len(ids_to_delete),
                        )
                    except Exception as qdrant_cleanup_err:
                        await logger.awarning(
                            "compensating_qdrant_rollback_failed; staging chunks remain quarantined",
                            error=str(qdrant_cleanup_err),
                            exc_info=True,
                        )

                    # 2. Guarded SQL compensation rollback
                    try:
                        async with self._uow as comp_uow:
                            await comp_uow.suggestions.delete_batch(ids_to_delete)
                            await comp_uow.commit()
                        await logger.ainfo(
                            "compensating_sql_rollback_completed",
                            rolled_back_count=len(batch_valid_suggestions),
                        )
                    except Exception as comp_err:
                        await logger.acritical(
                            "compensating_sql_rollback_failed",
                            error=str(comp_err),
                            exc_info=True,
                        )

                    raise qdrant_err

            # Step 5c: Checkpoint Watermark Commit upon Qdrant Success
            total_ingested += len(batch_valid_suggestions)
            total_chunks += len(batch_chunks)
            total_skipped += len(batch_skipped_records)
            current_offset += len(raw_batch)
            last_processed_id = batch_last_id

            async with self._uow as cp_uow:
                await cp_uow.checkpoints.save_checkpoint(
                    job_name=self._job_name,
                    offset=current_offset,
                    last_id=batch_last_id,
                    total_processed=total_ingested,
                )
                await cp_uow.commit()

            if on_progress:
                on_progress(total_extracted, total_ingested, total_skipped)

            # 6. Check for Graceful Shutdown Request
            if should_stop and should_stop():
                await logger.ainfo(
                    "graceful_drain_requested",
                    job_name=self._job_name,
                    offset=current_offset,
                    last_processed_id=batch_last_id,
                )
                break

        execution_time = time.monotonic() - start_time
        await logger.ainfo(
            "historical_ingestion_finished",
            job_name=self._job_name,
            execution_time_seconds=round(execution_time, 2),
            total_extracted=total_extracted,
            total_ingested=total_ingested,
            total_chunks=total_chunks,
            total_skipped=total_skipped,
            last_offset=current_offset,
            last_processed_id=last_processed_id,
        )

        return HistoricalIngestionResultDTO(
            total_extracted=total_extracted,
            total_ingested=total_ingested,
            total_chunks=total_chunks,
            total_skipped=total_skipped,
            last_offset=current_offset,
            last_processed_id=last_processed_id,
            execution_time_seconds=execution_time,
        )


__all__ = ["ExtractAndIngestHistoricalSuggestionsUseCase"]
