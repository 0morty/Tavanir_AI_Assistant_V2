from collections.abc import Sequence
from copy import copy
from dataclasses import is_dataclass, replace
from typing import Any

from src.application.context.sections.prompt_section import PromptSection
from src.application.context.sections.referenced_section import ReferenceSupport
from src.application.dtos import SectionProcessingResult
from src.application.interfaces.i_reference_generator import IReferenceGenerator
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.domain.context.overflow.summarize import SummarizeStrategy
from src.domain.context.summarizer import Summarizer
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import Reference
from src.domain.overflow_strategy_stack import OverflowStrategyStack


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

    @property
    def items(self) -> tuple[Any, ...]:
        return self._items

    def item_content(self, item: Any) -> str:
        return getattr(item, "content", "")

    def _item_body(self, item: Any) -> str:
        """Add this item's reference to its own formatted content."""
        content = self.item_content(item)
        reference = getattr(item, "reference", None)
        if not content.strip() or reference is None:
            return content
        reference_text = self._resolve_reference_text(reference)
        return (
            self.compose_referenced_content(reference_text, content)
            if reference_text
            else content
        )

    def _render_bodies(self, bodies: Sequence[str]) -> str:
        joined = self.item_separator.join(body for body in bodies if body.strip())
        return self._compose(self._with_section_reference(joined))

    def append_references(self) -> str:
        """Return the joined item bodies with each item's reference injected."""
        return self.item_separator.join(
            body for item in self._items if (body := self._item_body(item)).strip()
        )

    def body(self) -> str:
        return self.append_references()

    def render(self) -> str:
        return self._render_bodies(tuple(self._item_body(item) for item in self._items))

    def prepare(self) -> SectionProcessingResult:
        """Inject references once, then prepare aggregate and per-item inputs."""
        bodies = tuple(self._item_body(item) for item in self._items)
        return SectionProcessingResult(
            content=self._render_bodies(bodies),
            items=self._items,
            item_bodies=bodies,
            item_inputs=tuple(
                self._compose(self._with_section_reference(body)) for body in bodies
            ),
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
            return SectionProcessingResult("", (), (), ())
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
        )

    def _summary_bodies(
        self, items: tuple[Any, ...], summaries: list[str]
    ) -> tuple[str, ...]:
        """Default output body for each summarized collection item."""
        return tuple(summaries)

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
        if len(bodies) != len(items):
            raise ValueError("Collection result requires one prepared body per item")
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
        )
