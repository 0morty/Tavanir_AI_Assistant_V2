from collections.abc import Callable

from src.application.interfaces import ISection
from src.application.interfaces.i_reference_generator import IReferenceGenerator
from src.application.reference.deterministic_reference_generator import (
    DeterministicReferenceGenerator,
)
from src.domain.context.overflow.summarize import SummarizeStrategy
from src.domain.context.overflow.truncate import TruncateStrategy
from src.domain.context.summarizer import Summarizer
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import Reference
from src.domain.enums import OverflowStrategy
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class ReferencedSection(ISection):
    """Base class for Sections that can associate a Reference with their content.

    A ``ReferencedSection`` holds a :class:`Reference` and applies its
    human-readable representation to the Section's own content. Content is
    obtained from ``body()``; subclasses never pass content explicitly.

    Subclasses own ``section_type`` and raw ``body()`` construction. The
    reference enrichment is applied automatically by ``render()`` through
    the Template Method pattern: ``compose_referenced_content()`` is the
    overridable composition hook, and the reference-resolution mechanics
    stay internal to this class.
    """

    def __init__(
        self,
        reference: Reference | None = None,
        reference_generator: IReferenceGenerator | None = None,
        *,
        separator: str = "\n\n",
        importance: float | None = None,
        demand: float | None = None,
        default_importance: float = 0.5,
        default_demand: float = 0.5,
        overflow_strategies: OverflowStrategyStack | None = None,
        default_overflow_strategies: OverflowStrategyStack | None = None,
    ) -> None:
        super().__init__(
            separator=separator,
            importance=importance,
            demand=demand,
            default_importance=default_importance,
            default_demand=default_demand,
            overflow_strategies=overflow_strategies,
            default_overflow_strategies=default_overflow_strategies,
        )
        self._reference = reference
        self._reference_generator = (
            reference_generator
            if reference_generator is not None
            else DeterministicReferenceGenerator()
        )

    @property
    def reference(self) -> Reference | None:
        """The Reference associated with this Section, if any."""
        return self._reference

    def _resolve_reference_text(self, reference: Reference) -> str:
        try:
            return reference.fluent_text()
        except NotImplementedError:
            return self._reference_generator.generate(reference)

    def append_reference(self) -> str:
        """Return the Section body enriched with its Reference text.

        The Reference text is resolved from ``body()`` content and composed
        through ``compose_referenced_content()``. Without a Reference, or
        when the Section body is empty, the content remains unchanged.
        """
        content = self.body()
        if not content or not content.strip():
            return ""
        if self._reference is None:
            return content

        reference_text = self._resolve_reference_text(self._reference)
        if not reference_text:
            return content
        return self.compose_referenced_content(reference_text, content)

    def compose_referenced_content(self, reference_text: str, content: str) -> str:
        """Compose the resolved Reference text with the Section content.

        Default composition is ``Reference Text + Content``. Subclasses may
        override this hook when their domain requires a different strategy.
        """
        return f"{reference_text}\n{content}"

    def fit_to_capacity(
        self,
        content: str,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
        summarizer: Summarizer | None = None,
    ) -> str:
        """Fit a single plain-text ``content`` into ``capacity_tokens``.

        The default overflow handling for non-collection Sections. When the
        content already fits within the capacity, it is returned unchanged.
        Otherwise the Section's ``OverflowStrategyStack`` is walked in
        priority order, honouring the restart policy, and the first result
        that fits is returned. ``IGNORE`` has no meaning for a single plain
        text and is a no-op here.

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

    def render(self) -> str:
        """Render the Section with Reference enrichment applied to the body.

        Returns an empty string when the enriched body is empty, so that an
        unconfigured Section is skipped entirely by the builder.
        """
        body = self.append_reference()
        if not body or not body.strip():
            return ""
        parts = [self.pre_context, body, self.post_context]
        return self.separator.join(part for part in parts if part)