from collections.abc import Sequence
from typing import Any

from src.application.context.sections.referenced_collection_section import (
    ReferencedCollectionSection,
)
from src.application.dtos import SectionProcessingResult, SimilarSuggestionInput
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
    Overrides :meth:`truncate` to return an empty string or result, preventing
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
        chunks = [
            item.to_generation_chunk(idx + 1)
            for idx, item in enumerate(suggestions)
        ]

        resolved_overflow = OverflowStrategyStack([OverflowStrategy.IGNORE])
        super().__init__(
            items=chunks,
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
        """Return the chunk content, adapting SimilarSuggestionInput if passed directly."""
        if isinstance(item, SimilarSuggestionInput):
            return item.to_generation_chunk(1).content
        return getattr(item, "content", "")

    def _item_body(self, item: Any) -> str:
        """The item content already contains its formatted heading and metadata."""
        return self.item_content(item)

    def compose_referenced_content(self, reference_text: str, content: str) -> str:
        """Compose citation only if not already present in the formatted content heading."""
        if not reference_text or reference_text in content:
            return content
        return f"{reference_text}\n{content}"

    def ignore(
        self,
        content: SectionProcessingResult | str,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> SectionProcessingResult | str:
        """Fit items in rank order, supporting both SectionProcessingResult and legacy str callers."""
        is_str = isinstance(content, str)
        prep = self.prepare() if is_str else content
        result = super().ignore(prep, capacity_tokens, tokenizer=tokenizer)
        return result.content if is_str else result

    def truncate(
        self,
        content: SectionProcessingResult | str,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> SectionProcessingResult | str:
        """Neutralize truncation to prevent mid-sentence cutting."""
        if isinstance(content, str):
            return ""
        return SectionProcessingResult("", (), (), ())
