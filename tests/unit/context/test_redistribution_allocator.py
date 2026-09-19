import pytest

from src.application.context.allocation import ExpansionRequest, RedistributionAllocator


def test_zero_free_capacity_leaves_requests_untouched():
    request = ExpansionRequest(requested_tokens=100, weight=0.5)
    result = RedistributionAllocator().redistribute(0, [request])
    assert result.allocations == (request,)
    assert result.unused_capacity == 0


def test_empty_requests_leave_capacity_unused():
    result = RedistributionAllocator().redistribute(1000, [])
    assert result.allocations == ()
    assert result.unused_capacity == 1000


def test_document_example_allocates_iteratively():
    requests = [
        ExpansionRequest(requested_tokens=7000, weight=0.4),
        ExpansionRequest(requested_tokens=1000, weight=0.3),
        ExpansionRequest(requested_tokens=100, weight=0.2),
        ExpansionRequest(requested_tokens=50, weight=0.1),
    ]
    result = RedistributionAllocator().redistribute(10000, requests)

    allocations = {r.requested_tokens: r.allocated_tokens for r in result.allocations}
    assert allocations == {7000: 7000, 1000: 1000, 100: 100, 50: 50}
    assert result.unused_capacity == 1850


def test_largest_demand_section_takes_remaining_capacity():
    requests = [
        ExpansionRequest(requested_tokens=2000, weight=0.5),
        ExpansionRequest(requested_tokens=100, weight=0.5),
    ]
    result = RedistributionAllocator().redistribute(500, requests)
    allocations = {r.requested_tokens: r.allocated_tokens for r in result.allocations}
    assert allocations == {2000: 400, 100: 100}
    assert result.unused_capacity == 0


def test_allocation_never_exceeds_requested():
    requests = [
        ExpansionRequest(requested_tokens=50, weight=1.0),
    ]
    result = RedistributionAllocator().redistribute(1000, requests)
    assert result.allocations[0].allocated_tokens == 50
    assert result.unused_capacity == 950


def test_zero_weight_requests_receive_nothing():
    requests = [
        ExpansionRequest(requested_tokens=100, weight=0.0),
        ExpansionRequest(requested_tokens=100, weight=0.0),
    ]
    result = RedistributionAllocator().redistribute(500, requests)
    assert all(r.allocated_tokens == 0 for r in result.allocations)
    assert result.unused_capacity == 500


def test_preallocated_requests_only_receive_remaining_need():
    requests = [
        ExpansionRequest(
            requested_tokens=3000,
            weight=1.0,
            allocated_tokens=2500,
        ),
    ]
    result = RedistributionAllocator().redistribute(2000, requests)
    assert result.allocations[0].allocated_tokens == 3000
    assert result.unused_capacity == 1500


def test_input_requests_are_not_mutated():
    request = ExpansionRequest(requested_tokens=100, weight=0.5)
    RedistributionAllocator().redistribute(1000, [request])
    assert request.allocated_tokens == 0


def test_negative_free_capacity_is_rejected():
    with pytest.raises(ValueError):
        RedistributionAllocator().redistribute(-1, [])