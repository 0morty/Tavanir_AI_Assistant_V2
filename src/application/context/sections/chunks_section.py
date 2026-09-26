from typing import Any

from src.application.context.sections.referenced_collection_section import (
    ReferencedCollectionSection,
)
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.domain.context.summarizer import Summarizer
from src.domain.entities import GenerationChunk
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class ChunksSection(ReferencedCollectionSection):
    """Retrieval (RAG) context chunks.

    A ``ChunksSection`` is a collection section: the retrieved chunks are held
    as the section's items and exposed via ``items``. Items are the
    Generation-API side :class:`GenerationChunk` entities, whose ``reference``
    enriches each chunk's content during context construction (per the
    parent's collection behavior).
    """

    def __init__(
        self,
        chunks: list[GenerationChunk],
        *,
        importance: float | None = None,
        demand: float | None = None,
        overflow_strategies: OverflowStrategyStack | None = None,
        summarizer: Summarizer | None = None,
        chunk_summarizer: ITextSummarizer | None = None,
    ) -> None:
        super().__init__(
            items=chunks,
            separator="\n\n",
            importance=importance,
            demand=demand,
            default_importance=0.4,
            default_demand=0.5,
            overflow_strategies=overflow_strategies,
            summarizer=summarizer,
            chunk_summarizer=chunk_summarizer,
        )

    @property
    def chunks(self) -> tuple[GenerationChunk, ...]:
        """Summarized chunks when available, otherwise the source chunks."""
        items = self.summarized_items
        return tuple(self.items) if items is None else items

    @property
    def section_type(self) -> str:
        return "CHUNKS"

    @property
    def pre_context(self) -> str:
        return "Relevant context chunks:"

    def item_content(self, item: Any) -> str:
        """Render a chunk as a numbered block: ``Chunk N:\\n<content>``."""
        index = self.items.index(item) + 1
        return f"Chunk {index}:\n{item.content}"