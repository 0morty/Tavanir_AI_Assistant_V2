from src.application.prompt_architecture.prompt_section import PromptSection
from src.application.prompt_architecture.section_type import PromptSectionType


class OutputFormatSection(PromptSection):
    """Describes the expected output format."""

    def __init__(self, content: str) -> None:
        super().__init__()
        self._content = content

    @property
    def section_type(self) -> PromptSectionType:
        return PromptSectionType.OUTPUT_FORMAT

    def body(self) -> str:
        return self._content