from __future__ import annotations

import asyncio
import contextlib

import structlog

from src.application.dtos import (
    PatchSuggestionDTO,
    UpdateSuggestionDTO,
    UpdateSuggestionResponseDTO,
)
from src.application.interfaces import (
    IHybridEmbeddingService,
    ITextNormalizer,
    IUnitOfWork,
)
from src.application.services.suggestion_normalizer import normalize_suggestion
from src.application.utils.advisory_lock import suggestion_id_to_lock_key
from src.domain.entities import (
    CommitteeEvaluation,
    SecretariatEvaluation,
    ShamsiDate,
    Suggestion,
    SuggestionContent,
)
from src.domain.enums import ChunkStatus
from src.domain.exceptions import (
    SuggestionChunkingError,
    SuggestionNotFoundError,
    SuggestionProcessingConflictError,
)
from src.domain.interfaces import (
    ISuggestionChunker,
    ISuggestionVectorRepository,
)

logger = structlog.get_logger(__name__)


class UpdateSuggestionUseCase:
    """
    Orchestrates RESTful updates (PUT full replacement and PATCH partial update)
    with two-phase concurrency control and dual-store zero-blackout cutover.

    Two-Phase Workflow:
    - Phase 1 (Lock-Free):
      1. Fetch current entity snapshot (PUT allows soft-deleted records to restore them;
         PATCH requires active record).
      2. Construct updated candidate Suggestion entity and validate domain invariants.
      3. Normalize Persian text and decompose into field chunks (tagged as STAGING).
      4. Compute dense (TEI) and sparse (BM25) vector embeddings concurrently.
      5. Shadow upsert new chunks into Qdrant in STAGING status (Write-Before-Delete).
    - Phase 2 (Guarded Transaction):
      6. Acquire 64-bit PostgreSQL transaction-scoped advisory lock.
      7. Re-verify record version and active status inside the lock.
      8. Persist updated Suggestion to PostgreSQL via atomic upsert and commit.
    - Phase 3 (Cutover & Cleanup):
      9. Promote STAGING chunks to ACTIVE.
      10. Purge superseded chunks (chunks with parent_id whose IDs are not in new chunks).
    """

    def __init__(
        self,
        uow: IUnitOfWork,
        normalizer: ITextNormalizer,
        chunker: ISuggestionChunker,
        embedding_service: IHybridEmbeddingService,
        vector_repo: ISuggestionVectorRepository,
    ) -> None:
        self._uow = uow
        self._normalizer = normalizer
        self._chunker = chunker
        self._embedding_service = embedding_service
        self._vector_repo = vector_repo

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

        # --- Phase 1: Lock-Free Verification & Preparation ---
        # 1. Fetch current entity snapshot
        async with self._uow as uow:
            # PUT fetches existing row even if soft-deleted (restoration flow)
            # PATCH strictly fetches only active rows
            existing = await uow.suggestions.get_by_id(
                suggestion_id, include_deleted=not is_patch
            )

        if existing is None:
            raise SuggestionNotFoundError(
                f"Suggestion with ID '{suggestion_id}' not found.",
                pointer="/data/suggestionId",
            )

        expected_version = existing.version

        # 2. Assemble candidate domain entity
        if is_patch:
            assert isinstance(dto, PatchSuggestionDTO)
            candidate_suggestion = self._build_patched_suggestion(existing, dto)
        else:
            assert isinstance(dto, UpdateSuggestionDTO)
            candidate_suggestion = self._build_put_suggestion(existing, dto)

        # 3. Normalize Persian text
        normalized_suggestion = normalize_suggestion(
            candidate_suggestion, self._normalizer
        )

        # 4. Decompose into field-isolated chunks (STAGING status)
        chunks = await self._chunker.chunk(normalized_suggestion)
        if not chunks:
            raise SuggestionChunkingError(
                f"Chunking produced 0 chunks for suggestion '{suggestion_id}'."
            )

        for chunk in chunks:
            chunk.chunk_status = ChunkStatus.STAGING

        new_chunk_ids = [chunk.chunk_id for chunk in chunks]

        # 5. Compute dense and sparse embeddings concurrently
        await self._embedding_service.embed_chunks(chunks)

        # 6. Shadow staging in Qdrant (Write-Before-Delete)
        try:
            await self._vector_repo.upsert_chunks_batch(chunks)
        except Exception as qdrant_staging_err:
            await logger.aerror(
                "Failed to upsert staging chunks to Qdrant during update",
                suggestion_id=suggestion_id,
                error=str(qdrant_staging_err),
                exc_info=True,
            )
            # Clean up any partially upserted points from this batch
            with contextlib.suppress(Exception):
                await self._vector_repo.delete_chunks_by_ids(new_chunk_ids)
            raise qdrant_staging_err

        # --- Phase 2: Guarded Transaction Execution with Advisory Lock ---
        try:
            async with self._uow as uow:
                # Acquire PostgreSQL transaction-scoped advisory lock (non-blocking)
                lock_key = suggestion_id_to_lock_key(suggestion_id)
                locked = await uow.try_acquire_advisory_lock(lock_key)
                if not locked:
                    raise SuggestionProcessingConflictError(
                        f"Suggestion '{suggestion_id}' is currently being modified by another operation.",
                        pointer="/data/suggestionId",
                    )

                # Re-verify current state and optimistic version inside the lock
                current = await uow.suggestions.get_by_id(
                    suggestion_id, include_deleted=True
                )
                if current is None:
                    raise SuggestionNotFoundError(
                        f"Suggestion with ID '{suggestion_id}' not found.",
                        pointer="/data/suggestionId",
                    )

                if current.version != expected_version:
                    raise SuggestionProcessingConflictError(
                        f"Suggestion '{suggestion_id}' was modified concurrently (version mismatch: expected {expected_version}, got {current.version}).",
                        pointer="/data/suggestionId",
                    )

                if is_patch and current.is_deleted:
                    raise SuggestionNotFoundError(
                        f"Suggestion '{suggestion_id}' was deleted concurrently.",
                        pointer="/data/suggestionId",
                    )

                # Save updated entity to PostgreSQL
                await uow.suggestions.save(normalized_suggestion)
                await uow.commit()

        except Exception as phase2_err:
            # UoW context manager has exited, rolling back and releasing the PostgreSQL
            # connection back to the pool. Clean up staged chunks without holding any DB connection.
            await logger.awarning(
                "Phase 2 transaction failed or rejected; cleaning up staging chunks",
                suggestion_id=suggestion_id,
                error=str(phase2_err),
            )
            try:
                await self._vector_repo.delete_chunks_by_ids(new_chunk_ids)
            except Exception as cleanup_err:
                await logger.awarning(
                    "Compensating deletion of staging chunks failed",
                    suggestion_id=suggestion_id,
                    error=str(cleanup_err),
                )
            raise phase2_err

        # --- Phase 3: Zero-Downtime Qdrant Cutover & Superseded Purge ---
        # FIXME: [Architectural Tech Debt - Dual-Write Consistency via Transactional Outbox]
        # In case of persistent Qdrant failure, attempting synchronous nested compensation
        # triggers cascading failure loops (calling an already-failing service inside the except block).
        # Target Architecture:
        #   Implement Transactional Outbox pattern. A reconciliation event (e.g. `VectorReconciliationEvent`)
        #   should be recorded in PostgreSQL (within Phase 2), watched by an asynchronous ARQ/Redis background
        #   task. If Phase 3 fails, the background task polls for pending events, executes retries with
        #   exponential backoff and dead-letter queues until Qdrant is eventually consistent, and marks
        #   the event as resolved.
        # Current Mitigation:
        #   Apply in-process bounded retries with exponential backoff to absorb transient network blips
        #   before failing the request.
        max_cutover_retries = 3
        base_delay_seconds = 0.2

        for attempt in range(1, max_cutover_retries + 1):
            try:
                await self._vector_repo.activate_staging_chunks(suggestion_id)
                await self._vector_repo.delete_superseded_chunks(
                    suggestion_id, new_chunk_ids
                )
                break
            except Exception as cutover_err:
                if attempt < max_cutover_retries:
                    delay = base_delay_seconds * (2 ** (attempt - 1))
                    await logger.awarning(
                        "Transient error during Qdrant cutover/purge; retrying",
                        suggestion_id=suggestion_id,
                        attempt=attempt,
                        next_retry_delay_seconds=delay,
                        error=str(cutover_err),
                    )
                    await asyncio.sleep(delay)
                else:
                    await logger.acritical(
                        "Qdrant cutover/promotion failed after all retries; requires outbox reconciliation",
                        suggestion_id=suggestion_id,
                        total_attempts=max_cutover_retries,
                        error=str(cutover_err),
                        exc_info=True,
                    )
                    raise cutover_err

        await logger.ainfo(
            "Suggestion updated successfully",
            suggestion_id=suggestion_id,
            chunks_count=len(chunks),
            version=normalized_suggestion.version,
            is_patch=is_patch,
        )

        return UpdateSuggestionResponseDTO(
            suggestion_id=suggestion_id,
            chunks_count=len(chunks),
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
