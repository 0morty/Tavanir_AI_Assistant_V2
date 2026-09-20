from dataclasses import dataclass

from src.application.context.allocation.capacity_allocator import (
    CapacityAllocator,
    CapacityRequest,
)
from src.application.interfaces import IPromptSection
from src.application.prompt.prompt_builder import PromptBuilder
from src.domain.context.overflow.truncate import TruncateStrategy
from src.domain.context.summarizer import Summarizer
from src.domain.context.tokenizer import Tokenizer


@dataclass(frozen=True)
class SectionOutput:
    """Per-section result after budgeting, reference handling, and overflow fitting."""

    section_type: str
    content: str
    requested_tokens: int
    capacity_tokens: int
    fitted_tokens: int
    overflowed: bool


@dataclass(frozen=True)
class ContextBuilderResult:
    """Final rendered prompt plus per-section accounting."""

    prompt: str
    sections: tuple[SectionOutput, ...]
    budget_tokens: int
    total_tokens: int


class ContextBuilder:
    """Assemble a token-budgeted prompt from a :class:`PromptBuilder`'s sections.

    ``ContextBuilder`` orchestrates context-capacity management. It does not
    own the allocation policy (that is ``CapacityAllocator``), the section
    ordering/concatenation (that is ``PromptBuilder``), or content selection
    (that is the sections). The pipeline is:

    1. **Append sections** -- collect the registered sections (in the
       builder's order).
    2. **Calculate each section budget** -- delegate the initial capacity
       split by ``demand`` and the token-scarcity redistribution by
       ``importance`` to :class:`CapacityAllocator`.
    3. **Handle reference** -- render every section; ``ReferencedSection``
       resolves and composes its reference text into the content, so the
       reference counts toward the section's tokens.
    4. **Summarize/Truncate/Ignore** -- a section whose rendered content
       exceeds its final capacity is fitted through its own overflow
       ``OverflowStrategyStack``; a final truncation safety net keeps the
       budget guarantee.
    5. **Output** -- delegate the concatenation to
       :meth:`PromptBuilder.assemble`; the separator token cost is reserved
       out of the budget, so the prompt never exceeds ``max_tokens``.
    """

    def __init__(
        self,
        *,
        tokenizer: Tokenizer,
        summarizer: Summarizer | None = None,
    ) -> None:
        self._tokenizer = tokenizer
        self._summarizer = summarizer

    def build(
        self,
        builder: PromptBuilder,
        max_tokens: int,
    ) -> ContextBuilderResult:
        """Run the pipeline over ``builder``'s sections under ``max_tokens``."""
        if max_tokens < 0:
            raise ValueError("max_tokens must be non-negative")

        sections = list(builder.sections)
        if not sections:
            return ContextBuilderResult("", (), max_tokens, 0)

        separator = builder.SECTION_SEPARATOR
        separator_reservation = (len(sections) - 1) * self._tokenizer.count_tokens(
            separator
        )
        usable_budget = max(0, max_tokens - separator_reservation)

        # Steps 1 + 3: append + render (reference handled inside render()).
        rendered: dict[str, str] = {}
        needed: dict[str, int] = {}
        for section in sections:
            content = section.render()
            rendered[section.section_type] = content
            needed[section.section_type] = self._tokenizer.count_tokens(content)

        # Steps 2 + 4: budget by demand, token scarcity by importance.
        requests = [
            CapacityRequest(
                key=section.section_type,
                demand=section.demand,
                importance=section.importance,
                needed_tokens=needed[section.section_type],
            )
            for section in sections
        ]
        capacity = dict(CapacityAllocator().allocate(requests, usable_budget).capacities)

        # Step 5: overflow per section.
        outputs: list[SectionOutput] = []
        for section in sections:
            section_type = section.section_type
            share = capacity[section_type]
            overflowed = needed[section_type] > share
            content = rendered[section_type]
            if overflowed:
                content = self._fit(section, content, share)
            outputs.append(
                SectionOutput(
                    section_type=section_type,
                    content=content,
                    requested_tokens=needed[section_type],
                    capacity_tokens=share,
                    fitted_tokens=self._tokenizer.count_tokens(content),
                    overflowed=overflowed,
                )
            )

        # Step 6: output -- delegate ordering + concatenation to the builder.
        prompt = builder.assemble(
            {output.section_type: output.content for output in outputs}
        )
        return ContextBuilderResult(
            prompt=prompt,
            sections=tuple(outputs),
            budget_tokens=max_tokens,
            total_tokens=self._tokenizer.count_tokens(prompt),
        )

    def _fit(
        self,
        section: IPromptSection,
        content: str,
        capacity: int,
    ) -> str:
        """Fit ``content`` through the section's overflow chain.

        The section owns the default strategy-stack execution via
        ``fit_to_capacity`` (``Summarize`` when a summarizer is injected,
        ``Truncate``, ``Ignore``). A final truncation safety net guarantees
        the fitted content never exceeds the capacity, even when the chosen
        strategy returns an over-capacity result (e.g. an ``IGNORE``-only
        stack or a lazy summarizer).
        """
        fitted = section.fit_to_capacity(
            content,
            capacity,
            tokenizer=self._tokenizer,
            summarizer=self._summarizer,
        )
        if fitted and self._tokenizer.count_tokens(fitted) > capacity:
            fitted = TruncateStrategy(self._tokenizer).apply(fitted, capacity)
        return fitted