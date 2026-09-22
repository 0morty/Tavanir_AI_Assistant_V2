from typing import Any

from src.application.context.sections.referenced_collection_section import (
    ReferencedCollectionSection,
)
from src.application.interfaces.i_chunk_summarizer import IChunkSummarizer
from src.domain.context.summarizer import Summarizer
from src.domain.entities import HistoryMessage
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class HistorySection(ReferencedCollectionSection):
    """Conversation/interaction history, distinct from RAG context chunks.

    A ``HistorySection`` is a collection section: the conversation turns are
    held as the section's items. Each turn keeps its ``role`` prefix in the
    rendered text, so a reference enrichment never strips the sender role.
    """

    def __init__(
        self,
        messages: list[HistoryMessage],
        *,
        importance: float | None = None,
        demand: float | None = None,
        overflow_strategies: OverflowStrategyStack | None = None,
        summarizer: Summarizer | None = None,
        chunk_summarizer: IChunkSummarizer | None = None,
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