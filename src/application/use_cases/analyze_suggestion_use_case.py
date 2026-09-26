from __future__ import annotations

import asyncio
from typing import Final

import structlog

from src.application.dtos import (
    AnalyzeSuggestionDTO,
    AnalyzeSuggestionResponse,
    RerankCandidate,
)
from src.application.exceptions import (
    RerankerAPIError,
    RerankerConnectionError,
    RerankerInputLimitError,
    RerankerOverloadedError,
    RerankerProtocolError,
)
from src.application.interfaces import (
    IHybridEmbeddingService,
    IReranker,
    ITextNormalizer,
    IUnitOfWork,
)
from src.application.services.max_passage_pooler import (
    pool_and_partition_candidates,
)
from src.domain.entities import (
    SparseVector,
    SuggestionContent,
    SuggestionSearchResult,
)
from src.domain.enums import SuggestionChunkType, SuggestionStatus
from src.domain.interfaces import ISuggestionVectorRepository

logger = structlog.get_logger(__name__)

_ROLE_PREFIX_MAP: Final[dict[SuggestionChunkType, str]] = {
    SuggestionChunkType.SOLUTION: "راهکار پیشنهادی: ",
    SuggestionChunkType.PROBLEM: "مسئله و چالش: ",
    SuggestionChunkType.TITLE: "عنوان: ",
    SuggestionChunkType.EVALUATION: "بررسی کمیته: ",
}


def _build_placeholder_analysis(total_candidates: int) -> str:
    """Diagnostic handoff text documenting successful retrieval and reranking for downstream LLM generation."""
    return (
        "## تحلیل اولیه و سوابق مشابه بازیابی‌شده\n\n"
        "فرآیند بازیابی سه‌مسیره (Tri-Track Hybrid Retrieval) و بازرتبه‌بندی متقاطع (Cross-Encoder) "
        f"با موفقیت انجام شد. تعداد {total_candidates} پیشنهاد با بالاترین تشابه مفهومی و ساختاری "
        "در دسته‌بندی‌های پنج‌گانه سازمانی استخراج گردیدند."
    )


class AnalyzeSuggestionUseCase:
    """
    Orchestrates the Suggestion Analysis pipeline in Tavanir AI Assistant V2 (ADR-001, ADR-002).

    Pipeline Flow:
    1. Input Validation: Enforce domain invariants via SuggestionContent.
    2. Text Normalization: Asynchronously normalize Persian fields.
    3. Query Synthesis: Create field-isolated title, problem, and solution queries.
    4. Multi-Field Hybrid Embedding: Concurrently generate Dense + Sparse representations.
    5. Tri-Track Hybrid Retrieval: Run 5 concurrent Qdrant queries via asyncio.gather().
    6. Zero-Hits Short-Circuit: If all 5 tracks return 0 hits, early exit with empty results.
    7. In-Memory Registry: Deduplicate chunks across tracks by chunk_id, preserving max(score).
    8. Candidate Preparation: Apply role prefixes, sort globally by retrieval score, assign monotonic ranks.
    9. Cross-Encoder Reranking: Rerank full query against unique candidate chunks with degraded fallback to RRF.
    10. Max-Passage (MaxP) Pooling: Select winning chunks, gate thresholds, slice top-N per status partition.
    11. PostgreSQL Hydration: Validate active master entities and reconstruct descending score order.
    12. Response Assembly: Construct AnalyzeSuggestionResponse with status IDs and handoff placeholders.
    """

    def __init__(
        self,
        normalizer: ITextNormalizer,
        embedding_service: IHybridEmbeddingService,
        vector_repo: ISuggestionVectorRepository,
        reranker: IReranker,
        uow: IUnitOfWork,
        solution_global_limit: int = 40,
        problem_global_limit: int = 25,
        title_global_limit: int = 15,
        positive_probe_limit: int = 15,
        pending_probe_limit: int = 10,
        top_n_per_status: int = 3,
        min_score_threshold: float | None = 0.0,
    ) -> None:
        self._normalizer = normalizer
        self._embedding_service = embedding_service
        self._vector_repo = vector_repo
        self._reranker = reranker
        self._uow = uow
        self._solution_global_limit = solution_global_limit
        self._problem_global_limit = problem_global_limit
        self._title_global_limit = title_global_limit
        self._positive_probe_limit = positive_probe_limit
        self._pending_probe_limit = pending_probe_limit
        self._top_n_per_status = top_n_per_status
        self._min_score_threshold = min_score_threshold

    async def execute(self, dto: AnalyzeSuggestionDTO) -> AnalyzeSuggestionResponse:
        # Step 1: Validate domain invariants (raises InvalidSuggestionContentError on noise or < 5 chars)
        SuggestionContent(
            title=dto.title,
            problem=dto.problem,
            solution=dto.solution,
        )

        # Step 2: Asynchronous Persian text normalization
        norm_context: str | None = None
        if dto.context_title and dto.context_title.strip():
            raw_norm_context = await self._normalizer.normalize_async(
                dto.context_title.strip()
            )
            if raw_norm_context and raw_norm_context.strip():
                norm_context = raw_norm_context.strip()

        norm_title = (await self._normalizer.normalize_async(dto.title)).strip()
        norm_problem = (await self._normalizer.normalize_async(dto.problem)).strip()
        norm_solution = (await self._normalizer.normalize_async(dto.solution)).strip()

        # Step 3: Field Query Synthesis
        if norm_context:
            title_query = f"حوزه: {norm_context} | عنوان: {norm_title}"
        else:
            title_query = f"عنوان: {norm_title}"

        problem_query = norm_problem
        solution_query = norm_solution

        # Step 4: Concurrent Multi-Field Hybrid Embedding
        title_emb, problem_emb, solution_emb = await asyncio.gather(
            self._embedding_service.embed_query(title_query),
            self._embedding_service.embed_query(problem_query),
            self._embedding_service.embed_query(solution_query),
        )

        # Step 5: Tri-Track Hybrid Qdrant Retrieval (5 Concurrent Queries)
        empty_sparse = SparseVector.from_dict({})
        t1_sol, t1_prob, t1_title, t2_pos, t3_pend = await asyncio.gather(
            self._vector_repo.search_suggestions(
                dense_vector=solution_emb.dense_vector,
                sparse_vector=solution_emb.sparse_vector or empty_sparse,
                chunk_types=[SuggestionChunkType.SOLUTION],
                statuses=None,
                limit=self._solution_global_limit,
            ),
            self._vector_repo.search_suggestions(
                dense_vector=problem_emb.dense_vector,
                sparse_vector=problem_emb.sparse_vector or empty_sparse,
                chunk_types=[SuggestionChunkType.PROBLEM],
                statuses=None,
                limit=self._problem_global_limit,
            ),
            self._vector_repo.search_suggestions(
                dense_vector=title_emb.dense_vector,
                sparse_vector=title_emb.sparse_vector or empty_sparse,
                chunk_types=[SuggestionChunkType.TITLE],
                statuses=None,
                limit=self._title_global_limit,
            ),
            self._vector_repo.search_suggestions(
                dense_vector=solution_emb.dense_vector,
                sparse_vector=solution_emb.sparse_vector or empty_sparse,
                chunk_types=[SuggestionChunkType.SOLUTION],
                statuses=[SuggestionStatus.EXECUTED, SuggestionStatus.APPROVED],
                limit=self._positive_probe_limit,
            ),
            self._vector_repo.search_suggestions(
                dense_vector=solution_emb.dense_vector,
                sparse_vector=solution_emb.sparse_vector or empty_sparse,
                chunk_types=[SuggestionChunkType.SOLUTION],
                statuses=[SuggestionStatus.PENDING],
                limit=self._pending_probe_limit,
            ),
        )

        # Step 6: Zero-Hits Short-Circuit Guard
        all_raw_hits: list[SuggestionSearchResult] = (
            list(t1_sol) + list(t1_prob) + list(t1_title) + list(t2_pos) + list(t3_pend)
        )
        if not all_raw_hits:
            await logger.ainfo("suggestion_analysis_zero_vector_hits_short_circuit")
            return AnalyzeSuggestionResponse(
                analysis=_build_placeholder_analysis(total_candidates=0),
                similar_executed_ids=[],
                similar_approved_ids=[],
                similar_pending_ids=[],
                similar_rejected_ids=[],
                similar_not_accepted_ids=[],
                applied_statute_ids=[],
            )

        # Step 7: Candidate In-Memory Registry (Deduplicate across tracks, taking max initial score)
        chunk_registry: dict[str, SuggestionSearchResult] = {}
        for hit in all_raw_hits:
            cid = hit.chunk.chunk_id
            if cid not in chunk_registry or hit.score > chunk_registry[cid].score:
                chunk_registry[cid] = hit

        unique_chunks = list(chunk_registry.values())

        # Step 8: Candidate Formatting & Monotonic Retrieval Rank Assignment
        unique_chunks.sort(key=lambda h: h.score, reverse=True)

        rerank_candidates: list[RerankCandidate] = []
        for idx, hit in enumerate(unique_chunks, start=1):
            prefix = _ROLE_PREFIX_MAP.get(hit.chunk.metadata.chunk_type, "")
            formatted_text = f"{prefix}{hit.chunk.content}".strip()
            rerank_candidates.append(
                RerankCandidate(
                    candidate_id=hit.chunk.chunk_id,
                    normalized_text=formatted_text,
                    retrieval_rank=idx,
                    retrieval_score=hit.score,
                )
            )

        # Step 9: Cross-Encoder Reranking with Degraded Fallback Mode
        full_query = f"{title_query}\nمسئله: {norm_problem}\nراهکار: {norm_solution}"
        is_fallback_mode = False
        scored_chunks: list[tuple[SuggestionSearchResult, float]] = []

        try:
            reranked_results = await self._reranker.rerank(
                normalized_query=full_query,
                candidates=rerank_candidates,
            )
            score_by_chunk_id = {
                r.candidate_id: r.rerank_score for r in reranked_results
            }
            for hit in unique_chunks:
                cid = hit.chunk.chunk_id
                score = score_by_chunk_id.get(cid, hit.score)
                scored_chunks.append((hit, score))
        except (
            RerankerConnectionError,
            RerankerOverloadedError,
            RerankerAPIError,
            RerankerProtocolError,
            RerankerInputLimitError,
        ) as rerank_err:
            await logger.awarning(
                "cross_encoder_rerank_failed_falling_back_to_rrf",
                error=str(rerank_err),
                candidates_count=len(rerank_candidates),
                exc_info=True,
            )
            is_fallback_mode = True
            scored_chunks = [(hit, hit.score) for hit in unique_chunks]

        # Step 10: Max-Passage (MaxP) Pooling & Status Slicing
        partition_map = pool_and_partition_candidates(
            scored_chunks,
            top_n_per_status=self._top_n_per_status,
            min_score_threshold=self._min_score_threshold,
            is_fallback_mode=is_fallback_mode,
        )

        # Step 11: PostgreSQL Master Entity Hydration & Order Reconstruction
        all_winning_ids: list[str] = []
        for status in SuggestionStatus:
            for cand in partition_map[status]:
                all_winning_ids.append(cand.suggestion_id)

        valid_active_ids: set[str] = set()
        if all_winning_ids:
            async with self._uow as uow:
                hydrated_records = await uow.suggestions.get_by_ids(
                    all_winning_ids, include_deleted=False
                )
                valid_active_ids = {r.id for r in hydrated_records if not r.is_deleted}

        def _filter_active(status: SuggestionStatus) -> list[str]:
            return [
                cand.suggestion_id
                for cand in partition_map[status]
                if cand.suggestion_id in valid_active_ids
            ]

        similar_executed_ids = _filter_active(SuggestionStatus.EXECUTED)
        similar_approved_ids = _filter_active(SuggestionStatus.APPROVED)
        similar_pending_ids = _filter_active(SuggestionStatus.PENDING)
        similar_rejected_ids = _filter_active(SuggestionStatus.REJECTED)
        similar_not_accepted_ids = _filter_active(SuggestionStatus.NOT_ACCEPTED)

        # Step 12: Assemble Structured Response
        total_candidates = (
            len(similar_executed_ids)
            + len(similar_approved_ids)
            + len(similar_pending_ids)
            + len(similar_rejected_ids)
            + len(similar_not_accepted_ids)
        )

        await logger.ainfo(
            "suggestion_analysis_completed_successfully",
            total_active_candidates=total_candidates,
            executed_count=len(similar_executed_ids),
            approved_count=len(similar_approved_ids),
            pending_count=len(similar_pending_ids),
            rejected_count=len(similar_rejected_ids),
            not_accepted_count=len(similar_not_accepted_ids),
            is_fallback_mode=is_fallback_mode,
        )

        return AnalyzeSuggestionResponse(
            analysis=_build_placeholder_analysis(total_candidates=total_candidates),
            similar_executed_ids=similar_executed_ids,
            similar_approved_ids=similar_approved_ids,
            similar_pending_ids=similar_pending_ids,
            similar_rejected_ids=similar_rejected_ids,
            similar_not_accepted_ids=similar_not_accepted_ids,
            applied_statute_ids=[],
        )


__all__: Final[list[str]] = ["AnalyzeSuggestionUseCase"]
