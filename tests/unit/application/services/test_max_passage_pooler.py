from __future__ import annotations

from src.application.services.max_passage_pooler import (
    pool_and_partition_candidates,
)

from src.domain.entities import (
    SuggestionChunk,
    SuggestionChunkMetadata,
    SuggestionSearchResult,
)
from src.domain.enums import SuggestionChunkType, SuggestionStatus


def _create_search_result(
    chunk_id: str,
    parent_id: str,
    chunk_type: SuggestionChunkType,
    status: SuggestionStatus | None,
    content: str = "محتوای راهکار پیشنهادی سیستم",
) -> SuggestionSearchResult:
    metadata = SuggestionChunkMetadata(
        chunk_type=chunk_type,
        status=status,
    )
    chunk = SuggestionChunk(
        chunk_id=chunk_id,
        parent_id=parent_id,
        content=content,
        metadata=metadata,
    )
    return SuggestionSearchResult(chunk=chunk, score=0.0)


def test_empty_candidates_returns_empty_partitions() -> None:
    result = pool_and_partition_candidates([])
    assert len(result) == len(SuggestionStatus)
    for status in SuggestionStatus:
        assert result[status] == []


def test_maxp_picks_highest_scoring_chunk() -> None:
    # Parent sug-1 has three chunks with different scores
    hit_problem = _create_search_result(
        chunk_id="sug-1#prob",
        parent_id="sug-1",
        chunk_type=SuggestionChunkType.PROBLEM,
        status=SuggestionStatus.EXECUTED,
        content="شرح مسئله تست",
    )
    hit_title = _create_search_result(
        chunk_id="sug-1#title",
        parent_id="sug-1",
        chunk_type=SuggestionChunkType.TITLE,
        status=SuggestionStatus.EXECUTED,
        content="عنوان پیشنهاد",
    )
    hit_solution = _create_search_result(
        chunk_id="sug-1#sol",
        parent_id="sug-1",
        chunk_type=SuggestionChunkType.SOLUTION,
        status=SuggestionStatus.EXECUTED,
        content="شرح راهکار پیشنهادی برنده",
    )

    scored_chunks = [
        (hit_problem, 0.45),
        (hit_title, 0.20),
        (hit_solution, 3.85),
    ]

    partition_map = pool_and_partition_candidates(scored_chunks, top_n_per_status=3)

    executed_list = partition_map[SuggestionStatus.EXECUTED]
    assert len(executed_list) == 1

    winner = executed_list[0]
    assert winner.suggestion_id == "sug-1"
    assert winner.status == SuggestionStatus.EXECUTED

    assert winner.winning_score == 3.85
    assert winner.winning_chunk_id == "sug-1#sol"
    assert winner.winning_chunk_type == SuggestionChunkType.SOLUTION
    assert winner.winning_content == "شرح راهکار پیشنهادی برنده"
    # Asserts all distinct matched chunk types aggregated preserving encounter order
    assert winner.all_matched_chunk_types == (
        SuggestionChunkType.PROBLEM,
        SuggestionChunkType.TITLE,
        SuggestionChunkType.SOLUTION,
    )


def test_tied_scores_deterministic_selection() -> None:
    hit_a = _create_search_result(
        chunk_id="sug-1#prob",
        parent_id="sug-1",
        chunk_type=SuggestionChunkType.PROBLEM,
        status=SuggestionStatus.APPROVED,
    )
    hit_b = _create_search_result(
        chunk_id="sug-1#sol",
        parent_id="sug-1",
        chunk_type=SuggestionChunkType.SOLUTION,
        status=SuggestionStatus.APPROVED,
    )

    # Identical score 2.5
    scored_chunks = [(hit_a, 2.5), (hit_b, 2.5)]
    partition_map = pool_and_partition_candidates(scored_chunks)

    approved = partition_map[SuggestionStatus.APPROVED]
    assert len(approved) == 1
    # Deterministically picks first encountered
    assert approved[0].winning_chunk_id == "sug-1#prob"
    assert approved[0].winning_score == 2.5


def test_threshold_drops_negative_logits_in_normal_mode() -> None:
    hit_neg = _create_search_result(
        chunk_id="sug-neg#sol",
        parent_id="sug-neg",
        chunk_type=SuggestionChunkType.SOLUTION,
        status=SuggestionStatus.REJECTED,
    )
    hit_pos = _create_search_result(
        chunk_id="sug-pos#sol",
        parent_id="sug-pos",
        chunk_type=SuggestionChunkType.SOLUTION,
        status=SuggestionStatus.REJECTED,
    )

    scored_chunks = [
        (hit_neg, -1.2),
        (hit_pos, 0.8),
    ]

    partition_map = pool_and_partition_candidates(
        scored_chunks, min_score_threshold=0.0, is_fallback_mode=False
    )

    rejected = partition_map[SuggestionStatus.REJECTED]
    assert len(rejected) == 1
    assert rejected[0].suggestion_id == "sug-pos"


def test_fallback_mode_bypasses_threshold() -> None:
    hit_rrf = _create_search_result(
        chunk_id="sug-rrf#sol",
        parent_id="sug-rrf",
        chunk_type=SuggestionChunkType.SOLUTION,
        status=SuggestionStatus.PENDING,
    )

    # Typical RRF score is 0.02, which is < 0.0 threshold if interpreted as logit
    scored_chunks = [(hit_rrf, 0.023)]

    # Normal mode with threshold=0.0 would drop this if score < 0.0, wait:
    # 0.023 is > 0.0, but if threshold was e.g. 0.5 (logit scale):
    partition_map = pool_and_partition_candidates(
        scored_chunks, min_score_threshold=0.5, is_fallback_mode=True
    )

    pending = partition_map[SuggestionStatus.PENDING]
    assert len(pending) == 1
    assert pending[0].suggestion_id == "sug-rrf"
    assert pending[0].winning_score == 0.023


def test_threshold_none_preserves_negative_scores() -> None:
    hit_neg = _create_search_result(
        chunk_id="sug-neg#sol",
        parent_id="sug-neg",
        chunk_type=SuggestionChunkType.SOLUTION,
        status=SuggestionStatus.NOT_ACCEPTED,
    )
    scored_chunks = [(hit_neg, -3.5)]

    partition_map = pool_and_partition_candidates(
        scored_chunks, min_score_threshold=None, is_fallback_mode=False
    )

    not_accepted = partition_map[SuggestionStatus.NOT_ACCEPTED]
    assert len(not_accepted) == 1
    assert not_accepted[0].winning_score == -3.5


def test_all_candidates_below_threshold_returns_empty_lists() -> None:
    hit1 = _create_search_result(
        chunk_id="sug-1#sol",
        parent_id="sug-1",
        chunk_type=SuggestionChunkType.SOLUTION,
        status=SuggestionStatus.APPROVED,
    )
    scored_chunks = [(hit1, -0.5)]

    partition_map = pool_and_partition_candidates(
        scored_chunks, min_score_threshold=0.0, is_fallback_mode=False
    )
    for status in SuggestionStatus:
        assert partition_map[status] == []


def test_partitioning_and_top_n_clamping() -> None:
    # 5 suggestions under EXECUTED with different scores
    scored_chunks = []
    for i in range(1, 6):
        hit = _create_search_result(
            chunk_id=f"sug-{i}#sol",
            parent_id=f"sug-{i}",
            chunk_type=SuggestionChunkType.SOLUTION,
            status=SuggestionStatus.EXECUTED,
        )
        scored_chunks.append((hit, float(i)))  # scores: 1.0, 2.0, 3.0, 4.0, 5.0

    partition_map = pool_and_partition_candidates(scored_chunks, top_n_per_status=3)

    executed = partition_map[SuggestionStatus.EXECUTED]
    assert len(executed) == 3
    # Strictly descending order: 5.0, 4.0, 3.0
    assert [c.suggestion_id for c in executed] == ["sug-5", "sug-4", "sug-3"]
    assert [c.winning_score for c in executed] == [5.0, 4.0, 3.0]


def test_partition_with_fewer_than_top_n() -> None:
    hit = _create_search_result(
        chunk_id="sug-only#sol",
        parent_id="sug-only",
        chunk_type=SuggestionChunkType.SOLUTION,
        status=SuggestionStatus.PENDING,
    )
    scored_chunks = [(hit, 2.0)]

    partition_map = pool_and_partition_candidates(scored_chunks, top_n_per_status=3)
    pending = partition_map[SuggestionStatus.PENDING]
    assert len(pending) == 1
    assert pending[0].suggestion_id == "sug-only"


def test_unrecognized_or_none_status_dropped() -> None:
    hit_invalid = _create_search_result(
        chunk_id="sug-none#sol",
        parent_id="sug-none",
        chunk_type=SuggestionChunkType.SOLUTION,
        status=None,
    )
    scored_chunks = [(hit_invalid, 5.0)]

    partition_map = pool_and_partition_candidates(scored_chunks)
    for status in SuggestionStatus:
        assert partition_map[status] == []
