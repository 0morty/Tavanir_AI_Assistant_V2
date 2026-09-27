"""Reference-aware retrieval chunks with deterministic citation IDs."""

import re
from collections.abc import Sequence
from typing import Any

from src.application.context.sections.referenced_collection_section import (
    ReferencedCollectionSection,
)
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.domain.context.summarizer import Summarizer
from src.domain.entities import GenerationChunk
from src.domain.overflow_strategy_stack import OverflowStrategyStack


_CITATION_ID_PATTERN = re.compile(r"\[chunk [0-9]{3}\]")
_CHUNK_LABEL_PATTERN = re.compile(r"^Chunk [0-9]+:\s*")
_MAX_CITATION_IDS = 999


def _clean_chunk_summary(text: str) -> str:
    """Remove model-repeated labels and markers before section-owned rendering."""
    without_citations = _CITATION_ID_PATTERN.sub("", text).strip()
    return _CHUNK_LABEL_PATTERN.sub("", without_citations).strip()


class ChunksSection(ReferencedCollectionSection):
    """Generation chunks with position-based, LLM-visible citation markers.

    The section owns citation identity. A source chunk_id remains unchanged,
    while [chunk XXX] markers are assigned in source order. ContextBuilder
    receives the same prepared and processed collection result shape as before.
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
        if len(chunks) > _MAX_CITATION_IDS:
            raise ValueError("ChunksSection supports at most 999 three-digit citation IDs")
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
        self._citation_ids = tuple(
            f"[chunk {index:03d}]" for index in range(1, len(self.items) + 1)
        )

    @property
    def chunks(self) -> tuple[GenerationChunk, ...]:
        """Original chunks; processed copies are returned by transformations."""
        return self.items

    @property
    def citation_map(self) -> dict[str, str]:
        """Map every citation marker to its internal source chunk ID."""
        return dict(zip(self._citation_ids, (item.chunk_id for item in self.items)))

    def citation_map_for(
        self, surviving_items: Sequence[GenerationChunk]
    ) -> dict[str, str]:
        """Map only chunks retained in a processed ContextBuilder section.

        Collection IGNORE retains an ordered prefix. SUMMARIZE makes item copies
        but preserves their chunk IDs and order. Requiring those processed items
        prevents a removed chunk's marker from being accepted after overflow.
        """
        if len(surviving_items) > len(self.items) or any(
            item.chunk_id != self.items[index].chunk_id
            for index, item in enumerate(surviving_items)
        ):
            raise ValueError("Surviving chunks must retain the original order")
        return dict(
            zip(
                self._citation_ids[: len(surviving_items)],
                (item.chunk_id for item in surviving_items),
            )
        )

    @staticmethod
    def extract_citation_ids(response_text: str) -> list[str]:
        """Extract exact three-digit markers once, in first-appearance order."""
        return list(dict.fromkeys(_CITATION_ID_PATTERN.findall(response_text)))

    def invalid_citation_ids(
        self, response_text: str, surviving_items: Sequence[GenerationChunk]
    ) -> list[str]:
        """Return well-formed response IDs absent from the final chunk map."""
        known = self.citation_map_for(surviving_items)
        return [
            citation
            for citation in self.extract_citation_ids(response_text)
            if citation not in known
        ]

    def cited_sources(
        self, response_text: str, surviving_items: Sequence[GenerationChunk]
    ) -> dict[str, str]:
        """Resolve valid response citations to source IDs in text order."""
        known = self.citation_map_for(surviving_items)
        return {
            citation: known[citation]
            for citation in self.extract_citation_ids(response_text)
            if citation in known
        }

    @property
    def section_type(self) -> str:
        return "CHUNKS"

    @property
    def pre_context(self) -> str:
        return "Relevant context chunks:"

    def item_content(self, item: Any) -> str:
        """Return the source text without test or report labels."""
        return item.content

    def _item_body_at(self, item: Any, index: int) -> str:
        return self._cited_body(item, index, self.item_content(item))

    @staticmethod
    def _copy_with_content(item: Any, content: str) -> Any:
        return ReferencedCollectionSection._copy_with_content(
            item, _clean_chunk_summary(content)
        )

    def _summary_bodies(
        self, items: tuple[GenerationChunk, ...], summaries: list[str]
    ) -> tuple[str, ...]:
        # Item copies already contain cleaned summaries. Only section-owned IDs render.
        return tuple(
            self._cited_body(item, index, item.content)
            for index, item in enumerate(items)
        )

    def _cited_body(self, item: Any, index: int, content: str) -> str:
        reference = getattr(item, "reference", None)
        reference_text = self._resolve_reference_text(reference) if reference is not None else ""
        marker = f"Unique ID: {self._citation_ids[index]}"
        heading = f"{reference_text}\n{marker}" if reference_text else marker
        return f"{heading}\n\n{content}"
