from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.application.use_cases.analyze_suggestion_use_case import (
    AnalyzeSuggestionUseCase,
)
from src.containers import Container

from src.application.dtos import (
    AnalyzeSuggestionDTO,
    AnalyzeSuggestionResponse,
    GenerationResult,
    SimilarSuggestionInput,
    GenerationInput,
    RerankCandidate,
    RerankedCandidate,
)
from src.application.exceptions import (
    InsufficientEvidenceBudgetError,
    LLMConnectionError,
    LLMOutputParseError,
    PromptBudgetExceededError,
    RerankerAPIError,
    RerankerConnectionError,
    RerankerOverloadedError,
    RerankerProtocolError,
    RerankerValidationError,
)
from src.application.interfaces import (
    IHybridEmbeddingService,
    IReranker,
    IGenerateSuggestionUseCase,
    ITextNormalizer,
    IUnitOfWork,
)
from src.domain.entities import (
    Chunk,
    CommitteeEvaluation,
    DenseVector,
    QueryEmbedding,
    SparseVector,
    Suggestion,
    SuggestionChunkMetadata,
    SuggestionContent,
    SuggestionSearchResult,
)
from src.domain.enums import SuggestionChunkType, SuggestionStatus
from src.domain.exceptions import InvalidSuggestionContentError
from src.domain.interfaces import ISuggestionRepository, ISuggestionVectorRepository


def _make_chunk(
    chunk_id: str,
    parent_id: str,
    content: str,
    chunk_type: SuggestionChunkType,
    status: SuggestionStatus,
) -> Chunk[SuggestionChunkMetadata]:
    return Chunk(
        chunk_id=chunk_id,
        parent_id=parent_id,
        content=content,
        metadata=SuggestionChunkMetadata(chunk_type=chunk_type, status=status),
    )


def _make_search_result(
    chunk_id: str,
    parent_id: str,
    content: str,
    chunk_type: SuggestionChunkType,
    status: SuggestionStatus,
    score: float,
) -> SuggestionSearchResult:
    return SuggestionSearchResult(
        chunk=_make_chunk(chunk_id, parent_id, content, chunk_type, status),
        score=score,
    )


def _make_suggestion(
    suggestion_id: str,
    status: SuggestionStatus,
    is_deleted: bool = False,
) -> Suggestion:
    return Suggestion(
        id=suggestion_id,
        content=SuggestionContent(
            title=f"عنوان پیشنهاد {suggestion_id}",
            problem="چالش سیستم",
            solution="راهکار بهبود",
        ),
        evaluation=CommitteeEvaluation(status=status),
        is_deleted=is_deleted,
    )


class FakeUoW(IUnitOfWork):
    def __init__(self, suggestion_repo: ISuggestionRepository):
        self._suggestions = suggestion_repo
        self.committed = False
        self.rolled_back = False

    @property
    def suggestions(self) -> ISuggestionRepository:
        return self._suggestions

    @property
    def checkpoints(self) -> AsyncMock:
        return AsyncMock()

    @property
    def skipped_suggestions(self) -> AsyncMock:
        return AsyncMock()

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def try_acquire_advisory_lock(self, lock_key: int) -> bool:
        return True


@pytest.fixture
def mock_normalizer() -> ITextNormalizer:
    mock = MagicMock(spec=ITextNormalizer)
    mock.normalize_async = AsyncMock(side_effect=lambda text: f"normalized_{text}")
    return mock


@pytest.fixture
def mock_embedding_service() -> IHybridEmbeddingService:
    mock = MagicMock(spec=IHybridEmbeddingService)
    dense: DenseVector = [0.1] * 1024
    sparse = SparseVector.from_dict({1: 0.5, 2: 0.8})

    async def _embed_query(query: str) -> QueryEmbedding:
        return QueryEmbedding(text=query, dense_vector=dense, sparse_vector=sparse)

    mock.embed_query = AsyncMock(side_effect=_embed_query)
    return mock


@pytest.fixture
def mock_vector_repo() -> ISuggestionVectorRepository:
    mock = MagicMock(spec=ISuggestionVectorRepository)
    mock.search_suggestions = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def mock_reranker() -> IReranker:
    mock = MagicMock(spec=IReranker)
    mock.rerank = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def mock_suggestion_repo() -> ISuggestionRepository:
    mock = MagicMock(spec=ISuggestionRepository)
    mock.get_by_ids = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def mock_uow(mock_suggestion_repo: ISuggestionRepository) -> IUnitOfWork:
    return FakeUoW(mock_suggestion_repo)


@pytest.fixture
def mock_prompt_preparer(mock_generator: IGenerateSuggestionUseCase) -> IGenerateSuggestionUseCase:
    return mock_generator


@pytest.fixture
def mock_generator() -> IGenerateSuggestionUseCase:
    mock = MagicMock(spec=IGenerateSuggestionUseCase)
    mock.execute = AsyncMock(
        return_value=GenerationResult(
            answer="## PREPARED PROMPT TEXT",
            citations=[],
            uncertainty=None,
        )
    )
    return mock


@pytest.fixture
def valid_dto() -> AnalyzeSuggestionDTO:
    return AnalyzeSuggestionDTO(
        title="کاهش تلفات شبکه توزیع",
        problem="تلفات بالا در خطوط فشار ضعیف روستایی وجود دارد",
        solution="نصب ترانسفورماتورهای کم‌ظرفیت و نزدیک به بار مصرفی",
        context_title="توزیع نیروی برق",
    )


@pytest.mark.asyncio
async def test_analyze_suggestion_full_tri_track_retrieval_success(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    # Setup retrieval hits with collision across Track 1 and Track 2
    # Track 1 Solution: chunk-1 (score 0.80)
    hit_1 = _make_search_result(
        "chunk-1",
        "SUG-001",
        "نصب خازن",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.80,
    )
    # Track 1 Problem: chunk-2 (score 0.70)
    hit_2 = _make_search_result(
        "chunk-2",
        "SUG-001",
        "افت ولتاژ",
        SuggestionChunkType.PROBLEM,
        SuggestionStatus.EXECUTED,
        0.70,
    )
    # Track 1 Title: chunk-3 (score 0.60)
    hit_3 = _make_search_result(
        "chunk-3",
        "SUG-002",
        "اصلاح شبکه",
        SuggestionChunkType.TITLE,
        SuggestionStatus.APPROVED,
        0.60,
    )
    # Track 2 Positive Precedent: chunk-1 again with higher score (0.88)
    hit_1_higher = _make_search_result(
        "chunk-1",
        "SUG-001",
        "نصب خازن",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.88,
    )
    # Track 3 Pending Precedent: chunk-4 (score 0.75)
    hit_4 = _make_search_result(
        "chunk-4",
        "SUG-003",
        "کابل خودنگهدار",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.PENDING,
        0.75,
    )

    call_count = 0

    async def _mock_search(*args, **kwargs) -> list[SuggestionSearchResult]:
        nonlocal call_count
        call_count += 1
        # Track 1 Solution
        if (
            kwargs.get("chunk_types") == [SuggestionChunkType.SOLUTION]
            and kwargs.get("statuses") is None
        ):
            return [hit_1]
        # Track 1 Problem
        if kwargs.get("chunk_types") == [SuggestionChunkType.PROBLEM]:
            return [hit_2]
        # Track 1 Title
        if kwargs.get("chunk_types") == [SuggestionChunkType.TITLE]:
            return [hit_3]
        # Track 2 Positive
        if kwargs.get("statuses") == [SuggestionChunkType.SOLUTION] or kwargs.get(
            "statuses"
        ) == [
            SuggestionStatus.EXECUTED,
            SuggestionStatus.APPROVED,
        ]:
            return [hit_1_higher]
        # Track 3 Pending
        if kwargs.get("statuses") == [SuggestionStatus.PENDING]:
            return [hit_4]
        return []

    mock_vector_repo.search_suggestions = AsyncMock(side_effect=_mock_search)

    # Mock Reranker response
    async def _mock_rerank(
        normalized_query: str,
        candidates: list[RerankCandidate],
        **kwargs,
    ) -> list[RerankedCandidate]:
        reranked = []
        for idx, cand in enumerate(candidates, start=1):
            score = (
                0.95
                if cand.candidate_id == "chunk-1"
                else (0.85 if cand.candidate_id == "chunk-4" else 0.75)
            )
            reranked.append(
                RerankedCandidate(
                    candidate_id=cand.candidate_id,
                    retrieval_rank=cand.retrieval_rank,
                    retrieval_score=cand.retrieval_score,
                    rerank_score=score,
                    reranked_rank=idx,
                )
            )
        return reranked

    mock_reranker.rerank = AsyncMock(side_effect=_mock_rerank)

    # Mock PostgreSQL hydration returning shuffled records
    mock_uow.suggestions.get_by_ids = AsyncMock(
        return_value=[
            _make_suggestion("SUG-003", SuggestionStatus.PENDING),
            _make_suggestion("SUG-002", SuggestionStatus.APPROVED),
            _make_suggestion("SUG-001", SuggestionStatus.EXECUTED),
        ]
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
        solution_global_limit=40,
        problem_global_limit=25,
        title_global_limit=15,
        positive_probe_limit=15,
        pending_probe_limit=10,
        top_n_per_status=3,
        min_score_threshold=0.0,
    )

    result = await use_case.execute(valid_dto)

    # Assert 5 parallel searches were triggered
    assert mock_vector_repo.search_suggestions.call_count == 5

    # Assert reranker was called once with deduplicated chunks
    assert mock_reranker.rerank.call_count == 1
    call_args = mock_reranker.rerank.call_args
    passed_candidates: list[RerankCandidate] = (
        call_args.kwargs.get("candidates") or call_args[0][1]
    )
    candidate_ids = [c.candidate_id for c in passed_candidates]
    assert len(candidate_ids) == len(set(candidate_ids))
    assert set(candidate_ids) == {"chunk-1", "chunk-2", "chunk-3", "chunk-4"}

    # Assert chunk-1 kept the higher score from Track 2 (0.88 instead of 0.80)
    chunk_1_cand = next(c for c in passed_candidates if c.candidate_id == "chunk-1")
    assert chunk_1_cand.retrieval_score == 0.88

    # Assert role prefixes were applied to candidate text
    assert chunk_1_cand.normalized_text.startswith("راهکار پیشنهادی: ")
    chunk_2_cand = next(c for c in passed_candidates if c.candidate_id == "chunk-2")
    assert chunk_2_cand.normalized_text.startswith("مسئله و چالش: ")
    chunk_3_cand = next(c for c in passed_candidates if c.candidate_id == "chunk-3")
    assert chunk_3_cand.normalized_text.startswith("عنوان: ")

    # Assert response contains correctly partitioned suggestions
    assert result.similar_executed_ids == ["SUG-001"]
    assert result.similar_pending_ids == ["SUG-003"]
    assert result.similar_approved_ids == ["SUG-002"]
    assert result.similar_rejected_ids == []
    assert result.similar_not_accepted_ids == []
    assert result.applied_statute_ids == []
    assert result.analysis == "## PREPARED PROMPT TEXT"
    mock_generator.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_analyze_suggestion_zero_hits_short_circuits(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    # All 5 tracks return empty
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[])

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    result = await use_case.execute(valid_dto)

    # 5 searches were executed
    assert mock_vector_repo.search_suggestions.call_count == 5
    # Reranker, UoW, and prompt preparer were NEVER called
    cast(AsyncMock, mock_reranker.rerank).assert_not_called()
    cast(AsyncMock, mock_uow.suggestions.get_by_ids).assert_not_called()
    mock_generator.execute.assert_not_awaited()

    # Empty lists returned with placeholder analysis
    assert result.similar_executed_ids == []
    assert result.similar_approved_ids == []
    assert result.similar_pending_ids == []
    assert result.similar_rejected_ids == []
    assert result.similar_not_accepted_ids == []
    assert result.applied_statute_ids == []
    assert "تعداد 0 پیشنهاد" in result.analysis


@pytest.mark.asyncio
async def test_analyze_suggestion_reranker_connection_error_fallback(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    hit = _make_search_result(
        "chunk-1",
        "SUG-001",
        "راهکار پیشنهادی",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.85,
    )
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit])

    # Reranker fails with connection error
    mock_reranker.rerank = AsyncMock(
        side_effect=RerankerConnectionError("TEI container unreachable")
    )

    mock_uow.suggestions.get_by_ids = AsyncMock(
        return_value=[_make_suggestion("SUG-001", SuggestionStatus.EXECUTED)]
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    # Should not raise; degrades gracefully to RRF
    result = await use_case.execute(valid_dto)

    assert result.similar_executed_ids == ["SUG-001"]
    mock_uow.suggestions.get_by_ids.assert_called_once_with(
        ["SUG-001"], include_deleted=False
    )
    mock_generator.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_analyze_suggestion_reranker_overloaded_fallback(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    hit = _make_search_result(
        "chunk-1",
        "SUG-001",
        "راهکار",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.85,
    )
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit])
    mock_reranker.rerank = AsyncMock(
        side_effect=RerankerOverloadedError("HTTP 429 concurrency limit")
    )
    mock_uow.suggestions.get_by_ids = AsyncMock(
        return_value=[_make_suggestion("SUG-001", SuggestionStatus.EXECUTED)]
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    result = await use_case.execute(valid_dto)
    assert result.similar_executed_ids == ["SUG-001"]
    mock_generator.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_analyze_suggestion_reranker_api_error_fallback(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    hit = _make_search_result(
        "chunk-1",
        "SUG-001",
        "راهکار",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.85,
    )
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit])
    mock_reranker.rerank = AsyncMock(
        side_effect=RerankerAPIError("HTTP 500 internal server error")
    )
    mock_uow.suggestions.get_by_ids = AsyncMock(
        return_value=[_make_suggestion("SUG-001", SuggestionStatus.EXECUTED)]
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    result = await use_case.execute(valid_dto)
    assert result.similar_executed_ids == ["SUG-001"]
    mock_generator.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_analyze_suggestion_reranker_validation_error_propagates(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    hit = _make_search_result(
        "chunk-1",
        "SUG-001",
        "راهکار",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.85,
    )
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit])
    mock_reranker.rerank = AsyncMock(
        side_effect=RerankerValidationError("Invalid payload format")
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    with pytest.raises(RerankerValidationError, match="Invalid payload format"):
        await use_case.execute(valid_dto)

    mock_generator.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_analyze_suggestion_filters_soft_deleted_and_preserves_score_order(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    # 3 hits across executed suggestions
    hit_1 = _make_search_result(
        "c-1",
        "SUG-100",
        "sol 1",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.90,
    )
    hit_2 = _make_search_result(
        "c-2",
        "SUG-200",
        "sol 2",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.80,
    )
    hit_3 = _make_search_result(
        "c-3",
        "SUG-300",
        "sol 3",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.70,
    )

    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit_1, hit_2, hit_3])

    # Reranker assigns scores: SUG-100 (0.95), SUG-200 (0.85), SUG-300 (0.75)
    mock_reranker.rerank = AsyncMock(
        return_value=[
            RerankedCandidate(
                candidate_id="c-1",
                retrieval_rank=1,
                retrieval_score=0.90,
                rerank_score=0.95,
                reranked_rank=1,
            ),
            RerankedCandidate(
                candidate_id="c-2",
                retrieval_rank=2,
                retrieval_score=0.80,
                rerank_score=0.85,
                reranked_rank=2,
            ),
            RerankedCandidate(
                candidate_id="c-3",
                retrieval_rank=3,
                retrieval_score=0.70,
                rerank_score=0.75,
                reranked_rank=3,
            ),
        ]
    )

    # PostgreSQL returns SUG-200 as is_deleted=True, and returns records shuffled [SUG-300, SUG-100]
    mock_uow.suggestions.get_by_ids = AsyncMock(
        return_value=[
            _make_suggestion("SUG-300", SuggestionStatus.EXECUTED, is_deleted=False),
            _make_suggestion(
                "SUG-200", SuggestionStatus.EXECUTED, is_deleted=True
            ),  # soft-deleted!
            _make_suggestion("SUG-100", SuggestionStatus.EXECUTED, is_deleted=False),
        ]
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    result = await use_case.execute(valid_dto)

    # SUG-200 was filtered out.
    # Score order must be preserved: SUG-100 (0.95) must precede SUG-300 (0.75), despite SQL returning SUG-300 first!
    assert result.similar_executed_ids == ["SUG-100", "SUG-300"]
    mock_generator.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_analyze_suggestion_validates_domain_noise_and_short_content(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
) -> None:
    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    # Noise placeholder in solution
    noise_dto = AnalyzeSuggestionDTO(
        title="عنوان پیشنهاد معتبر",
        problem="چالش سیستم توزیع برق",
        solution="ندارد",  # noise!
    )

    with pytest.raises(InvalidSuggestionContentError):
        await use_case.execute(noise_dto)

    # Short content (< 5 chars)
    short_dto = AnalyzeSuggestionDTO(
        title="تست",  # < 5 chars
        problem="چالش سیستم توزیع برق",
        solution="راهکار پیشنهادی جامع",
    )

    with pytest.raises(InvalidSuggestionContentError):
        await use_case.execute(short_dto)

    mock_generator.execute.assert_not_awaited()


# ==============================================================================
# Category 2: Tri-Track Normalization, Field Mapping & Prompt Assembly Happy Path
# ==============================================================================


@pytest.mark.asyncio
async def test_analyze_suggestion_invokes_prompt_preparer_with_normalized_fields(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    hit = _make_search_result(
        "c-1",
        "SUG-1",
        "sol",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.9,
    )
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit])
    mock_reranker.rerank = AsyncMock(
        return_value=[
            RerankedCandidate(
                candidate_id="c-1",
                retrieval_rank=1,
                retrieval_score=0.9,
                rerank_score=1.85,
                reranked_rank=1,
            )
        ]
    )
    mock_uow.suggestions.get_by_ids = AsyncMock(
        return_value=[_make_suggestion("SUG-1", SuggestionStatus.EXECUTED)]
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    await use_case.execute(valid_dto)

    mock_generator.execute.assert_awaited_once()
    call_args = mock_generator.execute.call_args
    gen_input: GenerationInput = call_args[0][0]
    curr = gen_input.current_suggestion

    assert curr.title == f"normalized_{valid_dto.title}"
    assert curr.problem == f"normalized_{valid_dto.problem}"
    assert curr.solution == f"normalized_{valid_dto.solution}"
    assert curr.context_title == f"normalized_{valid_dto.context_title}"


@pytest.mark.asyncio
async def test_analyze_suggestion_populates_analysis_with_prepared_prompt(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    mock_generator.execute.return_value = GenerationResult(
        answer="## CUSTOM_GENERATED_PROMPT_ABC_123",
        citations=[],
        uncertainty=None,
    )
    hit = _make_search_result(
        "c-1",
        "SUG-1",
        "sol",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.9,
    )
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit])
    mock_reranker.rerank = AsyncMock(
        return_value=[
            RerankedCandidate(
                candidate_id="c-1",
                retrieval_rank=1,
                retrieval_score=0.9,
                rerank_score=1.5,
                reranked_rank=1,
            )
        ]
    )
    mock_uow.suggestions.get_by_ids = AsyncMock(
        return_value=[_make_suggestion("SUG-1", SuggestionStatus.EXECUTED)]
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    result = await use_case.execute(valid_dto)
    assert result.analysis == "## CUSTOM_GENERATED_PROMPT_ABC_123"


@pytest.mark.asyncio
async def test_analyze_suggestion_passes_raw_logits_to_similar_input(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    hit1 = _make_search_result(
        "c-1",
        "SUG-1",
        "sol",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.9,
    )
    hit2 = _make_search_result(
        "c-2",
        "SUG-2",
        "prob",
        SuggestionChunkType.PROBLEM,
        SuggestionStatus.PENDING,
        0.8,
    )
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit1, hit2])

    # Neural cross-encoder unconstrained raw logits (> 1.0 and < 0.0)
    mock_reranker.rerank = AsyncMock(
        return_value=[
            RerankedCandidate(
                candidate_id="c-1",
                retrieval_rank=1,
                retrieval_score=0.9,
                rerank_score=2.45,
                reranked_rank=1,
            ),
            RerankedCandidate(
                candidate_id="c-2",
                retrieval_rank=2,
                retrieval_score=0.8,
                rerank_score=-0.85,
                reranked_rank=2,
            ),
        ]
    )
    mock_uow.suggestions.get_by_ids = AsyncMock(
        return_value=[
            _make_suggestion("SUG-1", SuggestionStatus.EXECUTED),
            _make_suggestion("SUG-2", SuggestionStatus.PENDING),
        ]
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
        min_score_threshold=None,
    )

    await use_case.execute(valid_dto)

    call_args = mock_generator.execute.call_args
    gen_input: GenerationInput = call_args[0][0]
    similar_inputs = gen_input.similar_suggestions

    assert len(similar_inputs) == 2
    assert similar_inputs[0].id == "SUG-1"
    assert similar_inputs[0].similarity == 2.45  # Unclamped positive logit
    assert similar_inputs[1].id == "SUG-2"
    assert similar_inputs[1].similarity == -0.85  # Unclamped negative logit


@pytest.mark.asyncio
async def test_analyze_suggestion_maps_hydrated_fields_accurately(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    hit = _make_search_result(
        "c-1",
        "SUG-99",
        "sol",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.APPROVED,
        0.9,
    )
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit])
    mock_reranker.rerank = AsyncMock(
        return_value=[
            RerankedCandidate(
                candidate_id="c-1",
                retrieval_rank=1,
                retrieval_score=0.9,
                rerank_score=0.98,
                reranked_rank=1,
            )
        ]
    )

    detailed_sug = Suggestion(
        id="SUG-99",
        content=SuggestionContent(
            title="عنوان دقیق در پایگاه داده",
            problem="مسئله دقیق ثبت‌شده در سیستم",
            solution="راهکار کامل و جامع",
        ),
        evaluation=CommitteeEvaluation(status=SuggestionStatus.APPROVED),
        context_title="حوزه تخصصی انتقال",
    )
    mock_uow.suggestions.get_by_ids = AsyncMock(return_value=[detailed_sug])

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    await use_case.execute(valid_dto)

    call_args = mock_generator.execute.call_args
    gen_input: GenerationInput = call_args[0][0]
    sim_item = gen_input.similar_suggestions[0]

    assert sim_item.id == "SUG-99"
    assert sim_item.status == SuggestionStatus.APPROVED
    assert sim_item.title == "عنوان دقیق در پایگاه داده"
    assert sim_item.problem == "مسئله دقیق ثبت‌شده در سیستم"
    assert sim_item.solution == "راهکار کامل و جامع"
    assert sim_item.context_title == "حوزه تخصصی انتقال"
    assert sim_item.similarity == 0.98


@pytest.mark.asyncio
async def test_analyze_suggestion_none_or_empty_context_title_mapping(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
) -> None:
    dto_no_context = AnalyzeSuggestionDTO(
        title="عنوان پیشنهاد تستی",
        problem="مسئله و چالش بسیار مهم در سیستم",
        solution="راهکار بهبود و رفع مشکل موردنظر",
        context_title="   ",  # Whitespace only
    )
    hit = _make_search_result(
        "c-1",
        "SUG-1",
        "sol",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.9,
    )
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit])
    mock_reranker.rerank = AsyncMock(
        return_value=[
            RerankedCandidate(
                candidate_id="c-1",
                retrieval_rank=1,
                retrieval_score=0.9,
                rerank_score=1.0,
                reranked_rank=1,
            )
        ]
    )
    mock_uow.suggestions.get_by_ids = AsyncMock(
        return_value=[_make_suggestion("SUG-1", SuggestionStatus.EXECUTED)]
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    await use_case.execute(dto_no_context)

    call_args = mock_generator.execute.call_args
    gen_input: GenerationInput = call_args[0][0]
    assert gen_input.current_suggestion.context_title is None


@pytest.mark.asyncio
async def test_analyze_suggestion_delegates_to_generator_with_valid_input(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    hit = _make_search_result(
        "c-1",
        "SUG-1",
        "sol",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.9,
    )
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit])
    mock_reranker.rerank = AsyncMock(
        return_value=[
            RerankedCandidate(
                candidate_id="c-1",
                retrieval_rank=1,
                retrieval_score=0.9,
                rerank_score=1.0,
                reranked_rank=1,
            )
        ]
    )
    mock_uow.suggestions.get_by_ids = AsyncMock(
        return_value=[_make_suggestion("SUG-1", SuggestionStatus.EXECUTED)]
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    await use_case.execute(valid_dto)

    mock_generator.execute.assert_awaited_once()
    call_args = mock_generator.execute.call_args
    gen_input: GenerationInput = call_args[0][0]
    assert gen_input.current_suggestion.title == f"normalized_{valid_dto.title}"
    assert len(gen_input.similar_suggestions) == 1
    assert gen_input.similar_suggestions[0].id == "SUG-1"


# ==============================================================================
# Category 3: Global Rank Preservation & Partition Ordering Invariants
# ==============================================================================


@pytest.mark.asyncio
async def test_analyze_suggestion_orders_candidates_by_global_score_desc(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    # 3 hits across different statuses: PENDING, EXECUTED, REJECTED
    hit_pending = _make_search_result(
        "c-p",
        "SUG-P",
        "sol",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.PENDING,
        0.8,
    )
    hit_exec = _make_search_result(
        "c-e",
        "SUG-E",
        "sol",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.8,
    )
    hit_rej = _make_search_result(
        "c-r",
        "SUG-R",
        "sol",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.REJECTED,
        0.8,
    )
    mock_vector_repo.search_suggestions = AsyncMock(
        return_value=[hit_pending, hit_exec, hit_rej]
    )

    # Cross-encoder scores: PENDING (1.85) > EXECUTED (0.92) > REJECTED (-0.20)
    mock_reranker.rerank = AsyncMock(
        return_value=[
            RerankedCandidate(
                candidate_id="c-p",
                retrieval_rank=1,
                retrieval_score=0.8,
                rerank_score=1.85,
                reranked_rank=1,
            ),
            RerankedCandidate(
                candidate_id="c-e",
                retrieval_rank=2,
                retrieval_score=0.8,
                rerank_score=0.92,
                reranked_rank=2,
            ),
            RerankedCandidate(
                candidate_id="c-r",
                retrieval_rank=3,
                retrieval_score=0.8,
                rerank_score=-0.20,
                reranked_rank=3,
            ),
        ]
    )
    mock_uow.suggestions.get_by_ids = AsyncMock(
        return_value=[
            _make_suggestion("SUG-R", SuggestionStatus.REJECTED),
            _make_suggestion("SUG-E", SuggestionStatus.EXECUTED),
            _make_suggestion("SUG-P", SuggestionStatus.PENDING),
        ]
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
        min_score_threshold=None,
    )

    await use_case.execute(valid_dto)

    call_args = mock_generator.execute.call_args
    gen_input: GenerationInput = call_args[0][0]
    similar_inputs = gen_input.similar_suggestions

    assert [s.id for s in similar_inputs] == ["SUG-P", "SUG-E", "SUG-R"]
    assert [s.similarity for s in similar_inputs] == [1.85, 0.92, -0.20]


@pytest.mark.asyncio
async def test_analyze_suggestion_orders_mixed_positive_and_negative_scores(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    hits = [
        _make_search_result(
            f"c-{i}",
            f"SUG-{i}",
            "sol",
            SuggestionChunkType.SOLUTION,
            SuggestionStatus.EXECUTED,
            0.8,
        )
        for i in range(1, 5)
    ]
    mock_vector_repo.search_suggestions = AsyncMock(return_value=hits)

    # Scores: 3.1, 0.4, -0.2, -1.9
    mock_reranker.rerank = AsyncMock(
        return_value=[
            RerankedCandidate(
                candidate_id="c-1",
                retrieval_rank=1,
                retrieval_score=0.8,
                rerank_score=3.1,
                reranked_rank=1,
            ),
            RerankedCandidate(
                candidate_id="c-2",
                retrieval_rank=2,
                retrieval_score=0.8,
                rerank_score=0.4,
                reranked_rank=2,
            ),
            RerankedCandidate(
                candidate_id="c-3",
                retrieval_rank=3,
                retrieval_score=0.8,
                rerank_score=-0.2,
                reranked_rank=3,
            ),
            RerankedCandidate(
                candidate_id="c-4",
                retrieval_rank=4,
                retrieval_score=0.8,
                rerank_score=-1.9,
                reranked_rank=4,
            ),
        ]
    )
    mock_uow.suggestions.get_by_ids = AsyncMock(
        return_value=[
            _make_suggestion(f"SUG-{i}", SuggestionStatus.EXECUTED) for i in range(1, 5)
        ]
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
        top_n_per_status=5,
        min_score_threshold=None,
    )

    await use_case.execute(valid_dto)

    call_args = mock_generator.execute.call_args
    gen_input: GenerationInput = call_args[0][0]
    similar_inputs = gen_input.similar_suggestions

    assert [s.id for s in similar_inputs] == ["SUG-1", "SUG-2", "SUG-3", "SUG-4"]
    assert [s.similarity for s in similar_inputs] == [3.1, 0.4, -0.2, -1.9]


@pytest.mark.asyncio
async def test_analyze_suggestion_handles_equal_scores_deterministically(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    hit1 = _make_search_result(
        "c-1",
        "SUG-1",
        "sol",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.8,
    )
    hit2 = _make_search_result(
        "c-2",
        "SUG-2",
        "sol",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.8,
    )
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit1, hit2])

    # Exactly identical rerank scores
    mock_reranker.rerank = AsyncMock(
        return_value=[
            RerankedCandidate(
                candidate_id="c-1",
                retrieval_rank=1,
                retrieval_score=0.8,
                rerank_score=1.50,
                reranked_rank=1,
            ),
            RerankedCandidate(
                candidate_id="c-2",
                retrieval_rank=2,
                retrieval_score=0.8,
                rerank_score=1.50,
                reranked_rank=2,
            ),
        ]
    )
    mock_uow.suggestions.get_by_ids = AsyncMock(
        return_value=[
            _make_suggestion("SUG-1", SuggestionStatus.EXECUTED),
            _make_suggestion("SUG-2", SuggestionStatus.EXECUTED),
        ]
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    # Must complete without sorting crash
    result = await use_case.execute(valid_dto)
    assert len(result.similar_executed_ids) == 2


@pytest.mark.asyncio
async def test_analyze_suggestion_single_winning_chunk_per_parent(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    # 2 different chunks for the SAME parent SUG-1
    hit_sol = _make_search_result(
        "c-sol",
        "SUG-1",
        "راهکار",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.85,
    )
    hit_prob = _make_search_result(
        "c-prob",
        "SUG-1",
        "مسئله",
        SuggestionChunkType.PROBLEM,
        SuggestionStatus.EXECUTED,
        0.75,
    )
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit_sol, hit_prob])

    mock_reranker.rerank = AsyncMock(
        return_value=[
            RerankedCandidate(
                candidate_id="c-sol",
                retrieval_rank=1,
                retrieval_score=0.85,
                rerank_score=2.10,
                reranked_rank=1,
            ),
            RerankedCandidate(
                candidate_id="c-prob",
                retrieval_rank=2,
                retrieval_score=0.75,
                rerank_score=1.40,
                reranked_rank=2,
            ),
        ]
    )
    mock_uow.suggestions.get_by_ids = AsyncMock(
        return_value=[_make_suggestion("SUG-1", SuggestionStatus.EXECUTED)]
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    await use_case.execute(valid_dto)

    call_args = mock_generator.execute.call_args
    gen_input: GenerationInput = call_args[0][0]
    similar_inputs = gen_input.similar_suggestions

    # SUG-1 must appear exactly ONCE with winning score 2.10
    assert len(similar_inputs) == 1
    assert similar_inputs[0].id == "SUG-1"
    assert similar_inputs[0].similarity == 2.10


@pytest.mark.asyncio
async def test_analyze_suggestion_enforces_top_n_per_status_slicing(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    # 5 hits all EXECUTED
    hits = [
        _make_search_result(
            f"c-{i}",
            f"SUG-{i}",
            "sol",
            SuggestionChunkType.SOLUTION,
            SuggestionStatus.EXECUTED,
            0.9 - (i * 0.05),
        )
        for i in range(1, 6)
    ]
    mock_vector_repo.search_suggestions = AsyncMock(return_value=hits)

    mock_reranker.rerank = AsyncMock(
        return_value=[
            RerankedCandidate(
                candidate_id=f"c-{i}",
                retrieval_rank=i,
                retrieval_score=0.9 - (i * 0.05),
                rerank_score=2.0 - (i * 0.2),
                reranked_rank=i,
            )
            for i in range(1, 6)
        ]
    )
    mock_uow.suggestions.get_by_ids = AsyncMock(
        return_value=[
            _make_suggestion(f"SUG-{i}", SuggestionStatus.EXECUTED) for i in range(1, 4)
        ]
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
        top_n_per_status=3,  # Top-N is 3
    )

    result = await use_case.execute(valid_dto)

    # Only top 3 are queried from DB and returned
    mock_uow.suggestions.get_by_ids.assert_called_once_with(
        ["SUG-1", "SUG-2", "SUG-3"], include_deleted=False
    )
    assert result.similar_executed_ids == ["SUG-1", "SUG-2", "SUG-3"]


# ==============================================================================
# Category 4: Zero-Evidence Short-Circuiting (GPU & Compute Conservation)
# ==============================================================================


@pytest.mark.asyncio
async def test_analyze_suggestion_zero_active_db_records_bypasses_prompt_preparer(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    hit = _make_search_result(
        "c-1",
        "SUG-1",
        "sol",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.9,
    )
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit])
    mock_reranker.rerank = AsyncMock(
        return_value=[
            RerankedCandidate(
                candidate_id="c-1",
                retrieval_rank=1,
                retrieval_score=0.9,
                rerank_score=1.5,
                reranked_rank=1,
            )
        ]
    )

    # Database returns record as is_deleted=True
    mock_uow.suggestions.get_by_ids = AsyncMock(
        return_value=[
            _make_suggestion("SUG-1", SuggestionStatus.EXECUTED, is_deleted=True)
        ]
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    result = await use_case.execute(valid_dto)

    # Must short-circuit without calling prompt preparer
    mock_generator.execute.assert_not_awaited()
    assert result.similar_executed_ids == []
    assert "تعداد 0 پیشنهاد" in result.analysis


@pytest.mark.asyncio
async def test_analyze_suggestion_missing_db_records_filtered_cleanly(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    hit = _make_search_result(
        "c-stale",
        "SUG-STALE",
        "sol",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.9,
    )
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit])
    mock_reranker.rerank = AsyncMock(
        return_value=[
            RerankedCandidate(
                candidate_id="c-stale",
                retrieval_rank=1,
                retrieval_score=0.9,
                rerank_score=1.5,
                reranked_rank=1,
            )
        ]
    )

    # PostgreSQL returns empty list (record hard-deleted)
    mock_uow.suggestions.get_by_ids = AsyncMock(return_value=[])

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    result = await use_case.execute(valid_dto)

    # Should cleanly short-circuit
    mock_generator.execute.assert_not_awaited()
    assert result.similar_executed_ids == []
    assert "تعداد 0 پیشنهاد" in result.analysis


@pytest.mark.asyncio
async def test_analyze_suggestion_all_below_min_score_threshold_bypasses_preparer(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    hit = _make_search_result(
        "c-1",
        "SUG-1",
        "sol",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.4,
    )
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit])

    # Score 0.2 is below threshold 0.5
    mock_reranker.rerank = AsyncMock(
        return_value=[
            RerankedCandidate(
                candidate_id="c-1",
                retrieval_rank=1,
                retrieval_score=0.4,
                rerank_score=0.2,
                reranked_rank=1,
            )
        ]
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
        min_score_threshold=0.5,
    )

    result = await use_case.execute(valid_dto)

    # All below threshold -> short-circuits
    mock_generator.execute.assert_not_awaited()
    cast(AsyncMock, mock_uow.suggestions.get_by_ids).assert_not_called()
    assert result.similar_executed_ids == []
    assert "تعداد 0 پیشنهاد" in result.analysis


@pytest.mark.asyncio
async def test_analyze_suggestion_single_active_candidate_survives(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    hit1 = _make_search_result(
        "c-1",
        "SUG-1",
        "sol",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.9,
    )
    hit2 = _make_search_result(
        "c-2",
        "SUG-2",
        "sol",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.8,
    )
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit1, hit2])

    mock_reranker.rerank = AsyncMock(
        return_value=[
            RerankedCandidate(
                candidate_id="c-1",
                retrieval_rank=1,
                retrieval_score=0.9,
                rerank_score=1.5,
                reranked_rank=1,
            ),
            RerankedCandidate(
                candidate_id="c-2",
                retrieval_rank=2,
                retrieval_score=0.8,
                rerank_score=1.2,
                reranked_rank=2,
            ),
        ]
    )

    # SUG-2 is deleted, only SUG-1 active
    mock_uow.suggestions.get_by_ids = AsyncMock(
        return_value=[
            _make_suggestion("SUG-1", SuggestionStatus.EXECUTED, is_deleted=False),
            _make_suggestion("SUG-2", SuggestionStatus.EXECUTED, is_deleted=True),
        ]
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    result = await use_case.execute(valid_dto)

    mock_generator.execute.assert_awaited_once()
    assert result.similar_executed_ids == ["SUG-1"]
    call_args = mock_generator.execute.call_args
    gen_input: GenerationInput = call_args[0][0]
    assert len(gen_input.similar_suggestions) == 1
    assert gen_input.similar_suggestions[0].id == "SUG-1"


# ==============================================================================
# Category 5 & 6: Fail-Fast Token Budget & Provider Degradation
# ==============================================================================


@pytest.mark.asyncio
async def test_analyze_suggestion_insufficient_evidence_budget_propagates(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    hit = _make_search_result(
        "c-1",
        "SUG-1",
        "sol",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.9,
    )
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit])
    mock_reranker.rerank = AsyncMock(
        return_value=[
            RerankedCandidate(
                candidate_id="c-1",
                retrieval_rank=1,
                retrieval_score=0.9,
                rerank_score=1.5,
                reranked_rank=1,
            )
        ]
    )
    mock_uow.suggestions.get_by_ids = AsyncMock(
        return_value=[_make_suggestion("SUG-1", SuggestionStatus.EXECUTED)]
    )

    mock_generator.execute.side_effect = InsufficientEvidenceBudgetError(
        "Remaining budget cannot fit highest-ranked item."
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    with pytest.raises(InsufficientEvidenceBudgetError):
        await use_case.execute(valid_dto)


@pytest.mark.asyncio
async def test_analyze_suggestion_prompt_budget_exceeded_propagates(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    hit = _make_search_result(
        "c-1",
        "SUG-1",
        "sol",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.9,
    )
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit])
    mock_reranker.rerank = AsyncMock(
        return_value=[
            RerankedCandidate(
                candidate_id="c-1",
                retrieval_rank=1,
                retrieval_score=0.9,
                rerank_score=1.5,
                reranked_rank=1,
            )
        ]
    )
    mock_uow.suggestions.get_by_ids = AsyncMock(
        return_value=[_make_suggestion("SUG-1", SuggestionStatus.EXECUTED)]
    )

    mock_generator.execute.side_effect = PromptBudgetExceededError("Fixed sections exceed budget.")

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    with pytest.raises(PromptBudgetExceededError):
        await use_case.execute(valid_dto)


@pytest.mark.asyncio
async def test_analyze_suggestion_reranker_protocol_or_limit_fallback_prepares_prompt(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    hit = _make_search_result(
        "c-1",
        "SUG-1",
        "sol",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.85,
    )
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit])

    # Reranker raises RerankerProtocolError
    mock_reranker.rerank = AsyncMock(
        side_effect=RerankerProtocolError("Malformed response from TEI")
    )
    mock_uow.suggestions.get_by_ids = AsyncMock(
        return_value=[_make_suggestion("SUG-1", SuggestionStatus.EXECUTED)]
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    result = await use_case.execute(valid_dto)
    assert result.similar_executed_ids == ["SUG-1"]
    mock_generator.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_analyze_suggestion_normalizer_failure_fails_fast(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    mock_normalizer.normalize_async = AsyncMock(
        side_effect=RuntimeError("Normalizer failed unexpectedly")
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    with pytest.raises(RuntimeError, match="Normalizer failed"):
        await use_case.execute(valid_dto)

    cast(AsyncMock, mock_vector_repo.search_suggestions).assert_not_called()
    mock_generator.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_analyze_suggestion_embedding_failure_fails_fast(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    mock_embedding_service.embed_query = AsyncMock(
        side_effect=RuntimeError("Embedding service connection error")
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    with pytest.raises(RuntimeError, match="Embedding service"):
        await use_case.execute(valid_dto)

    cast(AsyncMock, mock_vector_repo.search_suggestions).assert_not_called()
    mock_generator.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_analyze_suggestion_vector_repo_failure_fails_fast(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    mock_vector_repo.search_suggestions = AsyncMock(
        side_effect=RuntimeError("Qdrant cluster unavailable")
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    with pytest.raises(RuntimeError, match="Qdrant cluster unavailable"):
        await use_case.execute(valid_dto)

    cast(AsyncMock, mock_reranker.rerank).assert_not_called()
    mock_generator.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_analyze_suggestion_uow_database_failure_fails_fast(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    hit = _make_search_result(
        "c-1",
        "SUG-1",
        "sol",
        SuggestionChunkType.SOLUTION,
        SuggestionStatus.EXECUTED,
        0.9,
    )
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit])
    mock_reranker.rerank = AsyncMock(
        return_value=[
            RerankedCandidate(
                candidate_id="c-1",
                retrieval_rank=1,
                retrieval_score=0.9,
                rerank_score=1.5,
                reranked_rank=1,
            )
        ]
    )

    mock_uow.suggestions.get_by_ids = AsyncMock(
        side_effect=RuntimeError("PostgreSQL pool connection timeout")
    )

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )

    with pytest.raises(RuntimeError, match="PostgreSQL pool"):
        await use_case.execute(valid_dto)

    mock_generator.execute.assert_not_awaited()


# ==============================================================================
# Category 7: Dependency Injection, Configuration & Architectural Invariants
# ==============================================================================


def test_analyze_suggestion_constructor_requires_generator(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
) -> None:
    with pytest.raises(TypeError, match="generator must not be None"):
        AnalyzeSuggestionUseCase(
            normalizer=mock_normalizer,
            embedding_service=mock_embedding_service,
            vector_repo=mock_vector_repo,
            reranker=mock_reranker,
            uow=mock_uow,
            generator=cast(Any, None),
        )


def test_container_resolves_analyze_suggestion_use_case_with_generator() -> None:
    from dependency_injector import providers
    from src.application.interfaces import ILLMClient
    from src.domain.context.tokenizer import Tokenizer

    class LocalFakeTokenizer(Tokenizer):
        @property
        def supports_offset_mapping(self) -> bool:
            return True

        def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
            return [(i, (i, i + 1)) for i in range(len(text))]

        def count_tokens(self, text: str) -> int:
            return len(text)

    container = Container()
    container.tokenizer.override(providers.Object(LocalFakeTokenizer()))
    container.reranker.override(providers.Object(MagicMock(spec=IReranker)))
    container.hybrid_embedding_service.override(
        providers.Object(MagicMock(spec=IHybridEmbeddingService))
    )
    container.suggestion_vector_repository.override(
        providers.Object(MagicMock(spec=ISuggestionVectorRepository))
    )
    container.unit_of_work.override(providers.Object(MagicMock(spec=IUnitOfWork)))
    container.llm_client.override(providers.Object(MagicMock(spec=ILLMClient)))
    use_case = container.analyze_suggestion_use_case()

    assert isinstance(use_case, AnalyzeSuggestionUseCase)
    assert isinstance(use_case._generator, IGenerateSuggestionUseCase)


def _setup_active_candidates(
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    suggestion_ids: list[str],
) -> None:
    hits = []
    reranked = []
    suggestions = []
    for i, sid in enumerate(suggestion_ids, 1):
        cid = f"chunk-{sid}"
        hits.append(
            _make_search_result(
                cid,
                sid,
                f"راهکار {sid}",
                SuggestionChunkType.SOLUTION,
                SuggestionStatus.EXECUTED,
                0.9 - (i * 0.05),
            )
        )
        reranked.append(
            RerankedCandidate(
                candidate_id=cid,
                retrieval_rank=i,
                retrieval_score=0.9 - (i * 0.05),
                rerank_score=2.0 - (i * 0.1),
                reranked_rank=i,
            )
        )
        suggestions.append(_make_suggestion(sid, SuggestionStatus.EXECUTED))
    mock_vector_repo.search_suggestions = AsyncMock(return_value=hits)
    mock_reranker.rerank = AsyncMock(return_value=reranked)
    mock_uow.suggestions.get_by_ids = AsyncMock(return_value=suggestions)


@pytest.mark.asyncio
async def test_analyze_suggestion_empty_citations_yields_zero_grounding_ratio(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    _setup_active_candidates(mock_vector_repo, mock_reranker, mock_uow, ["SUG-1", "SUG-2"])
    mock_generator.execute.return_value = GenerationResult(
        answer="تحلیل بدون ارجاع",
        citations=[],
        uncertainty=None,
    )
    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )
    res = await use_case.execute(valid_dto)
    assert res.cited_suggestion_ids == []
    assert res.grounding_ratio == 0.0


@pytest.mark.asyncio
async def test_analyze_suggestion_all_evidence_cited_yields_perfect_grounding_ratio(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    _setup_active_candidates(mock_vector_repo, mock_reranker, mock_uow, ["SUG-1", "SUG-2"])
    mock_generator.execute.return_value = GenerationResult(
        answer="تحلیل با ارجاع کامل",
        citations=[
            SimilarSuggestionInput(id="SUG-1", status=SuggestionStatus.EXECUTED, title="t1", problem="p1", solution="s1", similarity=1.0),
            SimilarSuggestionInput(id="SUG-2", status=SuggestionStatus.EXECUTED, title="t2", problem="p2", solution="s2", similarity=0.9),
        ],
        uncertainty=None,
    )
    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )
    res = await use_case.execute(valid_dto)
    assert res.cited_suggestion_ids == ["SUG-1", "SUG-2"]
    assert res.grounding_ratio == 1.0


@pytest.mark.asyncio
async def test_analyze_suggestion_partial_citations_calculates_correct_rounded_ratio(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    _setup_active_candidates(mock_vector_repo, mock_reranker, mock_uow, ["SUG-1", "SUG-2", "SUG-3"])
    mock_generator.execute.return_value = GenerationResult(
        answer="تحلیل با ارجاع جزئی",
        citations=[
            SimilarSuggestionInput(id="SUG-1", status=SuggestionStatus.EXECUTED, title="t1", problem="p1", solution="s1", similarity=1.0),
        ],
        uncertainty=None,
    )
    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )
    res = await use_case.execute(valid_dto)
    assert res.cited_suggestion_ids == ["SUG-1"]
    assert res.grounding_ratio == 0.33


@pytest.mark.asyncio
async def test_analyze_suggestion_duplicate_llm_citations_deduplicated_preserving_order(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    _setup_active_candidates(mock_vector_repo, mock_reranker, mock_uow, ["SUG-1", "SUG-2"])
    mock_generator.execute.return_value = GenerationResult(
        answer="تحلیل با ارجاعات تکراری",
        citations=[
            SimilarSuggestionInput(id="SUG-2", status=SuggestionStatus.EXECUTED, title="t2", problem="p2", solution="s2", similarity=0.9),
            SimilarSuggestionInput(id="SUG-1", status=SuggestionStatus.EXECUTED, title="t1", problem="p1", solution="s1", similarity=1.0),
            SimilarSuggestionInput(id="SUG-2", status=SuggestionStatus.EXECUTED, title="t2", problem="p2", solution="s2", similarity=0.9),
        ],
        uncertainty=None,
    )
    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )
    res = await use_case.execute(valid_dto)
    assert res.cited_suggestion_ids == ["SUG-2", "SUG-1"]
    assert res.grounding_ratio == 1.0


@pytest.mark.asyncio
async def test_analyze_suggestion_unretrieved_citation_ids_isolated_and_filtered(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    _setup_active_candidates(mock_vector_repo, mock_reranker, mock_uow, ["SUG-1"])
    mock_generator.execute.return_value = GenerationResult(
        answer="تحلیل با ارجاع ساختگی",
        citations=[
            SimilarSuggestionInput(id="SUG-1", status=SuggestionStatus.EXECUTED, title="t1", problem="p1", solution="s1", similarity=1.0),
            SimilarSuggestionInput(id="HALLUCINATED-999", status=SuggestionStatus.EXECUTED, title="fake", problem="fake", solution="fake", similarity=0.5),
        ],
        uncertainty=None,
    )
    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )
    res = await use_case.execute(valid_dto)
    assert res.cited_suggestion_ids == ["SUG-1"]
    assert res.grounding_ratio == 1.0


@pytest.mark.asyncio
async def test_analyze_suggestion_citation_type_safety_filters_non_suggestion_chunks(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    _setup_active_candidates(mock_vector_repo, mock_reranker, mock_uow, ["SUG-1"])
    mock_generator.execute.return_value = GenerationResult(
        answer="تحلیل با انواع مختلف ارجاع",
        citations=[
            cast(Any, "raw-string-citation"),
            SimilarSuggestionInput(id="SUG-1", status=SuggestionStatus.EXECUTED, title="t1", problem="p1", solution="s1", similarity=1.0),
        ],
        uncertainty=None,
    )
    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )
    res = await use_case.execute(valid_dto)
    assert res.cited_suggestion_ids == ["SUG-1"]


@pytest.mark.asyncio
async def test_analyze_suggestion_uncertainty_field_preservation_null_and_non_null(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    _setup_active_candidates(mock_vector_repo, mock_reranker, mock_uow, ["SUG-1"])
    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )
    # Non-null uncertainty
    mock_generator.execute.return_value = GenerationResult(
        answer="تحلیل با عدم قطعیت",
        citations=[],
        uncertainty="داده‌های عملکردی در دسترس نیست.",
    )
    res1 = await use_case.execute(valid_dto)
    assert res1.uncertainty == "داده‌های عملکردی در دسترس نیست."

    # Null uncertainty
    mock_generator.execute.return_value = GenerationResult(
        answer="تحلیل بدون عدم قطعیت",
        citations=[],
        uncertainty=None,
    )
    res2 = await use_case.execute(valid_dto)
    assert res2.uncertainty is None


@pytest.mark.asyncio
async def test_analyze_suggestion_rrf_fallback_preserved_when_zero_db_records_survive(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    hit = _make_search_result("c-1", "SUG-1", "sol", SuggestionChunkType.SOLUTION, SuggestionStatus.EXECUTED, 0.9)
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit])
    mock_reranker.rerank = AsyncMock(side_effect=RerankerConnectionError("TEI unreachable"))
    mock_uow.suggestions.get_by_ids = AsyncMock(return_value=[])

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )
    res = await use_case.execute(valid_dto)
    assert res.is_fallback_mode is True
    assert res.uncertainty == "هیچ سابقه سازمانی مرتبطی برای ارزیابی این پیشنهاد یافت نشد."
    assert res.grounding_ratio == 0.0
    mock_generator.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_analyze_suggestion_rrf_fallback_propagates_to_successful_generation_response(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    hit = _make_search_result("c-1", "SUG-1", "sol", SuggestionChunkType.SOLUTION, SuggestionStatus.EXECUTED, 0.9)
    mock_vector_repo.search_suggestions = AsyncMock(return_value=[hit])
    mock_reranker.rerank = AsyncMock(side_effect=RerankerConnectionError("TEI unreachable"))
    mock_uow.suggestions.get_by_ids = AsyncMock(return_value=[_make_suggestion("SUG-1", SuggestionStatus.EXECUTED)])

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )
    res = await use_case.execute(valid_dto)
    assert res.is_fallback_mode is True
    mock_generator.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_analyze_suggestion_llm_provider_errors_propagate_fail_fast(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    _setup_active_candidates(mock_vector_repo, mock_reranker, mock_uow, ["SUG-1"])
    mock_generator.execute.side_effect = LLMConnectionError("vLLM connection refused")

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )
    with pytest.raises(LLMConnectionError, match="vLLM connection refused"):
        await use_case.execute(valid_dto)


@pytest.mark.asyncio
async def test_analyze_suggestion_output_parser_errors_propagate_fail_fast(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
    mock_generator: IGenerateSuggestionUseCase,
    valid_dto: AnalyzeSuggestionDTO,
) -> None:
    _setup_active_candidates(mock_vector_repo, mock_reranker, mock_uow, ["SUG-1"])
    mock_generator.execute.side_effect = LLMOutputParseError("Invalid json")

    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
        generator=mock_generator,
    )
    with pytest.raises(LLMOutputParseError, match="Invalid json"):
        await use_case.execute(valid_dto)
