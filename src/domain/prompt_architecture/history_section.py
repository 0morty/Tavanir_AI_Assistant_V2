from src.domain.prompt_architecture.prompt_section import PromptSection
from src.domain.prompt_architecture.section_type import PromptSectionType


class HistorySection(PromptSection):
    """Conversation/interaction history, distinct from RAG context chunks."""

    def __init__(self, entries: list[str]) -> None:
        super().__init__(separator="\n\n")
        self._entries = entries

    @property
    def section_type(self) -> PromptSectionType:
        return PromptSectionType.HISTORY

    @property
    def pre_context(self) -> str:
        return "History of previous interactions:"

    def body(self) -> str:
        return self.separator.join(self._entries)