import structlog

from src.application.dtos import CreateSuggestionDTO, IngestSuggestionResponseDTO
from src.application.interfaces import IUnitOfWork
from src.application.interfaces.i_hybrid_embedding_service import (
    IHybridEmbeddingService,
)
from src.application.interfaces.i_text_normalizer import ITextNormalizer
from src.application.services.suggestion_normalizer import normalize_suggestion
from src.domain.entities import (
    CommitteeEvaluation,
    SecretariatEvaluation,
    ShamsiDate,
    Suggestion,
    SuggestionContent,
)
from src.domain.enums import ChunkStatus
from src.domain.exceptions import (
    SuggestionAlreadyExistsError,
    SuggestionChunkingError,
)
from src.domain.interfaces import (
    ISuggestionChunker,
    ISuggestionVectorRepository,
)

logger = structlog.get_logger(__name__)


class IngestSuggestionUseCase:
    """
    Orchestrates the synchronous ingestion pipeline for employee suggestions (ADR-001, ADR-002).

    Pipeline Flow:
    1. Pre-check idempotency/conflict via short-lived UoW (raises SuggestionAlreadyExistsError).
       Acts as strict gatekeeper to guarantee no healthy data is ever purged from Qdrant.
    2. Construct domain entity & validate domain invariants (raises InvalidSuggestionContentError).
    3. Normalize Persian text across all fields.
    4. Decompose suggestion into field-isolated child chunks (TITLE, PROBLEM, SOLUTION, EVALUATION)
       and tag them with ChunkStatus.STAGING.
    5. Compute dense and sparse embeddings concurrently via IHybridEmbeddingService.
    6. Pattern A Persistence with Staging Lifecycle:
       a. Fast PostgreSQL persistence via short-lived UoW.
       b. Guarded Qdrant execution:
          - Pre-emptive purge of residual chunks from previous crashed attempts.
          - Batch upsert of chunks in STAGING status.
          - Atomic promotion from STAGING to ACTIVE.
       c. If Qdrant fails at any point:
          - Best-effort compensating deletion in Qdrant.
          - Guarded compensating SQL deletion to maintain dual-write consistency.
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

    async def execute(self, dto: CreateSuggestionDTO) -> IngestSuggestionResponseDTO:
        # Step 1: Pre-check duplicate existence (Gatekeeper: protects healthy suggestions and soft-deleted records)
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
        )

        # Step 3: Normalize Persian text
        normalized_suggestion = normalize_suggestion(raw_suggestion, self._normalizer)

        # Step 4: Decompose into field-isolated chunks and tag with STAGING status
        chunks = await self._chunker.chunk(normalized_suggestion)
        if not chunks:
            raise SuggestionChunkingError(
                f"Chunking produced 0 chunks for suggestion '{dto.suggestion_id}'."
            )
        for chunk in chunks:
            chunk.chunk_status = ChunkStatus.STAGING

        # Step 5: Generate dense and sparse embeddings concurrently
        await self._embedding_service.embed_chunks(chunks)

        # Step 6: Pattern A Persistence with Staging Lifecycle
        # 6a. Persist to PostgreSQL via short-lived UoW
        async with self._uow as uow:
            await uow.suggestions.save(normalized_suggestion)
            await uow.commit()

        # 6b. Guarded Qdrant Operations (Purge residual -> Upsert STAGING -> Promote ACTIVE)
        try:
            # Pre-emptive cleanup: only safe because Step 1 confirmed this ID does not exist in SQL.
            # Guarantees no lingering chunks from a prior crashed ingestion remain.
            await self._vector_repo.delete_chunks_by_parent_id(dto.suggestion_id)
            await self._vector_repo.upsert_chunks_batch(chunks)
            await self._vector_repo.activate_staging_chunks(dto.suggestion_id)
        except Exception as qdrant_err:
            await logger.aerror(
                "Qdrant operation failed during suggestion ingestion; executing compensating cleanups",
                suggestion_id=dto.suggestion_id,
                error=str(qdrant_err),
                exc_info=True,
            )

            # 1. Best-effort Qdrant cleanup (guarded against network drops to ensure SQL rollback runs)
            try:
                await self._vector_repo.delete_chunks_by_parent_id(dto.suggestion_id)
                await logger.ainfo(
                    "Compensating Qdrant deletion succeeded",
                    suggestion_id=dto.suggestion_id,
                )
            except Exception as qdrant_cleanup_err:
                await logger.awarning(
                    "Compensating Qdrant deletion failed; staging chunks remain quarantined",
                    suggestion_id=dto.suggestion_id,
                    error=str(qdrant_cleanup_err),
                    exc_info=True,
                )

            # 2. Guarded compensating SQL deletion
            try:
                async with self._uow as comp_uow:
                    await comp_uow.suggestions.delete(dto.suggestion_id)
                    await comp_uow.commit()
                await logger.ainfo(
                    "Compensating SQL deletion succeeded",
                    suggestion_id=dto.suggestion_id,
                )
            except Exception as comp_err:
                await logger.acritical(
                    "Compensating SQL deletion failed! System in inconsistent state for suggestion",
                    suggestion_id=dto.suggestion_id,
                    error=str(comp_err),
                    exc_info=True,
                )

            # Re-raise original Qdrant exception so caller gets accurate root cause
            raise qdrant_err

        await logger.ainfo(
            "Suggestion ingested successfully",
            suggestion_id=dto.suggestion_id,
            chunks_count=len(chunks),
        )

        return IngestSuggestionResponseDTO(
            suggestion_id=dto.suggestion_id,
            chunks_count=len(chunks),
            status="CREATED",
        )


__all__ = ["IngestSuggestionUseCase"]
