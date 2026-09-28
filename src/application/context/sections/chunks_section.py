"""Reference-aware retrieval chunks using shared collection citation IDs."""

import re

from src.application.context.sections.referenced_collection_section import (
    ReferencedCollectionSection,
)
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.domain.context.summarizer import Summarizer
from src.domain.entities import GenerationChunk
from src.domain.overflow_strategy_stack import OverflowStrategyStack


_CHUNK_LABEL_PATTERN = re.compile(r"^Chunk [0-9]+:\s*")


class ChunksSection(ReferencedCollectionSection):
    """Render generation chunks with section-owned reference and citation text."""

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
            citation_label="chunk",
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
        """Original chunks; processed copies are returned by transformations."""
        return self.items

    @property
    def section_type(self) -> str:
        return "CHUNKS"

    @property
    def pre_context(self) -> str:
        return "Relevant context chunks:"

    @staticmethod
    def _copy_with_content(item: GenerationChunk, content: str) -> GenerationChunk:
        """Remove report-only chunk labels from generated summaries."""
        cleaned = _CHUNK_LABEL_PATTERN.sub("", content).strip()
        return ReferencedCollectionSection._copy_with_content(item, cleaned)
