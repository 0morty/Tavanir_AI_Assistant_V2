import asyncio

import structlog

from src.application.dtos import CreateSuggestionDTO, IngestSuggestionResponseDTO
from src.application.interfaces.i_dense_embedder import IDenseEmbedder
from src.application.interfaces.i_sparse_embedder import ISparseEmbedder
from src.application.interfaces.i_text_normalizer import ITextNormalizer
from src.application.services.suggestion_normalizer import normalize_suggestion
from src.domain.entities import (
    CommitteeEvaluation,
    ShamsiDate,
    Suggestion,
    SuggestionContent,
)
from src.domain.exceptions import (
    SuggestionAlreadyExistsError,
    SuggestionChunkingError,
)
from src.domain.interfaces import (
    ISuggestionChunker,
    ISuggestionVectorRepository,
    IUnitOfWork,
)

logger = structlog.get_logger(__name__)


class IngestSuggestionUseCase:
    """
    Orchestrates the synchronous ingestion pipeline for employee suggestions (ADR-001, ADR-002).

    Pipeline Flow:
    1. Pre-check idempotency/conflict via short-lived UoW (raises SuggestionAlreadyExistsError).
    2. Construct domain entity & validate domain invariants (raises InvalidSuggestionContentError).
    3. Normalize Persian text across all fields.
    4. Decompose suggestion into field-isolated child chunks (TITLE, PROBLEM, SOLUTION, EVALUATION).
    5. Compute dense (semantic) and sparse (lexical BM25) embeddings concurrently in-memory.
    6. Pattern A Persistence:
       a. Fast PostgreSQL persistence via short-lived UoW.
       b. Vector store upsert into Qdrant outside SQL transaction.
       c. If Qdrant fails, execute guarded compensating SQL deletion to maintain dual-write consistency.
    """

    def __init__(
        self,
        uow: IUnitOfWork,
        normalizer: ITextNormalizer,
        chunker: ISuggestionChunker,
        dense_embedder: IDenseEmbedder,
        sparse_embedder: ISparseEmbedder,
        vector_repo: ISuggestionVectorRepository,
    ) -> None:
        self._uow = uow
        self._normalizer = normalizer
        self._chunker = chunker
        self._dense_embedder = dense_embedder
        self._sparse_embedder = sparse_embedder
        self._vector_repo = vector_repo

    async def execute(self, dto: CreateSuggestionDTO) -> IngestSuggestionResponseDTO:
        # Step 1: Pre-check duplicate existence
        async with self._uow as uow:
            existing = await uow.suggestions.get_by_id(dto.suggestion_id)
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
            scrutiny=dto.scrutiny,
            description=dto.description,
        )
        date = ShamsiDate(dto.shamsi_date) if dto.shamsi_date else None

        raw_suggestion = Suggestion(
            id=dto.suggestion_id,
            content=content,
            evaluation=evaluation,
            date=date,
            context_title=dto.context_title,
        )

        # Step 3: Normalize Persian text
        normalized_suggestion = normalize_suggestion(raw_suggestion, self._normalizer)

        # Step 4: Decompose into field-isolated chunks
        chunks = await self._chunker.chunk(normalized_suggestion)
        if not chunks:
            raise SuggestionChunkingError(
                f"Chunking produced 0 chunks for suggestion '{dto.suggestion_id}'."
            )

        # Step 5: Generate dense and sparse embeddings concurrently
        texts = [chunk.content for chunk in chunks]
        dense_vectors, sparse_vectors = await asyncio.gather(
            self._dense_embedder.embed_documents(texts),
            self._sparse_embedder.embed_documents(texts),
        )

        for chunk, dense_vec, sparse_vec in zip(
            chunks, dense_vectors, sparse_vectors, strict=True
        ):
            chunk.dense_vector = dense_vec
            chunk.sparse_vector = sparse_vec

        # Step 6: Pattern A Persistence
        # 6a. Persist to PostgreSQL via short-lived UoW
        async with self._uow as uow:
            await uow.suggestions.save(normalized_suggestion)
            await uow.commit()

        # 6b. Upsert chunks into Qdrant outside SQL transaction
        try:
            await self._vector_repo.upsert_chunks_batch(chunks)
        except Exception as qdrant_err:
            await logger.aerror(
                "Qdrant upsert failed during suggestion ingestion; executing compensating SQL deletion",
                suggestion_id=dto.suggestion_id,
                error=str(qdrant_err),
                exc_info=True,
            )
            # Guarded compensating deletion
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
