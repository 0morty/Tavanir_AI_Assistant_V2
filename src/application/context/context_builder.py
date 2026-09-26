from src.application.context.allocation.capacity_allocator import CapacityRequest
from src.application.dtos import ContextBuilderResult, SectionOutput
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
       exceeds its final capacity is fitted by walking its own overflow
       ``OverflowStrategyStack`` through the
       :class:`OverflowStrategyDispatcher`; a final truncation safety net
       keeps the budget guarantee.
    5. **Output** -- delegate the concatenation to
       :meth:`PromptBuilder.assemble`; the separator token cost is reserved
       out of the budget, so the prompt never exceeds ``max_tokens``.
    """

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
        capacity = dict(
            self._capacity_allocator.allocate(requests, usable_budget).capacities
        )

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
        section: CompressibleSection,
        content: str,
        capacity: int,
    ) -> str:
        """Fit ``content`` through the section's overflow chain.

        Walks the section's ``OverflowStrategyStack`` in priority order
        (honouring the restart policy), invoking each strategy through the
        :class:`OverflowStrategyDispatcher` and returning the first result that
        fits ``capacity``. ``_fit`` owns only the orchestration -- the strategy
        selection and the loop -- never the reduction itself. Mapping an
        ``OverflowStrategy`` to its ``Section`` operation
        (``truncate``/``summarize``/``ignore``) is the dispatcher's job, and
        the Section owns the actual reduction, so no strategy is ever executed
        or instantiated here directly. A final ``TRUNCATE`` safety net
        guarantees the fitted content never exceeds the capacity, even when
        the chosen strategy returns an over-capacity result (e.g. an
        ``IGNORE``-only stack); that safety net is also dispatched
        (``TRUNCATE -> section.truncate``), never executed locally.
        """
        stack = section.overflow_strategies
        best = content
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
                if result is None:
                    continue
                best = result
                if self._tokenizer.count_tokens(result) <= capacity:
                    return result
        if best and self._tokenizer.count_tokens(best) > capacity:
            truncated = self._dispatcher.apply(
                section,
                OverflowStrategy.TRUNCATE,
                best,
                capacity,
                tokenizer=self._tokenizer,
            )
            if truncated is not None:
                best = truncated
        return best