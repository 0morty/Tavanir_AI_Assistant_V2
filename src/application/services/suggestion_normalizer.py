from src.application.interfaces.i_text_normalizer import ITextNormalizer
from src.domain.entities import (
    CommitteeEvaluation,
    SecretariatEvaluation,
    Suggestion,
    SuggestionContent,
)


def normalize_suggestion(
    suggestion: Suggestion, normalizer: ITextNormalizer
) -> Suggestion:
    """
    Normalizes all textual fields of a Suggestion entity using the provided ITextNormalizer.

    Produces a clean, new Suggestion instance ready for persistence in PostgreSQL
    (System of Record) and downstream vector chunking.
    """
    # 1. Normalize SuggestionContent
    normalized_title = normalizer.normalize(suggestion.content.title)
    normalized_problem = normalizer.normalize(suggestion.content.problem)
    normalized_solution = normalizer.normalize(suggestion.content.solution)
    normalized_content = SuggestionContent(
        title=normalized_title,
        problem=normalized_problem,
        solution=normalized_solution,
    )

    # 2. Normalize CommitteeEvaluation
    normalized_description = (
        normalizer.normalize(suggestion.evaluation.description)
        if suggestion.evaluation.description is not None
        else None
    )
    normalized_evaluation = CommitteeEvaluation(
        status=suggestion.evaluation.status,
        scrutiny=suggestion.evaluation.scrutiny,
        description=normalized_description,
        scrutiny_id=suggestion.evaluation.scrutiny_id,
    )

    # 3. Normalize SecretariatEvaluation
    normalized_sec_evaluation: SecretariatEvaluation | None = None
    if suggestion.secretariat_evaluation is not None:
        sec = suggestion.secretariat_evaluation
        norm_sec_comment = (
            normalizer.normalize(sec.comment)
            if sec.comment is not None
            else None
        )
        normalized_sec_evaluation = SecretariatEvaluation(
            scrutiny=sec.scrutiny,
            comment=norm_sec_comment,
            scrutiny_id=sec.scrutiny_id,
        )

    # 4. Normalize context_title
    normalized_context_title = (
        normalizer.normalize(suggestion.context_title)
        if suggestion.context_title is not None
        else None
    )

    return Suggestion(
        id=suggestion.id,
        content=normalized_content,
        evaluation=normalized_evaluation,
        date=suggestion.date,
        context_title=normalized_context_title,
        secretariat_evaluation=normalized_sec_evaluation,
    )


__all__ = ["normalize_suggestion"]

