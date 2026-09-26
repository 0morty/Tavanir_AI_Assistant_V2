import pytest

from src.application.context.allocation.capacity_allocator import (
    CapacityAllocator,
    CapacityRequest,
)
from src.application.context.allocation.demand_allocator import DemandAllocator
from src.application.context.allocation.redistribution_allocator import (
    RedistributionAllocator,
)


def req(key, demand=0.5, importance=0.5, needed=0) -> CapacityRequest:
    return CapacityRequest(key=key, demand=demand, importance=importance, needed_tokens=needed)


def make_capacity_allocator() -> CapacityAllocator:
    return CapacityAllocator(DemandAllocator(), RedistributionAllocator())


def test_allocate_empty_requests_returns_budget_as_unused():
    result = make_capacity_allocator().allocate([], budget_tokens=100)
    assert result.capacities == {}
    assert result.unused_tokens == 100


def test_budget_split_is_proportional_to_demand():
    result = make_capacity_allocator().allocate(
        [req("A", demand=0.5, needed=50), req("B", demand=0.5, needed=50)],
        budget_tokens=100,
    )
    assert result.capacities == {"A": 50, "B": 50}
    assert result.unused_tokens == 0


def test_under_used_share_is_given_back_to_needed_amount():
    result = make_capacity_allocator().allocate(
        [req("A", demand=0.7, needed=5), req("B", demand=0.3, importance=1.0, needed=100)],
        budget_tokens=100,
    )
    assert result.capacities == {"A": 5, "B": 95}
    assert result.unused_tokens == 0


def test_redistribution_favors_higher_importance():
    result = make_capacity_allocator().allocate(
        [
            req("A", demand=0.5, importance=1.0, needed=100),
            req("B", demand=0.1, importance=0.0, needed=100),
            req("C", demand=0.4, importance=0.0, needed=0),
        ],
        budget_tokens=100,
    )
    assert result.capacities == {"A": 90, "B": 10, "C": 0}


def test_allocation_is_capped_at_actual_need():
    result = make_capacity_allocator().allocate(
        [req("A", demand=1.0, needed=60)],
        budget_tokens=100,
    )
    assert result.capacities == {"A": 60}
    assert result.unused_tokens == 40


def test_unused_capacity_is_reported_when_no_requesters():
    result = make_capacity_allocator().allocate(
        [req("A", demand=0.5, needed=10), req("B", demand=0.5, needed=10)],
        budget_tokens=100,
    )
    assert result.capacities == {"A": 10, "B": 10}
    assert result.unused_tokens == 80


def test_zero_demand_section_receives_no_initial_capacity():
    result = make_capacity_allocator().allocate(
        [req("A", demand=0.0, needed=0), req("B", demand=1.0, needed=50)],
        budget_tokens=100,
    )
    assert result.capacities == {"A": 0, "B": 50}
    assert result.unused_tokens == 50


def test_rejects_negative_budget():
    with pytest.raises(ValueError):
        make_capacity_allocator().allocate([req("A", needed=10)], budget_tokens=-1)


def test_rejects_demand_outside_unit_range():
    with pytest.raises(ValueError):
        make_capacity_allocator().allocate([req("A", demand=1.5, needed=10)], budget_tokens=100)


def test_rejects_importance_outside_unit_range():
    with pytest.raises(ValueError):
        make_capacity_allocator().allocate(
            [req("A", importance=1.5, needed=10)], budget_tokens=100
        )


def test_rejects_duplicate_keys():
    with pytest.raises(ValueError):
        make_capacity_allocator().allocate(
            [req("A", needed=10), req("A", needed=20)], budget_tokens=100
        )


def test_rejects_negative_needed_tokens():
    with pytest.raises(ValueError):
        make_capacity_allocator().allocate([req("A", needed=-1)], budget_tokens=100)