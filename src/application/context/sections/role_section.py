from src.domain.overflow_strategy_stack import OverflowStrategyStack
from src.application.interfaces import ISection


class RoleSection(ISection):
    """Assigns the model its role."""

    def __init__(
        self,
        content: str,
        *,
        importance: float | None = None,
        demand: float | None = None,
        overflow_strategies: OverflowStrategyStack | None = None,
    ) -> None:
        super().__init__(
            importance=importance,
            demand=demand,
            default_importance=0.5,
            default_demand=0.3,
            overflow_strategies=overflow_strategies,
        )
        self._content = content

    @property
    def section_type(self) -> str:
        return "ROLE"

    def body(self) -> str:
        return self._content