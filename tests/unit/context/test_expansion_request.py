import pytest

from src.application.context.allocation import ExpansionRequest


def test_holds_requested_weight_and_zero_allocation():
    request = ExpansionRequest(requested_tokens=7000, weight=0.4)
    assert request.requested_tokens == 7000
    assert request.weight == 0.4
    assert request.allocated_tokens == 0


def test_remaining_need_is_requested_minus_allocated():
    request = ExpansionRequest(requested_tokens=5000, weight=0.3, allocated_tokens=1200)
    assert request.remaining_need == 3800


def test_remaining_need_is_zero_when_satisfied():
    request = ExpansionRequest(requested_tokens=100, weight=0.2, allocated_tokens=100)
    assert request.remaining_need == 0


def test_is_immutable():
    request = ExpansionRequest(requested_tokens=10, weight=1.0)
    with pytest.raises(AttributeError):
        request.allocated_tokens = 5


def test_negative_requested_tokens_is_rejected():
    with pytest.raises(ValueError):
        ExpansionRequest(requested_tokens=-1, weight=0.5)


def test_negative_allocated_tokens_is_rejected():
    with pytest.raises(ValueError):
        ExpansionRequest(requested_tokens=10, weight=0.5, allocated_tokens=-1)


def test_allocated_above_requested_is_rejected():
    with pytest.raises(ValueError):
        ExpansionRequest(requested_tokens=10, weight=0.5, allocated_tokens=11)


def test_negative_weight_is_rejected():
    with pytest.raises(ValueError):
        ExpansionRequest(requested_tokens=10, weight=-0.1)


def test_weight_above_one_is_rejected():
    with pytest.raises(ValueError):
        ExpansionRequest(requested_tokens=10, weight=1.1)


def test_boundary_values_are_accepted():
    assert ExpansionRequest(requested_tokens=0, weight=0.0).remaining_need == 0
    assert ExpansionRequest(requested_tokens=0, weight=1.0).remaining_need == 0