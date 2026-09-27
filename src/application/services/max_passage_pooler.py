from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from src.application.dtos import PooledSuggestionCandidate
from src.domain.entities import SuggestionSearchResult
from src.domain.enums import SuggestionChunkType, SuggestionStatus


def pool_and_partition_candidates(
    scored_chunks: Sequence[tuple[SuggestionSearchResult, float]],
    *,
    top_n_per_status: int = 3,
    min_score_threshold: float | None = 0.0,
    is_fallback_mode: bool = False,
) -> dict[SuggestionStatus, list[PooledSuggestionCandidate]]:
    """
    Executes pure, deterministic Max-Passage (MaxP) pooling, threshold gating,
    and status partition slicing over retrieved candidate chunks.

    Pipeline:
    1. Groups candidate chunks by parent suggestion ID (`chunk.parent_id`).
    2. Identifies the winning chunk with the maximum score for each parent suggestion.
    3. Aggregates all matched `SuggestionChunkType` values into an immutable tuple.
    4. Applies threshold gating: drops candidates whose winning_score < min_score_threshold
       (automatically BYPASSED when operating in degraded RRF fallback mode).
    5. Partitions surviving candidates into discrete `SuggestionStatus` buckets.
    6. Sorts each partition descending by winning_score and clamps to `top_n_per_status`.

    Args:
        scored_chunks: Sequence of (SuggestionSearchResult, score) pairs.
        top_n_per_status: Maximum suggestions to retain per status partition.
        min_score_threshold: Minimum score required in normal mode (ignored if None).
        is_fallback_mode: If True, indicates fallback to RRF scores; threshold is bypassed.

    Returns:
        Dictionary mapping each SuggestionStatus to its top-N PooledSuggestionCandidate list.
    """
    partitions: dict[SuggestionStatus, list[PooledSuggestionCandidate]] = {
        status: [] for status in SuggestionStatus
    }

    if not scored_chunks:
        return partitions

    # 1. Group chunks by parent suggestion ID
    parent_groups: dict[str, list[tuple[SuggestionSearchResult, float]]] = {}
    for result, score in scored_chunks:
        pid = result.parent_id
        if pid not in parent_groups:
            parent_groups[pid] = []
        parent_groups[pid].append((result, score))

    # 2. Process each parent suggestion
    for pid, chunks in parent_groups.items():
        # Determine domain status from chunk metadata
        status: SuggestionStatus | None = None
        for res, _ in chunks:
            if isinstance(res.chunk.metadata.status, SuggestionStatus):
                status = res.chunk.metadata.status
                break

        if status is None:
            # Drop chunks with missing or unmapped status metadata
            continue

        # Find winning chunk by maximum score (deterministic first-encountered upon ties)
        winning_result, winning_score = max(chunks, key=lambda item: item[1])

        # Threshold Gate: filter out negative/irrelevant matches in normal mode
        if not is_fallback_mode and min_score_threshold is not None:
            if winning_score < min_score_threshold:
                continue

        # Aggregate distinct matched chunk types preserving encounter order
        seen_types: set[SuggestionChunkType] = set()
        matched_types: list[SuggestionChunkType] = []
        for res, _ in chunks:
            ctype = res.chunk.metadata.chunk_type
            if ctype not in seen_types:
                seen_types.add(ctype)
                matched_types.append(ctype)

        candidate = PooledSuggestionCandidate(
            suggestion_id=pid,
            status=status,
            winning_chunk_id=winning_result.chunk.chunk_id,
            winning_chunk_type=winning_result.chunk.metadata.chunk_type,
            winning_score=winning_score,
            winning_content=winning_result.chunk.content,
            all_matched_chunk_types=tuple(matched_types),
        )
        partitions[status].append(candidate)

    # 3. Sort each status partition descending by winning_score and slice top-N
    for status in SuggestionStatus:
        partitions[status].sort(key=lambda c: c.winning_score, reverse=True)
        if top_n_per_status > 0:
            partitions[status] = partitions[status][:top_n_per_status]

    return partitions


__all__: Final[list[str]] = ["pool_and_partition_candidates"]
