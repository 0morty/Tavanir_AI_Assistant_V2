from abc import abstractmethod

from src.application.interfaces.i_compressible_section import CompressibleSection
from src.application.interfaces.i_prompt_section import IPromptSection
from src.domain.context.overflow.summarize import SummarizeStrategy
from src.domain.context.overflow.truncate import TruncateStrategy
from src.domain.context.summarizer import Summarizer
from src.domain.context.tokenizer import Tokenizer
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class PromptSection(IPromptSection, CompressibleSection):
    """A logical section of an LLM prompt.

    ``PromptSection`` implements the
    :class:`~src.application.interfaces.i_prompt_section.IPromptSection` port
    and ships the default prompt-section behavior on top of that contract. It
    is the skeleton developers subclass to build new sections; consumer code
    (such as the ``PromptBuilder``) can depend on the port alone.

    A ``PromptSection`` is a reusable part of a prompt. The
    ``PromptBuilder`` composes ``PromptSection`` instances into an ordered
    prompt, and context construction / token allocation operate on the same
    abstraction.

    The prompt-section abstraction owns three tuning properties that are
    part of what a prompt section *is* -- not generic properties of every
    possible section:

    - ``importance`` -- the intrinsic semantic importance of the section in
      the range ``[0.0, 1.0]``; used as a weight when redistributing unused
      token capacity; **not** a token percentage.
    - ``demand`` -- the section's relative context-capacity demand in the
      range ``[0.0, 1.0]``; used to calculate the section's initial
      proportional token capacity.
    - ``overflow_strategies`` -- an :class:`OverflowStrategyStack`: the
      ordered list of overflow strategies (lower index means higher priority)
      plus the restart policy for this section.

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

    Both ``importance`` and ``demand`` of several sections are independent:
    they do not need to sum to ``1.0``, and a ``PromptSection`` never
    normalizes them or allocates capacity itself. Normalization and
    allocation are the responsibility of the context/token-allocation logic.

    ``overflow_strategies`` is the section's overflow policy. ``PromptSection``
    also implements the :class:`CompressibleSection` contract with the default
    **plain-text** interpretation of that policy: ``truncate`` applies the
    universal :class:`TruncateStrategy` to the text, ``summarize`` delegates to
    an injected :class:`Summarizer`, and ``ignore`` is not applicable to a
    single plain text (it returns ``None`` so the caller falls through to the
    next strategy). Collection-based Sections override these operations for
    their own representation -- ``ReferencedCollectionSection``, for example,
    makes ``IGNORE`` mean "drop items in order". The dispatch of an
    ``OverflowStrategy`` to one of these operations is owned by the external
    :class:`OverflowStrategyDispatcher`, never by this class.
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

    def truncate(
        self,
        content: str,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> str:
        """Reduce a plain-text ``content`` to a prefix that fits ``capacity_tokens``.

        Applies the universal truncation algorithm (:class:`TruncateStrategy`)
        to the text as-is. Already-fitting or empty content is returned
        unchanged by the strategy.
        """
        return TruncateStrategy(tokenizer).apply(content, capacity_tokens)

    def summarize(
        self,
        content: str,
        capacity_tokens: int,
        *,
        summarizer: Summarizer,
    ) -> str:
        """Compress a plain-text ``content`` through the injected ``summarizer``."""
        if not content or capacity_tokens <= 0:
            return ""
        return SummarizeStrategy(summarizer).apply(content, capacity_tokens)

    def ignore(
        self,
        content: str,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> None:
        """``IGNORE`` is not applicable to a single plain text.

        There are no items to drop, so this returns ``None`` to signal the
        caller to move on to the next strategy in the overflow stack.
        """
        return None

    def _compose(self, body: str) -> str:
        """Frame a rendered body with pre/post context, skipping empty parts.

        Returns an empty string when the body is empty, so that an
        unconfigured section is skipped entirely by the builder.
        """
        if not body or not body.strip():
            return ""
        parts = [self.pre_context, body, self.post_context]
        return self.separator.join(part for part in parts if part)

    def render(self) -> str:
        """Render the complete section by combining pre-context, body, and post-context."""
        return self._compose(self.body())