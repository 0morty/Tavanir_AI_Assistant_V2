from __future__ import annotations

import asyncio
from typing import Final

import structlog

from src.application.dtos import (
    AnalyzeSuggestionDTO,
    AnalyzeSuggestionResponse,
    ContextBuilderResult,
    CurrentSuggestionInput,
    GenerationInput,
    RerankCandidate,
    SimilarSuggestionInput,
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
    ISuggestionPromptPreparer,
    ITextNormalizer,
    IUnitOfWork,
)
from src.application.services.max_passage_pooler import (
    PooledSuggestionCandidate,
    pool_and_partition_candidates,
)
from src.domain.entities import (
    SparseVector,
    Suggestion,
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


def _build_empty_response() -> AnalyzeSuggestionResponse:
    """Creates a standardized empty response with zero-candidate diagnostic placeholder and empty partition lists."""
    return AnalyzeSuggestionResponse(
        analysis=_build_placeholder_analysis(total_candidates=0),
        similar_executed_ids=[],
        similar_approved_ids=[],
        similar_pending_ids=[],
        similar_rejected_ids=[],
        similar_not_accepted_ids=[],
        applied_statute_ids=[],
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
    12. Prompt Preparation & Response Assembly: Token-budget prompt preparation and structured response.
    """

    def __init__(
        self,
        normalizer: ITextNormalizer,
        embedding_service: IHybridEmbeddingService,
        vector_repo: ISuggestionVectorRepository,
        reranker: IReranker,
        uow: IUnitOfWork,
        prompt_preparer: ISuggestionPromptPreparer,
        solution_global_limit: int = 40,
        problem_global_limit: int = 25,
        title_global_limit: int = 15,
        positive_probe_limit: int = 15,
        pending_probe_limit: int = 10,
        top_n_per_status: int = 3,
        min_score_threshold: float | None = 0.0,
        max_prompt_tokens: int = 4096,
    ) -> None:
        if prompt_preparer is None:
            raise TypeError("prompt_preparer must not be None.")
        if max_prompt_tokens <= 0:
            raise ValueError("max_prompt_tokens must be positive.")
        self._normalizer = normalizer
        self._embedding_service = embedding_service
        self._vector_repo = vector_repo
        self._reranker = reranker
        self._uow = uow
        self._prompt_preparer = prompt_preparer
        self._solution_global_limit = solution_global_limit
        self._problem_global_limit = problem_global_limit
        self._title_global_limit = title_global_limit
        self._positive_probe_limit = positive_probe_limit
        self._pending_probe_limit = pending_probe_limit
        self._top_n_per_status = top_n_per_status
        self._min_score_threshold = min_score_threshold
        self._max_prompt_tokens = max_prompt_tokens

    async def execute(self, dto: AnalyzeSuggestionDTO) -> AnalyzeSuggestionResponse:
        # Step 1: Enforce domain invariants upfront
        SuggestionContent(
            title=dto.title,
            problem=dto.problem,
            solution=dto.solution,
        )

        # Step 2: Asynchronously normalize Persian fields
        (
            norm_title,
            norm_problem,
            norm_solution,
            norm_context,
        ) = await self._normalize_inputs(dto)

        # Step 3: Field Query Synthesis
        title_q, problem_q, solution_q, full_q = self._synthesize_queries(
            norm_title=norm_title,
            norm_problem=norm_problem,
            norm_solution=norm_solution,
            norm_context=norm_context,
        )

        # Step 4 & 5: Tri-Track Hybrid Retrieval (5 concurrent vector queries)
        raw_hits = await self._retrieve_tri_track_hits(
            title_query=title_q,
            problem_query=problem_q,
            solution_query=solution_q,
        )

        # Step 6: Zero-Hits Short-Circuit Guard
        if not raw_hits:
            await logger.ainfo("suggestion_analysis_zero_vector_hits_short_circuit")
            return _build_empty_response()

        # Step 7 & 8: Deduplicate chunks and format rerank candidates
        unique_chunks = self._deduplicate_chunks(raw_hits)
        rerank_candidates = self._prepare_rerank_candidates(unique_chunks)

        # Step 9: Cross-Encoder Reranking with degraded fallback mode
        scored_chunks, is_fallback_mode = await self._rerank_candidates(
            full_query=full_q,
            rerank_candidates=rerank_candidates,
            unique_chunks=unique_chunks,
        )

        # Step 10: Max-Passage (MaxP) Pooling & Status Slicing
        partition_map = pool_and_partition_candidates(
            scored_chunks,
            top_n_per_status=self._top_n_per_status,
            min_score_threshold=self._min_score_threshold,
            is_fallback_mode=is_fallback_mode,
        )

        # Step 11: PostgreSQL Master Entity Hydration & Order Reconstruction
        all_winning_candidates: list[PooledSuggestionCandidate] = []
        for status in SuggestionStatus:
            all_winning_candidates.extend(partition_map[status])

        all_winning_ids = [c.suggestion_id for c in all_winning_candidates]
        hydrated_map = await self._hydrate_master_entities(all_winning_ids)

        active_partitions = self._filter_active_status_partitions(
            partition_map=partition_map,
            hydrated_map=hydrated_map,
        )

        similar_executed_ids = active_partitions[SuggestionStatus.EXECUTED]
        similar_approved_ids = active_partitions[SuggestionStatus.APPROVED]
        similar_pending_ids = active_partitions[SuggestionStatus.PENDING]
        similar_rejected_ids = active_partitions[SuggestionStatus.REJECTED]
        similar_not_accepted_ids = active_partitions[SuggestionStatus.NOT_ACCEPTED]

        total_active_candidates = sum(len(ids) for ids in active_partitions.values())

        # GPU Conservation Guard: short-circuit if 0 active candidates survive
        if total_active_candidates == 0:
            await logger.ainfo(
                "suggestion_analysis_short_circuit_zero_active_candidates",
                retrieved_hits_count=len(all_winning_ids),
            )
            return _build_empty_response()

        # Step 12: Prompt Preparation & Final Response Assembly
        prompt_result = self._prepare_generation_prompt(
            norm_title=norm_title,
            norm_problem=norm_problem,
            norm_solution=norm_solution,
            norm_context=norm_context,
            all_winning_candidates=all_winning_candidates,
            hydrated_map=hydrated_map,
        )

        await logger.ainfo(
            "suggestion_analysis_completed_successfully",
            total_active_candidates=total_active_candidates,
            executed_count=len(similar_executed_ids),
            approved_count=len(similar_approved_ids),
            pending_count=len(similar_pending_ids),
            rejected_count=len(similar_rejected_ids),
            not_accepted_count=len(similar_not_accepted_ids),
            prompt_tokens=prompt_result.total_tokens,
            is_fallback_mode=is_fallback_mode,
        )

        return AnalyzeSuggestionResponse(
            analysis=prompt_result.prompt,
            similar_executed_ids=similar_executed_ids,
            similar_approved_ids=similar_approved_ids,
            similar_pending_ids=similar_pending_ids,
            similar_rejected_ids=similar_rejected_ids,
            similar_not_accepted_ids=similar_not_accepted_ids,
            applied_statute_ids=[],
        )

    # region Helpers
    async def _normalize_inputs(
        self, dto: AnalyzeSuggestionDTO
    ) -> tuple[str, str, str, str | None]:
        """Asynchronously normalizes all Persian text fields from the input DTO."""
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

        return norm_title, norm_problem, norm_solution, norm_context

    @staticmethod
    def _synthesize_queries(
        norm_title: str,
        norm_problem: str,
        norm_solution: str,
        norm_context: str | None,
    ) -> tuple[str, str, str, str]:
        """Constructs field-isolated search queries and composite cross-encoder query."""
        if norm_context:
            title_query = f"حوزه: {norm_context} | عنوان: {norm_title}"
        else:
            title_query = f"عنوان: {norm_title}"

        problem_query = norm_problem
        solution_query = norm_solution
        full_query = f"{title_query}\nمسئله: {norm_problem}\nراهکار: {norm_solution}"

        return title_query, problem_query, solution_query, full_query

    async def _retrieve_tri_track_hits(
        self,
        title_query: str,
        problem_query: str,
        solution_query: str,
    ) -> list[SuggestionSearchResult]:
        """Concurrently generates embeddings and queries 5 Qdrant retrieval tracks."""
        title_emb, problem_emb, solution_emb = await asyncio.gather(
            self._embedding_service.embed_query(title_query),
            self._embedding_service.embed_query(problem_query),
            self._embedding_service.embed_query(solution_query),
        )

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

        return (
            list(t1_sol) + list(t1_prob) + list(t1_title) + list(t2_pos) + list(t3_pend)
        )

    @staticmethod
    def _deduplicate_chunks(
        raw_hits: list[SuggestionSearchResult],
    ) -> list[SuggestionSearchResult]:
        """Deduplicates chunks across tracks by chunk_id, preserving the highest initial score."""
        chunk_registry: dict[str, SuggestionSearchResult] = {}
        for hit in raw_hits:
            cid = hit.chunk.chunk_id
            if cid not in chunk_registry or hit.score > chunk_registry[cid].score:
                chunk_registry[cid] = hit

        unique_chunks = list(chunk_registry.values())
        unique_chunks.sort(key=lambda h: h.score, reverse=True)
        return unique_chunks

    @staticmethod
    def _prepare_rerank_candidates(
        unique_chunks: list[SuggestionSearchResult],
    ) -> list[RerankCandidate]:
        """Applies role prefixes and builds RerankCandidate list with monotonic initial ranks."""
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
        return rerank_candidates

    async def _rerank_candidates(
        self,
        full_query: str,
        rerank_candidates: list[RerankCandidate],
        unique_chunks: list[SuggestionSearchResult],
    ) -> tuple[list[tuple[SuggestionSearchResult, float]], bool]:
        """Executes cross-encoder reranking with graceful fallback to initial retrieval scores on transient errors."""
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

        return scored_chunks, is_fallback_mode

    async def _hydrate_master_entities(
        self,
        suggestion_ids: list[str],
    ) -> dict[str, Suggestion]:
        """Fetches active master suggestion entities from PostgreSQL, excluding soft-deleted records."""
        if not suggestion_ids:
            return {}

        async with self._uow as uow:
            hydrated_records = await uow.suggestions.get_by_ids(
                suggestion_ids, include_deleted=False
            )
            return {r.id: r for r in hydrated_records if not r.is_deleted}

    @staticmethod
    def _filter_active_status_partitions(
        partition_map: dict[SuggestionStatus, list[PooledSuggestionCandidate]],
        hydrated_map: dict[str, Suggestion],
    ) -> dict[SuggestionStatus, list[str]]:
        """Filters partitioned candidates to only active, hydrated master suggestions."""
        return {
            status: [
                cand.suggestion_id
                for cand in partition_map[status]
                if cand.suggestion_id in hydrated_map
            ]
            for status in SuggestionStatus
        }

    def _prepare_generation_prompt(
        self,
        norm_title: str,
        norm_problem: str,
        norm_solution: str,
        norm_context: str | None,
        all_winning_candidates: list[PooledSuggestionCandidate],
        hydrated_map: dict[str, Suggestion],
    ) -> ContextBuilderResult:
        """Sorts active candidates globally by winning score, prepares prompt DTOs, and builds the prompt."""
        active_candidates = [
            c for c in all_winning_candidates if c.suggestion_id in hydrated_map
        ]
        active_candidates.sort(key=lambda c: c.winning_score, reverse=True)

        similar_inputs: list[SimilarSuggestionInput] = []
        for cand in active_candidates:
            entity = hydrated_map[cand.suggestion_id]
            similar_inputs.append(
                SimilarSuggestionInput(
                    id=entity.id,
                    status=entity.evaluation.status,
                    title=entity.content.title,
                    problem=entity.content.problem,
                    solution=entity.content.solution,
                    similarity=float(cand.winning_score),
                    context_title=entity.context_title,
                )
            )

        generation_input = GenerationInput(
            current_suggestion=CurrentSuggestionInput(
                title=norm_title,
                problem=norm_problem,
                solution=norm_solution,
                context_title=norm_context,
            ),
            similar_suggestions=similar_inputs,
        )

        return self._prompt_preparer.prepare(
            generation_input,
            max_prompt_tokens=self._max_prompt_tokens,
        )

    # endregion


__all__: Final[list[str]] = ["AnalyzeSuggestionUseCase"]
