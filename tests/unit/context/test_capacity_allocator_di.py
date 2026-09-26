from src.application.context.allocation.capacity_allocator import CapacityAllocator
from src.application.context.allocation.demand_allocator import DemandAllocator
from src.application.context.allocation.redistribution_allocator import (
    RedistributionAllocator,
)
from src.application.dtos import CapacityRequest


class RecordingDemandAllocator(DemandAllocator):
    """Records the demands passed to ``allocate`` and delegates to the base."""

    def __init__(self) -> None:
        self.calls: list[dict[str, float]] = []

    def allocate(self, demands, budget_tokens: int):
        self.calls.append(dict(demands))
        return super().allocate(demands, budget_tokens)


class RecordingRedistributionAllocator(RedistributionAllocator):
    """Records every redistribution pass and delegates to the base."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def redistribute(self, free_capacity_tokens: int, requests):
        self.calls.append((free_capacity_tokens, len(requests)))
        return super().redistribute(free_capacity_tokens, requests)


def _requests(*demands) -> list[CapacityRequest]:
    return [
        CapacityRequest(key=f"S{i}", demand=d, importance=0.5, needed_tokens=1000)
        for i, d in enumerate(demands)
    ]


def test_injected_demand_allocator_is_used():
    demand = RecordingDemandAllocator()
    redist = RecordingRedistributionAllocator()
    allocator = CapacityAllocator(
        demand_allocator=demand,
        redistribution_allocator=redist,
    )

    allocator.allocate(_requests(0.5, 0.5), 1000)

    assert len(demand.calls) == 1
    assert demand.calls[0] == {"S0": 0.5, "S1": 0.5}


def test_injected_redistribution_allocator_is_used():
    demand = RecordingDemandAllocator()
    redist = RecordingRedistributionAllocator()
    allocator = CapacityAllocator(
        demand_allocator=demand,
        redistribution_allocator=redist,
    )

    allocator.allocate(_requests(0.5, 0.5), 1000)

    assert len(redist.calls) == 1


def test_satisfied_sections_do_not_enter_redistribution():
    demand = RecordingDemandAllocator()
    redist = RecordingRedistributionAllocator()
    allocator = CapacityAllocator(
        demand_allocator=demand,
        redistribution_allocator=redist,
    )

    allocator.allocate([CapacityRequest(key="A", demand=0.5, importance=0.5, needed_tokens=1)], 1000)

    assert redist.calls == [(999, 0)]