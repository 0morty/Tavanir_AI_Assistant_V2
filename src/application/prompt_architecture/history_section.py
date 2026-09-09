from src.domain.entities import HistoryMessage
from src.application.prompt_architecture.prompt_section import PromptSection
from src.application.prompt_architecture.section_type import PromptSectionType


class HistorySection(PromptSection):
    """Conversation/interaction history, distinct from RAG context chunks."""

    def __init__(self, messages: list[HistoryMessage]) -> None:
        super().__init__(separator="\n\n")
        self._messages = messages

    @property
    def section_type(self) -> PromptSectionType:
        return PromptSectionType.HISTORY

    @property
    def pre_context(self) -> str:
        return "History of previous interactions:"

    def body(self) -> str:
        rendered = [f"{message.role}: {message.content}" for message in self._messages]
        return self.separator.join(rendered)