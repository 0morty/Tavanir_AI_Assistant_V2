from src.domain.entities import HistoryMessage
from src.application.context.section import Section


class HistorySection(Section):
    """Conversation/interaction history, distinct from RAG context chunks."""

    def __init__(
        self,
        messages: list[HistoryMessage],
        *,
        importance: float | None = None,
        demand: float | None = None,
    ) -> None:
        super().__init__(
            separator="\n\n",
            importance=importance,
            demand=demand,
            default_importance=0.3,
            default_demand=0.4,
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