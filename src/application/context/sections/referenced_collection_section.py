from collections.abc import Sequence
from typing import Any

from src.application.context.sections.referenced_section import ReferencedSection
from src.application.interfaces.i_reference_generator import IReferenceGenerator
from src.domain.entities import Reference
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

    def body(self) -> str:
        """Build the Section content as the collection of enriched items."""
        return self.append_references()