from collections.abc import Sequence

from src.domain.enums import OverflowStrategy


class OverflowStrategyStack:
    """Ordered overflow-strategy configuration plus an optional restart policy.

    ``strategies`` is an ordered list of :class:`~src.domain.enums.OverflowStrategy`
    values; a lower index means a higher priority, so ``strategies[0]`` is tried
    before ``strategies[1]``. ``restart`` states whether, after every strategy in
    the sequence has been exhausted, the sequence may restart from the beginning,
    and ``max_restarts`` bounds how many times it may restart.

    This object is pure configuration/state: it never executes a strategy,
    decides success/failure, or runs retry/restart loops.
    """

    DEFAULT_STRATEGIES: tuple[OverflowStrategy, ...] = (
        OverflowStrategy.TRUNCATE,
        OverflowStrategy.IGNORE,
    )
    DEFAULT_RESTART = False
    DEFAULT_MAX_RESTARTS = 0

    def __init__(
        self,
        strategies: Sequence[OverflowStrategy] | None = None,
        *,
        restart: bool = False,
        max_restarts: int = 0,
    ) -> None:
        resolved = self.DEFAULT_STRATEGIES if strategies is None else tuple(strategies)
        if not resolved:
            raise ValueError("OverflowStrategyStack requires at least one strategy.")
        for strategy in resolved:
            if not isinstance(strategy, OverflowStrategy):
                raise TypeError(
                    f"Each strategy must be an OverflowStrategy member; "
                    f"got {strategy!r}."
                )
        if not isinstance(restart, bool):
            raise TypeError(
                f"restart must be a bool; got {type(restart).__name__}."
            )
        if isinstance(max_restarts, bool) or not isinstance(max_restarts, int):
            raise TypeError(
                f"max_restarts must be an int; got {type(max_restarts).__name__}."
            )
        if max_restarts < 0:
            raise ValueError(f"max_restarts must be >= 0; got {max_restarts}.")
        self._strategies = resolved
        self._restart = restart
        self._max_restarts = max_restarts

    @property
    def strategies(self) -> tuple[OverflowStrategy, ...]:
        """Ordered strategies; a lower index means a higher priority."""
        return self._strategies

    @property
    def restart(self) -> bool:
        """Whether the sequence may restart after all strategies are exhausted."""
        return self._restart

    @property
    def max_restarts(self) -> int:
        """How many times the sequence may restart."""
        return self._max_restarts

    def __repr__(self) -> str:
        return (
            "OverflowStrategyStack("
            f"strategies={list(self._strategies)!r}, "
            f"restart={self._restart!r}, "
            f"max_restarts={self._max_restarts!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, OverflowStrategyStack):
            return NotImplemented
        return (
            self._strategies == other._strategies
            and self._restart == other._restart
            and self._max_restarts == other._max_restarts
        )