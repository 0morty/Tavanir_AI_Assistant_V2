from typing import Any

from src.application.context.sections.referenced_collection_section import (
    ReferencedCollectionSection,
)
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.domain.context.summarizer import Summarizer
from src.domain.entities import HistoryMessage
from src.domain.overflow_strategy_stack import OverflowStrategyStack


# TODO: همگام سازی با استاندارد GenerationChunk
class HistorySection(ReferencedCollectionSection):
    """Conversation turns whose processed results retain order and roles."""

    def __init__(
        self,
        messages: list[HistoryMessage],
        *,
        importance: float | None = None,
        demand: float | None = None,
        overflow_strategies: OverflowStrategyStack | None = None,
        summarizer: Summarizer | None = None,
        chunk_summarizer: ITextSummarizer | None = None,
    ) -> None:
        super().__init__(
            items=messages,
            separator="\n\n",
            importance=importance,
            demand=demand,
            default_importance=0.3,
            default_demand=0.4,
            overflow_strategies=overflow_strategies,
            summarizer=summarizer,
            chunk_summarizer=chunk_summarizer,
        )

    @property
    def section_type(self) -> str:
        return "HISTORY"

    @property
    def pre_context(self) -> str:
        return "History of previous interactions:"

    def item_content(self, item: Any) -> str:
        """Render a turn as ``role: content`` so the sender is preserved."""
        return f"{item.role.value}: {item.content}"

    def _summary_bodies(
        self, items: tuple[HistoryMessage, ...], summaries: list[str]
    ) -> tuple[str, ...]:
        return tuple(self.item_content(item) for item in items)
