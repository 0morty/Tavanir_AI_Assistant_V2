from src.application.interfaces.i_text_normalizer import ITextNormalizer
from src.domain.entities import CommitteeEvaluation, Suggestion, SuggestionContent


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
    normalized_problem = (
        normalizer.normalize(suggestion.content.problem)
        if suggestion.content.problem is not None
        else None
    )
    normalized_solution = (
        normalizer.normalize(suggestion.content.solution)
        if suggestion.content.solution is not None
        else None
    )
    normalized_content = SuggestionContent(
        title=normalized_title,
        problem=normalized_problem,
        solution=normalized_solution,
    )

    # 2. Normalize CommitteeEvaluation
    normalized_scrutiny = (
        normalizer.normalize(suggestion.evaluation.scrutiny)
        if suggestion.evaluation.scrutiny is not None
        else None
    )
    normalized_description = (
        normalizer.normalize(suggestion.evaluation.description)
        if suggestion.evaluation.description is not None
        else None
    )
    normalized_evaluation = CommitteeEvaluation(
        status=suggestion.evaluation.status,
        scrutiny=normalized_scrutiny,
        description=normalized_description,
    )

    # 3. Normalize context_title
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
    )


__all__ = ["normalize_suggestion"]
