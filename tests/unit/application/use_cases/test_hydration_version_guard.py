from src.application.use_cases.analyze_suggestion_use_case import (
    AnalyzeSuggestionUseCase,
)

from src.application.dtos import (
    PooledSuggestionCandidate,
)
from src.domain.entities import (
    CommitteeEvaluation,
    Suggestion,
    SuggestionContent,
)
from src.domain.enums import SuggestionChunkType, SuggestionStatus


def create_candidate(suggestion_id: str, version: int = 1) -> PooledSuggestionCandidate:
    return PooledSuggestionCandidate(
        suggestion_id=suggestion_id,
        status=SuggestionStatus.APPROVED,
        winning_chunk_id=f"chunk-{suggestion_id}",
        winning_chunk_type=SuggestionChunkType.TITLE,
        winning_score=0.92,
        winning_content="عنوان تستی",
        all_matched_chunk_types=(SuggestionChunkType.TITLE,),
        version=version,
    )


def create_sql_suggestion(
    suggestion_id: str, version: int = 1, is_deleted: bool = False
) -> Suggestion:
    return Suggestion(
        id=suggestion_id,
        content=SuggestionContent(
            title="عنوان پایگاه داده",
            problem="شرح مشکل",
            solution="راهکار",
        ),
        evaluation=CommitteeEvaluation(status=SuggestionStatus.APPROVED),
        version=version,
        is_deleted=is_deleted,
    )


def test_is_valid_candidate_version_skew_rejected():
    cand = create_candidate("sugg-skew", version=1)
    sql_entity = create_sql_suggestion("sugg-skew", version=2)
    hydrated_map = {"sugg-skew": sql_entity}

    # Version skew (Qdrant v=1 vs SQL v=2): Must be rejected (F-14)
    assert AnalyzeSuggestionUseCase._is_valid_candidate(cand, hydrated_map) is False


def test_is_valid_candidate_version_match_accepted():
    cand = create_candidate("sugg-valid", version=2)
    sql_entity = create_sql_suggestion("sugg-valid", version=2)
    hydrated_map = {"sugg-valid": sql_entity}

    # Version match (Qdrant v=2 vs SQL v=2): Must be accepted
    assert AnalyzeSuggestionUseCase._is_valid_candidate(cand, hydrated_map) is True


def test_is_valid_candidate_deleted_rejected():
    cand = create_candidate("sugg-del", version=1)
    sql_entity = create_sql_suggestion("sugg-del", version=1, is_deleted=True)
    hydrated_map = {"sugg-del": sql_entity}

    # Soft-deleted record: Must be rejected
    assert AnalyzeSuggestionUseCase._is_valid_candidate(cand, hydrated_map) is False


def test_filter_active_status_partitions_filters_out_skewed_candidates():
    cand_skewed = create_candidate("sugg-1", version=1)
    cand_valid = create_candidate("sugg-2", version=2)

    partition_map = {
        SuggestionStatus.APPROVED: [cand_skewed, cand_valid],
        SuggestionStatus.EXECUTED: [],
        SuggestionStatus.PENDING: [],
        SuggestionStatus.REJECTED: [],
        SuggestionStatus.NOT_ACCEPTED: [],
    }

    hydrated_map = {
        "sugg-1": create_sql_suggestion("sugg-1", version=2),  # Skewed (v=1 != v=2)
        "sugg-2": create_sql_suggestion("sugg-2", version=2),  # Matched (v=2 == v=2)
    }

    filtered = AnalyzeSuggestionUseCase._filter_active_status_partitions(
        partition_map, hydrated_map
    )

    # sugg-1 must be discarded due to version skew; only sugg-2 survives
    assert filtered[SuggestionStatus.APPROVED] == ["sugg-2"]


def test_build_generation_input_omits_skewed_candidates():
    cand_skewed = create_candidate("sugg-1", version=1)
    cand_valid = create_candidate("sugg-2", version=2)

    hydrated_map = {
        "sugg-1": create_sql_suggestion("sugg-1", version=2),
        "sugg-2": create_sql_suggestion("sugg-2", version=2),
    }

    gen_input = AnalyzeSuggestionUseCase._build_generation_input(
        norm_title="عنوان ورودی",
        norm_problem="مشکل ورودی",
        norm_solution="راهکار ورودی",
        norm_context="شرکت توزیع",
        all_winning_candidates=[cand_skewed, cand_valid],
        hydrated_map=hydrated_map,
    )

    # Only sugg-2 should be present in similar_suggestions
    similar_ids = [s.id for s in gen_input.similar_suggestions]
    assert "sugg-1" not in similar_ids
    assert "sugg-2" in similar_ids
