from abc import ABC, abstractmethod

from src.domain.overflow_strategy_stack import OverflowStrategyStack


class ISection(ABC):
    """General-purpose logical section of a context.

    An ``ISection`` is a reusable logical part of a context. Prompting is
    just one consumer: the ``PromptBuilder`` composes ``ISection`` instances
    into an ordered prompt. Other components -- such as context
    construction or token allocation -- may consume the same ``ISection``
    concept without ever touching the prompt layer.

    Every section renders as three stacked parts:

    +--------------+
    | pre-context  |
    +--------------+
    |     body     |
    +--------------+
    | post-context |
    +--------------+

    Subclasses own the section's identity and body construction by
    overriding ``section_type`` and ``body()``; pre/post context framing is
    optional and defaults to empty strings. Each subclass passes its default
    ``importance`` and ``demand`` to the base constructor. A section whose
    ``body()`` is empty renders as an empty string, so unconfigured sections
    never leak framing or separators.

    ``importance`` is the intrinsic semantic importance of the section in the
    range ``[0.0, 1.0]``; it is used as a weight when redistributing unused
    token capacity and is **not** a token percentage.

    ``demand`` is the section's relative context-capacity demand in the range
    ``[0.0, 1.0]``; it is used to calculate the section's initial
    proportional token capacity.

    Both values of several sections are independent: they do not need to sum
    to ``1.0``, and an ``ISection`` never normalizes them or allocates
    capacity itself. Normalization and allocation are the responsibility of
    the context/token-allocation logic.

    ``overflow_strategies`` is an :class:`OverflowStrategyStack`: the ordered
    list of overflow strategies (lower index means higher priority) plus the
    restart policy for this section. It is pure configuration/state. Overflow
    handling itself is implemented by the reference-aware subclasses:
    ``ReferencedSection`` fits a single plain-text value, while
    ``ReferencedCollectionSection`` overrides the behavior for its collection.
    """

    def __init__(
        self,
        separator: str = "\n\n",
        importance: float | None = None,
        demand: float | None = None,
        default_importance: float = 0.5,
        default_demand: float = 0.5,
        overflow_strategies: OverflowStrategyStack | None = None,
        default_overflow_strategies: OverflowStrategyStack | None = None,
    ) -> None:
        self.separator = separator
        self.importance = default_importance if importance is None else importance
        self.demand = default_demand if demand is None else demand
        resolved_default = (
            default_overflow_strategies
            if default_overflow_strategies is not None
            else OverflowStrategyStack()
        )
        self.overflow_strategies = (
            resolved_default if overflow_strategies is None else overflow_strategies
        )

    @property
    @abstractmethod
    def section_type(self) -> str:
        """Identity/name of this section, e.g. "HISTORY" or "CHUNKS"."""

    @property
    def importance(self) -> float:
        """Intrinsic semantic importance used when redistributing unused capacity."""
        return self._importance

    @importance.setter
    def importance(self, value: float) -> None:
        if not 0.0 <= value <= 1.0:
            raise ValueError(
                f"Section importance must be in the range [0.0, 1.0]; got {value!r}."
            )
        self._importance = value

    @property
    def demand(self) -> float:
        """Relative context-capacity demand used for the initial token capacity."""
        return self._demand

    @demand.setter
    def demand(self, value: float) -> None:
        if not 0.0 <= value <= 1.0:
            raise ValueError(
                f"Section demand must be in the range [0.0, 1.0]; got {value!r}."
            )
        self._demand = value

    @property
    def overflow_strategies(self) -> OverflowStrategyStack:
        """Ordered overflow strategies for this section, highest priority first."""
        return self._overflow_strategies

    @overflow_strategies.setter
    def overflow_strategies(self, value: OverflowStrategyStack) -> None:
        if not isinstance(value, OverflowStrategyStack):
            raise TypeError(
                "Section overflow_strategies must be an OverflowStrategyStack "
                f"instance, got {type(value).__name__}."
            )
        self._overflow_strategies = value

    @property
    def pre_context(self) -> str:
        return ""

    @property
    def post_context(self) -> str:
        return ""

    @abstractmethod
    def body(self) -> str:
        """Build the section's main content."""

    def render(self) -> str:
        """Render the complete section by combining pre-context, body, and post-context.

        Returns an empty string when the body is empty, so that an
        unconfigured section is skipped entirely by the builder.
        """
        body = self.body()
        if not body or not body.strip():
            return ""
        parts = [self.pre_context, body, self.post_context]
        return self.separator.join(part for part in parts if part)