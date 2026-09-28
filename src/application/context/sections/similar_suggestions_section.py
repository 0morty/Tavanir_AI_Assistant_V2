from collections.abc import Sequence
from typing import Any

from src.application.context.sections.referenced_collection_section import (
    ReferencedCollectionSection,
)
from src.application.dtos import SimilarSuggestionInput
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.domain.context.summarizer import Summarizer
from src.domain.overflow_strategy_stack import OverflowStrategy, OverflowStrategyStack


class SimilarSuggestionsSection(ReferencedCollectionSection):
    """Render retrieved suggestions in strict upstream rank order."""

    def __init__(
        self,
        suggestions: Sequence[SimilarSuggestionInput],
        *,
        item_separator: str = "\n\n",
        importance: float | None = None,
        demand: float | None = None,
        summarizer: Summarizer | None = None,
        chunk_summarizer: ITextSummarizer | None = None,
    ) -> None:
        resolved_overflow = OverflowStrategyStack([OverflowStrategy.IGNORE])
        super().__init__(
            items=suggestions,
            citation_label="similar",
            item_separator=item_separator,
            importance=importance,
            demand=demand,
            default_importance=0.5,
            default_demand=0.5,
            overflow_strategies=resolved_overflow,
            default_overflow_strategies=resolved_overflow,
            summarizer=summarizer,
            chunk_summarizer=chunk_summarizer,
        )

    @property
    def section_type(self) -> str:
        return "SIMILAR-SUGGESTIONS"

    @property
    def pre_context(self) -> str:
        return "## سوابق پیشنهادات مشابه بازیابی‌شده:"

    def item_content(self, item: Any) -> str:
        status_val = getattr(item, "status", None)
        status_title = (
            getattr(status_val, "title_fa", str(status_val))
            if status_val is not None
            else ""
        )
        similarity = getattr(item, "similarity", 0.0)
        try:
            sim_str = f"{float(similarity):.2f}"
        except (ValueError, TypeError):
            sim_str = "0.00"
        title = getattr(item, "title", "")
        problem = getattr(item, "problem", "")
        solution = getattr(item, "solution", "")
        return (
            f"وضعیت: {status_title} | میزان تشابه: {sim_str}\n"
            f"عنوان: {title}\n"
            f"مسئله: {problem}\n"
            f"راهکار: {solution}"
        )
