from abc import abstractmethod
from collections.abc import Callable

from src.application.interfaces.i_prompt_section import IPromptSection
from src.domain.context.overflow.summarize import SummarizeStrategy
from src.domain.context.overflow.truncate import TruncateStrategy
from src.domain.context.summarizer import Summarizer
from src.domain.context.tokenizer import Tokenizer
from src.domain.enums import OverflowStrategy
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class PromptSection(IPromptSection):
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

    ``overflow_strategies`` is the section's overflow policy. The base also
    ships the **default interpretation** of that policy: ``fit_to_capacity``
    fits a single plain-text value by walking the strategy stack in priority
    order (honouring the restart policy) and returning the first result that
    fits. Subclasses inherit this default as-is or override it when they need
    different behavior -- ``ReferencedCollectionSection`` overrides it for a
    collection of items, where ``IGNORE`` means "drop items in order".
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

    def fit_to_capacity(
        self,
        content: str,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
        summarizer: Summarizer | None = None,
    ) -> str:
        """Fit a single plain-text ``content`` into ``capacity_tokens``.

        The default overflow handling for a Section. When the content already
        fits within the capacity, it is returned unchanged. Otherwise the
        section's ``OverflowStrategyStack`` is walked in priority order,
        honouring the restart policy, and the first result that fits is
        returned. ``IGNORE`` has no meaning for a single plain text and is a
        no-op here.

        ``tokenizer`` drives token accounting; ``summarizer`` enables the
        ``SUMMARIZE`` strategy when configured.
        """
        if not content or not content.strip() or capacity_tokens <= 0:
            return ""
        if self._fits_within(content, capacity_tokens, tokenizer):
            return content
        return self._resolve_overflow(content, capacity_tokens, tokenizer, summarizer)

    def _fits_within(
        self,
        content: str,
        capacity_tokens: int,
        tokenizer: Tokenizer,
    ) -> bool:
        return tokenizer.count_tokens(content) <= capacity_tokens

    def _resolve_overflow(
        self,
        content: str,
        capacity_tokens: int,
        tokenizer: Tokenizer,
        summarizer: Summarizer | None,
        *,
        applier: Callable[
            [OverflowStrategy, str, int, Tokenizer, Summarizer | None],
            str | None,
        ]
        | None = None,
    ) -> str:
        apply = applier if applier is not None else self._apply_strategy
        stack = self.overflow_strategies
        best = content
        passes = range(stack.max_restarts + 1) if stack.restart else (0,)
        for _ in passes:
            for strategy in stack.strategies:
                result = apply(
                    strategy, content, capacity_tokens, tokenizer, summarizer
                )
                if result is None:
                    continue
                best = result
                if self._fits_within(result, capacity_tokens, tokenizer):
                    return result
        return best

    def _apply_strategy(
        self,
        strategy: OverflowStrategy,
        content: str,
        capacity_tokens: int,
        tokenizer: Tokenizer,
        summarizer: Summarizer | None,
    ) -> str | None:
        """Apply a single overflow strategy to a plain text.

        Returns ``None`` when the strategy cannot be executed for this
        content (e.g. ``SUMMARIZE`` without an injected summarizer). ``IGNORE``
        is not applicable to a single plain text and returns ``None``.
        """
        if strategy is OverflowStrategy.TRUNCATE:
            return TruncateStrategy(tokenizer).apply(content, capacity_tokens)
        if strategy is OverflowStrategy.SUMMARIZE:
            if summarizer is None:
                return None
            return SummarizeStrategy(summarizer).apply(content, capacity_tokens)
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