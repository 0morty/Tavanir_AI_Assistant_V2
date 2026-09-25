from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.application.use_cases.analyze_suggestion_use_case import (
    AnalyzeSuggestionUseCase,
)

from src.application.dtos import (
    AnalyzeSuggestionDTO,
    RerankCandidate,
    RerankedCandidate,
)
from src.application.exceptions import (
    RerankerAPIError,
    RerankerConnectionError,
    RerankerOverloadedError,
    RerankerValidationError,
)
from src.application.interfaces import (
    IHybridEmbeddingService,
    IReranker,
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
            # Assign score based on candidate_id
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
    # Unique chunks: chunk-1, chunk-2, chunk-3, chunk-4
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
    assert "تحلیل اولیه و سوابق مشابه" in result.analysis


@pytest.mark.asyncio
async def test_analyze_suggestion_zero_hits_short_circuits(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
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
    )

    result = await use_case.execute(valid_dto)

    # 5 searches were executed
    assert mock_vector_repo.search_suggestions.call_count == 5
    # Reranker and UoW were NEVER called
    cast(AsyncMock, mock_reranker.rerank).assert_not_called()
    cast(AsyncMock, mock_uow.suggestions.get_by_ids).assert_not_called()

    # Empty lists returned
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
    )

    # Should not raise; degrades gracefully to RRF
    result = await use_case.execute(valid_dto)

    assert result.similar_executed_ids == ["SUG-001"]
    mock_uow.suggestions.get_by_ids.assert_called_once_with(
        ["SUG-001"], include_deleted=False
    )


@pytest.mark.asyncio
async def test_analyze_suggestion_reranker_overloaded_fallback(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
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
    )

    result = await use_case.execute(valid_dto)
    assert result.similar_executed_ids == ["SUG-001"]


@pytest.mark.asyncio
async def test_analyze_suggestion_reranker_api_error_fallback(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
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
    )

    result = await use_case.execute(valid_dto)
    assert result.similar_executed_ids == ["SUG-001"]


@pytest.mark.asyncio
async def test_analyze_suggestion_reranker_validation_error_propagates(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
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
    )

    with pytest.raises(RerankerValidationError, match="Invalid payload format"):
        await use_case.execute(valid_dto)


@pytest.mark.asyncio
async def test_analyze_suggestion_filters_soft_deleted_and_preserves_score_order(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
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
    )

    result = await use_case.execute(valid_dto)

    # SUG-200 was filtered out.
    # Score order must be preserved: SUG-100 (0.95) must precede SUG-300 (0.75), despite SQL returning SUG-300 first!
    assert result.similar_executed_ids == ["SUG-100", "SUG-300"]


@pytest.mark.asyncio
async def test_analyze_suggestion_validates_domain_noise_and_short_content(
    mock_normalizer: ITextNormalizer,
    mock_embedding_service: IHybridEmbeddingService,
    mock_vector_repo: ISuggestionVectorRepository,
    mock_reranker: IReranker,
    mock_uow: IUnitOfWork,
) -> None:
    use_case = AnalyzeSuggestionUseCase(
        normalizer=mock_normalizer,
        embedding_service=mock_embedding_service,
        vector_repo=mock_vector_repo,
        reranker=mock_reranker,
        uow=mock_uow,
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
