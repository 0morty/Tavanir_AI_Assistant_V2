import re
from collections.abc import Mapping, Sequence
from copy import copy
from dataclasses import is_dataclass, replace
from typing import Any

from src.application.context.sections.prompt_section import PromptSection
from src.application.context.sections.referenced_section import ReferenceSupport
from src.application.dtos import SectionOutput, SectionProcessingResult
from src.application.interfaces.i_reference_generator import IReferenceGenerator
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.domain.context.overflow.summarize import SummarizeStrategy
from src.domain.context.summarizer import Summarizer
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import Reference
from src.domain.overflow_strategy_stack import OverflowStrategyStack

_MAX_CITATION_IDS = 999
_CITATION_LABEL_PATTERN = re.compile(r"[a-z][a-z0-9-]*")


class ReferencedCollectionSection(PromptSection, ReferenceSupport):
    """Reference-aware collection with independent, value-returning operations.

    The source items never change. Preparation creates complete per-item inputs
    for summarization, while the aggregate content is used for token accounting.
    """

    def __init__(
        self,
        items: Sequence[Any],
        reference: Reference | None = None,
        *,
        reference_generator: IReferenceGenerator | None = None,
        citation_label: str | None = None,
        cite_items: bool = True,
        separator: str = "\n\n",
        item_separator: str = "\n\n",
        importance: float | None = None,
        demand: float | None = None,
        default_importance: float = 0.5,
        default_demand: float = 0.5,
        overflow_strategies: OverflowStrategyStack | None = None,
        default_overflow_strategies: OverflowStrategyStack | None = None,
        summarizer: Summarizer | None = None,
        chunk_summarizer: ITextSummarizer | None = None,
    ) -> None:
        PromptSection.__init__(
            self,
            separator=separator,
            importance=importance,
            demand=demand,
            default_importance=default_importance,
            default_demand=default_demand,
            overflow_strategies=overflow_strategies,
            default_overflow_strategies=default_overflow_strategies,
            summarizer=summarizer,
        )
        ReferenceSupport.__init__(self, reference, reference_generator)
        self.item_separator = item_separator
        self._items = tuple(items)
        self._chunk_summarizer = chunk_summarizer
        self._cite_items = cite_items
        self._citation_pattern = re.compile(r"(?!)")
        self._summary_citation_pattern = re.compile(r"(?!)")
        self._citation_ids: tuple[str, ...] = ()
        self._citation_id_to_item: dict[str, Any] = {}
        self._item_identity_to_citations: dict[int, list[str]] = {}
        if cite_items:
            label = (
                citation_label
                if citation_label is not None
                else self.section_type.lower()
            )
            if not _CITATION_LABEL_PATTERN.fullmatch(label):
                raise ValueError("citation_label must be a lowercase ASCII identifier")
            if len(self._items) > _MAX_CITATION_IDS:
                raise ValueError(
                    "Referenced collections support at most 999 citation IDs"
                )
            self._citation_pattern = re.compile(rf"\[{re.escape(label)} [0-9]{{3}}\]")
            self._summary_citation_pattern = re.compile(
                rf"\[{re.escape(label)} [^\[\]]*\]"
            )
            self._citation_ids = tuple(
                f"[{label} {index:03d}]" for index in range(1, len(self._items) + 1)
            )
            self._citation_id_to_item = dict(zip(self._citation_ids, self._items))
            for citation_id, item in zip(self._citation_ids, self._items):
                self._item_identity_to_citations.setdefault(id(item), []).append(
                    citation_id
                )

    @property
    def items(self) -> tuple[Any, ...]:
        return self._items

    @property
    def citation_ids(self) -> tuple[str, ...]:
        return self._citation_ids

    @property
    def citation_map(self) -> dict[str, Any]:
        """Return citation IDs mapped to the original, unmodified items."""
        return self._citation_id_to_item.copy()

    def citation_ids_for(self, item: Any) -> tuple[str, ...]:
        """Return every occurrence ID for this exact source object."""
        return tuple(self._item_identity_to_citations.get(id(item), ()))

    def citation_map_for(
        self, result: SectionProcessingResult | SectionOutput
    ) -> dict[str, Any]:
        """Restrict the original map to IDs retained by overflow processing."""
        if not self._cite_items:
            raise ValueError("This collection does not expose citations")
        ids = result.citation_ids
        items = result.items
        if ids is None or items is None or len(ids) != len(items):
            raise ValueError(
                "Collection result requires aligned citation IDs and items"
            )
        if (
            isinstance(result, SectionOutput)
            and result.section_type != self.section_type
        ):
            raise ValueError("Collection result belongs to a different section")
        if ids != self._citation_ids[: len(ids)]:
            raise ValueError("Retained citation IDs must preserve their original order")
        return {
            citation_id: self._citation_id_to_item[citation_id] for citation_id in ids
        }

    def extract_citation_ids(self, output: Mapping[str, Any]) -> list[str]:
        """Read exact, unique IDs from the structured LLM citations array."""
        if not self._cite_items:
            raise ValueError("This collection does not expose citations")
        if not isinstance(output, Mapping):
            raise ValueError("Structured output must be a mapping")
        citations = output.get("citations")
        if not isinstance(citations, list):
            raise ValueError("Structured output requires a citations list")
        unique: dict[str, None] = {}
        for citation_id in citations:
            if not isinstance(citation_id, str) or not self._citation_pattern.fullmatch(
                citation_id
            ):
                raise ValueError(f"Invalid citation ID: {citation_id!r}")
            unique[citation_id] = None
        return list(unique)

    def resolve_citation_ids(
        self,
        citation_ids: Sequence[str],
        result: SectionProcessingResult | SectionOutput,
    ) -> dict[str, Any]:
        """Resolve retained IDs to original items; reject malformed or unknown IDs."""
        if isinstance(citation_ids, str):
            raise ValueError("Citation IDs must be a sequence of IDs")
        retained = self.citation_map_for(result)
        resolved: dict[str, Any] = {}
        for citation_id in citation_ids:
            if not isinstance(citation_id, str) or not self._citation_pattern.fullmatch(
                citation_id
            ):
                raise ValueError(f"Invalid citation ID: {citation_id!r}")
            if citation_id not in retained:
                raise ValueError(f"Unknown citation ID: {citation_id}")
            resolved[citation_id] = retained[citation_id]
        return resolved

    def item_content(self, item: Any) -> str:
        return getattr(item, "content", "")

    def _item_body_at(self, item: Any, index: int) -> str:
        """Attach a citation to source evidence and preserve uncited collections."""
        content = self.item_content(item)
        if not self._cite_items:
            return self._uncited_item_body(item, content)
        return self._cited_body(item, index, content)

    def _uncited_item_body(self, item: Any, content: str) -> str:
        reference = getattr(item, "reference", None)
        if reference is None or not content.strip():
            return content
        reference_text = self._resolve_reference_text(reference)
        return (
            self.compose_referenced_content(reference_text, content)
            if reference_text
            else content
        )

    def _cited_body(self, item: Any, index: int, content: str) -> str:
        reference = getattr(item, "reference", None)
        reference_text = (
            self._resolve_reference_text(reference) if reference is not None else ""
        )
        marker = f"Unique ID: {self._citation_ids[index]}"
        heading = f"{reference_text}\n{marker}" if reference_text else marker
        return f"{heading}\n\n{content}"

    def _render_bodies(self, bodies: Sequence[str]) -> str:
        joined = self.item_separator.join(body for body in bodies if body.strip())
        return self._compose(self._with_section_reference(joined))

    def append_references(self) -> str:
        """Return the joined item bodies with each item's reference injected."""
        return self.item_separator.join(
            body
            for index, item in enumerate(self._items)
            if (body := self._item_body_at(item, index)).strip()
        )

    def body(self) -> str:
        return self.append_references()

    def render(self) -> str:
        return self._render_bodies(
            tuple(
                self._item_body_at(item, index)
                for index, item in enumerate(self._items)
            )
        )

    def prepare(self) -> SectionProcessingResult:
        """Inject references once, then prepare aggregate and per-item inputs."""
        bodies = tuple(
            self._item_body_at(item, index) for index, item in enumerate(self._items)
        )
        return SectionProcessingResult(
            content=self._render_bodies(bodies),
            items=self._items,
            item_bodies=bodies,
            item_inputs=tuple(
                self._compose(self._with_section_reference(body)) for body in bodies
            ),
            citation_ids=self._citation_ids if self._cite_items else None,
        )

    def truncate(
        self,
        content: SectionProcessingResult,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> SectionProcessingResult:
        """Collection truncation is intentionally a no-op; IGNORE fits items."""
        return content

    def summarize(
        self,
        content: SectionProcessingResult,
        capacity_tokens: int,
    ) -> SectionProcessingResult | None:
        """Summarize prepared items independently and return aligned item copies."""
        if self._chunk_summarizer is None and self._summarizer is None:
            return None
        items = content.items or ()
        if not items or capacity_tokens <= 0:
            return SectionProcessingResult(
                content="",
                items=(),
                item_bodies=(),
                item_inputs=(),
                citation_ids=() if self._cite_items else None,
            )
        if self._cite_items:
            self.citation_map_for(content)
        inputs = content.item_inputs
        if inputs is None or len(inputs) != len(items):
            raise ValueError("Collection result requires one prepared input per item")
        if self._chunk_summarizer is not None:
            summaries = self._chunk_summarizer.summarize_chunks(
                inputs, capacity_tokens=capacity_tokens
            )
        else:
            summarizer = self._summarizer
            assert summarizer is not None
            strategy = SummarizeStrategy(summarizer)
            summaries = [strategy.apply(text, capacity_tokens) for text in inputs]
        if len(summaries) != len(items):
            raise ValueError("Collection summarizer must return one result per item")
        if self._cite_items:
            summaries = [
                self._summary_citation_pattern.sub("", summary).strip()
                for summary in summaries
            ]
        processed = tuple(
            self._copy_with_content(item, summary)
            for item, summary in zip(items, summaries)
        )
        bodies = self._summary_bodies(processed, summaries)
        return SectionProcessingResult(
            content=self._render_bodies(bodies),
            items=processed,
            item_bodies=bodies,
            item_inputs=tuple(
                self._compose(self._with_section_reference(body)) for body in bodies
            ),
            citation_ids=content.citation_ids,
        )

    def _summary_bodies(
        self, items: tuple[Any, ...], summaries: list[str]
    ) -> tuple[str, ...]:
        """Reattach original citations independently of the summarizer output."""
        if not self._cite_items:
            return tuple(
                self._uncited_item_body(item, getattr(item, "content", summary))
                for item, summary in zip(items, summaries)
            )
        return tuple(
            self._cited_body(item, index, getattr(item, "content", summary))
            for index, (item, summary) in enumerate(zip(items, summaries))
        )

    @staticmethod
    def _copy_with_content(item: Any, content: str) -> Any:
        if is_dataclass(item):
            return replace(item, content=content)
        copied = copy(item)
        copied.content = content
        return copied

    def ignore(
        self,
        content: SectionProcessingResult,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> SectionProcessingResult:
        """Drop trailing whole items until the complete rendered result fits."""
        items = content.items or ()
        bodies = content.item_bodies or ()
        ids = content.citation_ids or ()
        if len(bodies) != len(items) or (self._cite_items and len(ids) != len(items)):
            raise ValueError(
                "Collection result requires aligned bodies, items, and citation IDs"
            )
        fitting_count = 0
        fitting_content = ""
        for count in range(1, len(items) + 1):
            candidate = self._render_bodies(bodies[:count])
            if tokenizer.count_tokens(candidate) > capacity_tokens:
                break
            fitting_count = count
            fitting_content = candidate
        return SectionProcessingResult(
            content=fitting_content,
            items=items[:fitting_count],
            item_bodies=bodies[:fitting_count],
            item_inputs=(content.item_inputs or ())[:fitting_count],
            citation_ids=ids[:fitting_count] if self._cite_items else None,
        )
