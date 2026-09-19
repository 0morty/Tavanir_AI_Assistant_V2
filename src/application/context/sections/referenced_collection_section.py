from collections.abc import Sequence
from typing import Any

from src.application.context.sections.referenced_section import ReferencedSection
from src.application.interfaces.i_reference_generator import IReferenceGenerator
from src.domain.context.summarizer import Summarizer
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import Reference
from src.domain.enums import OverflowStrategy
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class ReferencedCollectionSection(ReferencedSection):
    """Parent base for every Section that holds a collection of reference-bearing items.

    Concrete collection sections such as :class:`ChunksSection` and
    :class:`HistorySection` inherit from this class. The held collection is
    exposed through ``chunks``; each item carries its own content and, when
    available, an optional Reference. Items are processed independently, so an
    item without a Reference, or with empty content, passes through unchanged.

    ``body()`` is built from ``append_references()``, which resolves each
    item's Reference (native ``fluent_text()`` or the injected generator) and
    composes it with the item's content through the inherited
    ``compose_referenced_content()`` hook. ``item_content()`` isolates the
    per-item text so subclasses own their item formatting while the reference
    machinery stays here.
    """

    def __init__(
        self,
        items: Sequence[Any],
        reference: Reference | None = None,
        *,
        reference_generator: IReferenceGenerator | None = None,
        separator: str = "\n\n",
        importance: float | None = None,
        demand: float | None = None,
        default_importance: float = 0.5,
        default_demand: float = 0.5,
        overflow_strategies: OverflowStrategyStack | None = None,
        default_overflow_strategies: OverflowStrategyStack | None = None,
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
        )
        self._items = list(items)

    @property
    def chunks(self) -> Sequence[Any]:
        """The collection of reference-bearing items held by this Section."""
        return self._items

    def item_content(self, item: Any) -> str:
        """The base content of a single collection item.

        Defaults to the item's ``content`` attribute. A subclass overrides this
        when its item text needs item-specific formatting (e.g. numbering or a
        role prefix) before reference composition.
        """
        return getattr(item, "content", "")

    def append_references(self) -> str:
        """Apply each item's Reference independently and join the results."""
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
        return self.separator.join(rendered)

    def fit_to_capacity(
        self,
        chunks: Sequence[Any],
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
        summarizer: Summarizer | None = None,
    ) -> str:
        """Fit a collection of items into ``capacity_tokens``.

        Collection-level overflow handling for the same ``OverflowStrategyStack``
        concept: when the joined collection already fits it is returned
        unchanged. Otherwise the stack is walked in priority order exactly like
        the parent, except that ``IGNORE`` operates at the item level -- it
        keeps items in order while they fit within the capacity and drops the
        rest. ``TRUNCATE`` and ``SUMMARIZE`` apply to the joined collection text
        through the parent's implementation.
        """
        if not chunks or capacity_tokens <= 0:
            return ""
        texts = [self.item_content(chunk) for chunk in chunks]
        content = self.separator.join(texts)
        if not content.strip():
            return ""
        if self._fits_within(content, capacity_tokens, tokenizer):
            return content
        return self._resolve_collection_overflow(
            texts, content, capacity_tokens, tokenizer, summarizer
        )

    def _resolve_collection_overflow(
        self,
        texts: Sequence[str],
        content: str,
        capacity_tokens: int,
        tokenizer: Tokenizer,
        summarizer: Summarizer | None,
    ) -> str:
        def apply(
            strategy: OverflowStrategy,
            _content: str,
            _capacity_tokens: int,
            _tokenizer: Tokenizer,
            _summarizer: Summarizer | None,
        ) -> str | None:
            if strategy is OverflowStrategy.IGNORE:
                return self._include_fitting_items(
                    texts, capacity_tokens, tokenizer
                )
            return self._apply_strategy(
                strategy, content, capacity_tokens, tokenizer, summarizer
            )

        return self._resolve_overflow(
            content, capacity_tokens, tokenizer, summarizer, applier=apply
        )

    def _include_fitting_items(
        self,
        texts: Sequence[str],
        capacity_tokens: int,
        tokenizer: Tokenizer,
    ) -> str:
        """Keep items in order while they fit; drop the items that would overflow."""
        included: list[str] = []
        total_tokens = 0
        separator_tokens = tokenizer.count_tokens(self.separator)
        for text in texts:
            item_tokens = tokenizer.count_tokens(text)
            separator_cost = separator_tokens if included else 0
            if total_tokens + separator_cost + item_tokens > capacity_tokens:
                break
            included.append(text)
            total_tokens += separator_cost + item_tokens
        return self.separator.join(included)

    def body(self) -> str:
        """Build the Section content as the collection of enriched items."""
        return self.append_references()