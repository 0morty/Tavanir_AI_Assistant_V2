import pytest

from src.domain.enums import OverflowStrategy
from src.domain.overflow_strategy_stack import OverflowStrategyStack


def test_overflow_strategy_members():
    assert OverflowStrategy.TRUNCATE.value == "truncate"
    assert OverflowStrategy.SUMMARIZE.value == "summarize"
    assert OverflowStrategy.IGNORE.value == "ignore"


def test_default_stack_uses_expected_defaults():
    stack = OverflowStrategyStack()
    assert stack.strategies == (
        OverflowStrategy.TRUNCATE,
        OverflowStrategy.IGNORE,
    )
    assert stack.restart is False
    assert stack.max_restarts == 0


def test_ordered_strategies_preserve_priority_order():
    stack = OverflowStrategyStack(
        [
            OverflowStrategy.SUMMARIZE,
            OverflowStrategy.TRUNCATE,
            OverflowStrategy.IGNORE,
        ]
    )
    assert stack.strategies == (
        OverflowStrategy.SUMMARIZE,
        OverflowStrategy.TRUNCATE,
        OverflowStrategy.IGNORE,
    )
    assert stack.strategies[0] is OverflowStrategy.SUMMARIZE


def test_strategies_are_exposed_as_immutable_tuple():
    stack = OverflowStrategyStack([OverflowStrategy.IGNORE])
    assert isinstance(stack.strategies, tuple)
    with pytest.raises(TypeError):
        stack.strategies[0] = OverflowStrategy.TRUNCATE


def test_restart_policy_is_configured():
    stack = OverflowStrategyStack(
        [OverflowStrategy.TRUNCATE], restart=True, max_restarts=2
    )
    assert stack.restart is True
    assert stack.max_restarts == 2


def test_empty_strategies_are_rejected():
    with pytest.raises(ValueError):
        OverflowStrategyStack([])


def test_non_enum_strategy_is_rejected():
    with pytest.raises(TypeError):
        OverflowStrategyStack(["truncate"])


def test_non_iterable_strategies_are_rejected():
    with pytest.raises(TypeError):
        OverflowStrategyStack(OverflowStrategy.TRUNCATE)


def test_non_bool_restart_is_rejected():
    with pytest.raises(TypeError):
        OverflowStrategyStack([OverflowStrategy.TRUNCATE], restart=1)


def test_negative_max_restarts_is_rejected():
    with pytest.raises(ValueError):
        OverflowStrategyStack([OverflowStrategy.TRUNCATE], max_restarts=-1)


def test_non_int_max_restarts_is_rejected():
    with pytest.raises(TypeError):
        OverflowStrategyStack([OverflowStrategy.TRUNCATE], max_restarts=1.5)
    with pytest.raises(TypeError):
        OverflowStrategyStack([OverflowStrategy.TRUNCATE], max_restarts=True)


def test_equality_compares_full_configuration():
    assert OverflowStrategyStack([OverflowStrategy.IGNORE]) == OverflowStrategyStack(
        [OverflowStrategy.IGNORE]
    )
    assert OverflowStrategyStack(
        [OverflowStrategy.IGNORE], restart=True, max_restarts=1
    ) == OverflowStrategyStack(
        [OverflowStrategy.IGNORE], restart=True, max_restarts=1
    )
    assert OverflowStrategyStack([OverflowStrategy.IGNORE]) != OverflowStrategyStack(
        [OverflowStrategy.TRUNCATE]
    )
    assert OverflowStrategyStack([OverflowStrategy.IGNORE]) != OverflowStrategyStack(
        [OverflowStrategy.IGNORE], restart=True
    )
    assert OverflowStrategyStack(
        [OverflowStrategy.IGNORE], restart=True
    ) != OverflowStrategyStack([OverflowStrategy.IGNORE], max_restarts=1)