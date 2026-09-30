from collections.abc import Sequence
from typing import Any

from src.application.context.sections.referenced_collection_section import (
    ReferencedCollectionSection,
)
from src.application.dtos import SectionProcessingResult, SimilarSuggestionInput
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.domain.context.summarizer import Summarizer
from src.domain.context.tokenizer import Tokenizer
from src.domain.overflow_strategy_stack import OverflowStrategy, OverflowStrategyStack


class SimilarSuggestionsSection(ReferencedCollectionSection):
    """Render suggestions in rank order while retaining their original identities."""

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
        if isinstance(item, SimilarSuggestionInput):
            return item.to_generation_chunk(1).content
        return getattr(item, "content", "")

    def _item_body_at(self, item: Any, index: int) -> str:
        if isinstance(item, SimilarSuggestionInput):
            chunk = item.to_generation_chunk(index + 1)
            return self._cited_body(chunk, index, chunk.content)
        return super()._item_body_at(item, index)

    def ignore(
        self,
        content: SectionProcessingResult | str,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> SectionProcessingResult | str:
        """Fit a prefix of complete suggestions, including legacy string callers."""
        if isinstance(content, str):
            return super().ignore(
                self.prepare(), capacity_tokens, tokenizer=tokenizer
            ).content
        return super().ignore(content, capacity_tokens, tokenizer=tokenizer)

    def truncate(
        self,
        content: SectionProcessingResult | str,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> SectionProcessingResult | str:
        """Keep fitted objects intact; legacy string callers receive no fragment."""
        if isinstance(content, str):
            return ""
        return super().truncate(content, capacity_tokens, tokenizer=tokenizer)
