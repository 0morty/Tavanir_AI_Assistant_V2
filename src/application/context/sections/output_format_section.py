from src.domain.overflow_strategy_stack import OverflowStrategyStack
from src.application.interfaces import ISection


class OutputFormatSection(ISection):
    """Describes the expected output format."""

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
            default_importance=0.1,
            default_demand=0.2,
            overflow_strategies=overflow_strategies,
        )
        self._content = content

    @property
    def section_type(self) -> str:
        return "OUTPUT-FORMAT"

    def body(self) -> str:
        return self._content