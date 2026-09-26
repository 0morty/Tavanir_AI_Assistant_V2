import pytest

from src.application.context.allocation.capacity_allocator import CapacityAllocator
from src.application.context.allocation.demand_allocator import DemandAllocator
from src.application.context.allocation.redistribution_allocator import (
    RedistributionAllocator,
)
from src.application.context.context_builder import ContextBuilder
from src.application.context.overflow_strategy_dispatcher import (
    OverflowStrategyDispatcher,
)
from src.application.context.sections import PromptSection
from src.application.prompt import PromptBuilder
from src.domain.context.summarizer import Summarizer
from src.domain.context.tokenizer import Tokenizer
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class FakeTokenizer(Tokenizer):
    """Char-based tokenizer: every character counts as one token."""

    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        return [(i, (i, i + 1)) for i in range(len(text))]

    def count_tokens(self, text: str) -> int:
        return len(text)


class TextSection(PromptSection):
    """Plain-text section with a per-instance identity."""

    def __init__(
        self,
        name: str,
        content: str,
        *,
        importance: float | None = None,
        demand: float | None = None,
        default_importance: float = 0.5,
        default_demand: float = 0.5,
        overflow_strategies: OverflowStrategyStack | None = None,
        summarizer: Summarizer | None = None,
    ) -> None:
        super().__init__(
            importance=importance,
            demand=demand,
            default_importance=default_importance,
            default_demand=default_demand,
            overflow_strategies=overflow_strategies,
            summarizer=summarizer,
        )
        self._name = name
        self._content = content

    @property
    def section_type(self) -> str:
        return self._name

    def body(self) -> str:
        return self._content


class RecordingCapacityAllocator(CapacityAllocator):
    """Records the requests passed to ``allocate`` and delegates to the base."""

    def __init__(self) -> None:
        super().__init__(DemandAllocator(), RedistributionAllocator())
        self.calls: list[int] = []

    def allocate(self, requests, budget_tokens: int):
        self.calls.append(budget_tokens)
        return super().allocate(requests, budget_tokens)


class RecordingDispatcher(OverflowStrategyDispatcher):
    """Records every strategy application and delegates to the base."""

    def __init__(self) -> None:
        self.applications: list[str] = []

    def apply(self, section, strategy, content, capacity_tokens, **kwargs):
        self.applications.append(strategy.name)
        return super().apply(section, strategy, content, capacity_tokens, **kwargs)


def make_builder(section: PromptSection) -> PromptBuilder:
    builder = PromptBuilder(seed_defaults=False)
    builder.set_section(section.section_type, section)
    return builder


def test_injected_capacity_allocator_is_used():
    allocator = RecordingCapacityAllocator()
    builder = ContextBuilder(
        tokenizer=FakeTokenizer(),
        capacity_allocator=allocator,
        dispatcher=OverflowStrategyDispatcher(),
    )
    result = builder.build(make_builder(TextSection("A", "abc")), max_tokens=100)

    assert allocator.calls == [100]
    assert result.total_tokens == 3


def test_injected_dispatcher_is_used_on_overflow():
    dispatcher = RecordingDispatcher()
    builder = ContextBuilder(
        tokenizer=FakeTokenizer(),
        capacity_allocator=CapacityAllocator(DemandAllocator(), RedistributionAllocator()),
        dispatcher=dispatcher,
    )
    result = builder.build(make_builder(TextSection("A", "x" * 100)), max_tokens=50)

    assert result.sections[0].overflowed is True
    assert dispatcher.applications


def test_missing_collaborators_are_rejected():
    with pytest.raises(TypeError):
        ContextBuilder(tokenizer=FakeTokenizer())
    with pytest.raises(TypeError):
        ContextBuilder(
            tokenizer=FakeTokenizer(),
            capacity_allocator=CapacityAllocator(
                DemandAllocator(), RedistributionAllocator()
            ),
        )