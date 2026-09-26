from src.application.context.allocation.capacity_allocator import CapacityRequest
from src.application.dtos import (
    ContextBuilderResult,
    SectionOutput,
    SectionProcessingResult,
)
from src.application.interfaces.i_capacity_allocator import ICapacityAllocator
from src.application.interfaces.i_compressible_section import CompressibleSection
from src.application.interfaces.i_context_builder import IContextBuilder
from src.application.interfaces.i_overflow_strategy_dispatcher import (
    IOverflowStrategyDispatcher,
)
from src.application.prompt.prompt_builder import PromptBuilder
from src.domain.context.tokenizer import Tokenizer
from src.domain.enums import OverflowStrategy


class ContextBuilder(IContextBuilder):
    """Prepare, allocate, fit, and account for immutable section results."""

    def __init__(
        self,
        *,
        tokenizer: Tokenizer,
        capacity_allocator: ICapacityAllocator,
        dispatcher: IOverflowStrategyDispatcher,
    ) -> None:
        self._tokenizer = tokenizer
        self._capacity_allocator = capacity_allocator
        self._dispatcher = dispatcher

    def build(
        self,
        builder: PromptBuilder,
        max_tokens: int,
    ) -> ContextBuilderResult:
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

        # References and pre/post context are prepared before token accounting.
        prepared = {section.section_type: section.prepare() for section in sections}
        needed = {
            section_type: self._tokenizer.count_tokens(result.content)
            for section_type, result in prepared.items()
        }
        requests = [
            CapacityRequest(
                key=section.section_type,
                demand=section.demand,
                importance=section.importance,
                needed_tokens=needed[section.section_type],
            )
            for section in sections
        ]
        capacity = dict(
            self._capacity_allocator.allocate(requests, usable_budget).capacities
        )

        outputs: list[SectionOutput] = []
        for section in sections:
            section_type = section.section_type
            share = capacity[section_type]
            overflowed = needed[section_type] > share
            result = prepared[section_type]
            if overflowed:
                result = self._fit(section, result, share)
            outputs.append(
                SectionOutput(
                    section_type=section_type,
                    content=result.content,
                    requested_tokens=needed[section_type],
                    capacity_tokens=share,
                    fitted_tokens=self._tokenizer.count_tokens(result.content),
                    overflowed=overflowed,
                    items=result.items,
                )
            )

        prompt = builder.assemble(
            {output.section_type: output.content for output in outputs}
        )
        return ContextBuilderResult(
            prompt=prompt,
            sections=tuple(outputs),
            budget_tokens=max_tokens,
            total_tokens=self._tokenizer.count_tokens(prompt),
            section_separator=separator,
        )

    def _fit(
        self,
        section: CompressibleSection,
        content: SectionProcessingResult,
        capacity: int,
    ) -> SectionProcessingResult:
        """Select the first fitting transformation; enforce the section budget."""
        stack = section.overflow_strategies
        passes = range(stack.max_restarts + 1) if stack.restart else (0,)
        for _ in passes:
            for strategy in stack.strategies:
                result = self._dispatcher.apply(
                    section,
                    strategy,
                    content,
                    capacity,
                    tokenizer=self._tokenizer,
                )
                if result is not None and self._tokenizer.count_tokens(result.content) <= capacity:
                    return result

        # A collection's TRUNCATE is explicitly a no-op. Its capacity safety
        # net removes whole trailing items; single text uses real truncation.
        fallback = (
            OverflowStrategy.IGNORE
            if content.items is not None
            else OverflowStrategy.TRUNCATE
        )
        result = self._dispatcher.apply(
            section, fallback, content, capacity, tokenizer=self._tokenizer
        )
        if result is None or self._tokenizer.count_tokens(result.content) > capacity:
            raise ValueError(f"Section {section.section_type} cannot fit capacity")
        return result
