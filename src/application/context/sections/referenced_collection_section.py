from collections.abc import Sequence

from src.application.context.sections.referenced_section import ReferencedSection
from src.application.interfaces.i_reference_generator import IReferenceGenerator
from src.domain.entities import Reference, ReferenceItem
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class ReferencedCollectionSection(ReferencedSection):
    """Base class for Sections whose content is a collection of reference-bearing items.

    Each :class:`ReferenceItem` pairs its own content with an optional
    :class:`Reference`; items are processed independently. An item without a
    Reference, or with empty content, passes through unchanged.

    ``body()`` is built from ``append_references()``, which composes every
    item through the inherited ``compose_referenced_content()`` hook. A
    subclass may override ``append_references()`` when its domain requires a
    different collection composition strategy.
    """

    def __init__(
        self,
        items: Sequence[ReferenceItem],
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
    def items(self) -> Sequence[ReferenceItem]:
        """The collection of reference-bearing items."""
        return self._items

    def append_references(self) -> str:
        """Apply each item's Reference independently and join the results."""
        rendered: list[str] = []
        for item in self._items:
            content = item.content
            if not content or not content.strip():
                continue
            if item.reference is None:
                rendered.append(content)
                continue

            reference_text = self._resolve_reference_text(item.reference)
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