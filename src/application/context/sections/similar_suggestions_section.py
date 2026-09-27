from collections.abc import Sequence
from typing import Any

from src.application.context.sections.referenced_collection_section import (
    ReferencedCollectionSection,
)
from src.application.dtos import SimilarSuggestionInput
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.domain.context.summarizer import Summarizer
from src.domain.context.tokenizer import Tokenizer
from src.domain.overflow_strategy_stack import (
    OverflowStrategy,
    OverflowStrategyStack,
)


class SimilarSuggestionsSection(ReferencedCollectionSection):
    """Section rendering retrieved similar suggestions in strict upstream rank order.

    Enforces rank integrity with no out-of-order skipping (knapsack anti-skip).
    Overrides :meth:`truncate` to return an empty string, preventing
    :class:`ContextBuilder` from falling back to mid-sentence cutting.
    """

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
        try:
            index = self._items.index(item) + 1
        except (ValueError, AttributeError):
            index = 1
        item_id = getattr(item, "id", "")
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
            f"[پیشنهاد مشابه {index}] کد پیشنهاد: {item_id} | وضعیت: {status_title} | میزان تشابه: {sim_str}\n"
            f"عنوان: {title}\n"
            f"مسئله: {problem}\n"
            f"راهکار: {solution}"
        )

    def ignore(
        self,
        content: str,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> str:
        """Fit items in upstream rank order, accounting for pre-context header framing."""
        if not self._items or capacity_tokens <= 0:
            return ""

        pre = self.pre_context
        pre_tokens = tokenizer.count_tokens(pre) if pre else 0
        frame_sep_tokens = tokenizer.count_tokens(self.separator) if pre else 0
        available_for_items = capacity_tokens - (pre_tokens + frame_sep_tokens)

        if available_for_items <= 0:
            return ""

        fitted_body = self._include_fitting_items(
            self._enriched_item_texts(), available_for_items, tokenizer
        )
        if not fitted_body:
            return ""

        return self._compose(fitted_body)

    def truncate(
        self,
        content: str,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> str:
        """Override to neutralize ContextBuilder's mid-sentence truncation safety net."""
        return ""
