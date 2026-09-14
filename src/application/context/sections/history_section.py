from src.domain.entities import HistoryMessage
from src.domain.overflow_strategy_stack import OverflowStrategyStack
from src.application.interfaces import ISection


class HistorySection(ISection):
    """Conversation/interaction history, distinct from RAG context chunks."""

    def __init__(
        self,
        messages: list[HistoryMessage],
        *,
        importance: float | None = None,
        demand: float | None = None,
        overflow_strategies: OverflowStrategyStack | None = None,
    ) -> None:
        super().__init__(
            separator="\n\n",
            importance=importance,
            demand=demand,
            default_importance=0.3,
            default_demand=0.4,
            overflow_strategies=overflow_strategies,
        )
        self._messages = messages

    @property
    def section_type(self) -> str:
        return "HISTORY"

    @property
    def pre_context(self) -> str:
        return "History of previous interactions:"

    def body(self) -> str:
        rendered = [
            f"{message.role.value}: {message.content}" for message in self._messages
        ]
        return self.separator.join(rendered)