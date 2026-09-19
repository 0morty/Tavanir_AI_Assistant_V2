import pytest

from src.application.context.allocation import DemandAllocator


def test_empty_demands_yield_empty_capacities():
    assert DemandAllocator().allocate({}, 1000) == {}


def test_zero_budget_yields_zero_capacities():
    demands = {"CHUNKS": 0.5, "HISTORY": 0.4}
    assert DemandAllocator().allocate(demands, 0) == {"CHUNKS": 0, "HISTORY": 0}


def test_single_section_gets_whole_budget():
    assert DemandAllocator().allocate({"CHUNKS": 0.5}, 1000) == {"CHUNKS": 1000}


def test_allocations_sum_to_budget():
    demands = {"CHUNKS": 0.5, "HISTORY": 0.4, "ROLE": 0.3, "OUTPUT-FORMAT": 0.2}
    capacities = DemandAllocator().allocate(demands, 10000)
    assert sum(capacities.values()) == 10000
    assert set(capacities) == set(demands)


def test_proportional_split_by_normalized_demand():
    demands = {"A": 0.6, "B": 0.2}
    capacities = DemandAllocator().allocate(demands, 1000)
    assert capacities == {"A": 750, "B": 250}


def test_zero_demand_section_gets_no_initial_capacity():
    demands = {"A": 0.5, "B": 0.0}
    capacities = DemandAllocator().allocate(demands, 1000)
    assert capacities["B"] == 0
    assert capacities["A"] == 1000


def test_all_zero_demands_split_equally():
    demands = {"A": 0.0, "B": 0.0, "C": 0.0}
    capacities = DemandAllocator().allocate(demands, 100)
    assert capacities == {"A": 34, "B": 33, "C": 33}


def test_deterministic_across_calls():
    demands = {"CHUNKS": 0.5, "HISTORY": 0.4, "ROLE": 0.3}
    first = DemandAllocator().allocate(demands, 777)
    second = DemandAllocator().allocate(demands, 777)
    assert first == second


def test_negative_budget_is_rejected():
    with pytest.raises(ValueError):
        DemandAllocator().allocate({"A": 0.5}, -10)


def test_demand_below_zero_is_rejected():
    with pytest.raises(ValueError):
        DemandAllocator().allocate({"A": -0.1}, 100)


def test_demand_above_one_is_rejected():
    with pytest.raises(ValueError):
        DemandAllocator().allocate({"A": 1.1}, 100)