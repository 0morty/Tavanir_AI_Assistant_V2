from collections.abc import Sequence
from typing import Any

from src.application.context.sections.referenced_section import ReferencedSection
from src.application.interfaces.i_chunk_summarizer import IChunkSummarizer
from src.application.interfaces.i_reference_generator import IReferenceGenerator
from src.domain.context.overflow.summarize import SummarizeStrategy
from src.domain.context.overflow.truncate import TruncateStrategy
from src.domain.context.summarizer import Summarizer
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import Reference
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class ReferencedCollectionSection(ReferencedSection):
    """Parent base for every Section that holds a collection of reference-bearing items.

    Concrete collection sections such as :class:`ChunksSection` and
    :class:`HistorySection` inherit from this class. The held collection is
    exposed as ``items``; each item carries its own content and, when
    available, an optional Reference. Items are processed independently, so an
    item without a Reference, or with empty content, passes through unchanged.

    ``body()`` is built from ``append_references()``, which resolves each
    item's Reference (native ``fluent_text()`` or the injected generator) and
    composes it with the item's content through the inherited
    ``compose_referenced_content()`` hook. ``item_content()`` isolates the
    per-item text so subclasses own their item formatting while the reference
    machinery stays here. Items are joined with ``item_separator``, which is
    independent of the section's framing ``separator``.

    The :class:`CompressibleSection` contract is inherited transitively through
    :class:`ReferencedSection`; this class overrides the three overflow
    operations for its collection representation, keeping the collection's
    internal shape a private concern. ``ignore`` keeps items in order while
    they fit and drops the rest; ``truncate`` and ``summarize`` apply the
    universal algorithms to the collection's joined (reference-enriched) text.
    When a :class:`IChunkSummarizer` is injected, ``summarize`` runs its
    batched 1:1 chunk summarization instead, mapping every item to its own
    summary.
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
        chunk_summarizer: IChunkSummarizer | None = None,
    ) -> None:
        super().__init__(
            reference=reference,
            reference_generator=reference_generator,
            separator=separator,
            importance=importance,
            demand=demand,
            default_importance=default_importance,
            default_demand=default_demand,
            overflow_strategies=overflow_strategies,
            default_overflow_strategies=default_overflow_strategies,
            summarizer=summarizer,
        )
        self.item_separator = item_separator
        self._items = list(items)
        self._chunk_summarizer = chunk_summarizer

    @property
    def items(self) -> Sequence[Any]:
        """The collection of reference-bearing items held by this Section."""
        return self._items

    def item_content(self, item: Any) -> str:
        """The base content of a single collection item.

        Defaults to the item's ``content`` attribute. A subclass overrides this
        when its item text needs item-specific formatting (e.g. numbering or a
        role prefix) before reference composition.
        """
        return getattr(item, "content", "")

    def _enriched_item_texts(self) -> list[str]:
        """The per-item texts, Reference-enriched, skipping empty items.

        Each item's own content is obtained from ``item_content()`` and, when
        the item carries a Reference, its resolved reference text is composed
        through ``compose_referenced_content()``.
        """
        rendered: list[str] = []
        for item in self._items:
            content = self.item_content(item)
            if not content or not content.strip():
                continue

            item_reference = getattr(item, "reference", None)
            if item_reference is None:
                rendered.append(content)
                continue

            reference_text = self._resolve_reference_text(item_reference)
            if not reference_text:
                rendered.append(content)
                continue
            rendered.append(
                self.compose_referenced_content(reference_text, content)
            )
        return rendered

    def append_references(self) -> str:
        """Apply each item's Reference independently and join the results."""
        return self.item_separator.join(self._enriched_item_texts())

    def truncate(
        self,
        content: str,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> str:
        """Apply the universal truncation to the collection's joined text.

        The collection's internal representation is its ordered, Reference-
        enriched item texts joined by ``item_separator``; the universal
        :class:`TruncateStrategy` reduces that joined text to a prefix that
        fits ``capacity_tokens``.
        """
        if not self._items or capacity_tokens <= 0:
            return ""
        joined = self.item_separator.join(self._enriched_item_texts())
        if not joined.strip():
            return ""
        return TruncateStrategy(tokenizer).apply(joined, capacity_tokens)

    def summarize(
        self,
        content: str,
        capacity_tokens: int,
    ) -> str | None:
        """Compress the collection's joined text through the Section's own summarizer.

        Returns ``None`` when no summarizer is configured, so the caller falls
        through to the next strategy. When an :class:`IChunkSummarizer` is
        injected, each item is summarized independently (strict 1:1 mapping)
        and the summaries are joined with ``item_separator``.
        """
        if self._chunk_summarizer is not None:
            if not self._items or capacity_tokens <= 0:
                return ""
            texts = self._enriched_item_texts()
            if not texts:
                return ""
            summaries = self._chunk_summarizer.summarize(
                texts, capacity_tokens=capacity_tokens
            )
            return self.item_separator.join(summaries)
        if self._summarizer is None:
            return None
        if not self._items or capacity_tokens <= 0:
            return ""
        joined = self.item_separator.join(self._enriched_item_texts())
        if not joined.strip():
            return ""
        return SummarizeStrategy(self._summarizer).apply(joined, capacity_tokens)

    def ignore(
        self,
        content: str,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> str:
        """Keep items in order while they fit; drop the items that would overflow."""
        if not self._items or capacity_tokens <= 0:
            return ""
        return self._include_fitting_items(
            self._enriched_item_texts(), capacity_tokens, tokenizer
        )

    def _include_fitting_items(
        self,
        texts: Sequence[str],
        capacity_tokens: int,
        tokenizer: Tokenizer,
    ) -> str:
        """Return the items in ``texts`` kept while each fits within the capacity."""
        included: list[str] = []
        total_tokens = 0
        separator_tokens = tokenizer.count_tokens(self.item_separator)
        for text in texts:
            item_tokens = tokenizer.count_tokens(text)
            separator_cost = separator_tokens if included else 0
            if total_tokens + separator_cost + item_tokens > capacity_tokens:
                break
            included.append(text)
            total_tokens += separator_cost + item_tokens
        return self.item_separator.join(included)

    def body(self) -> str:
        """Build the Section content as the collection of enriched items."""
        return self.append_references()