from src.domain.prompt_architecture.prompt_section import PromptSection
from src.domain.prompt_architecture.section_type import PromptSectionType


class UserInputSection(PromptSection):
    """User-provided input passed to the model."""

    def __init__(self, content: str) -> None:
        super().__init__()
        self._content = content

    @property
    def section_type(self) -> PromptSectionType:
        return PromptSectionType.USER_INPUT

    def body(self) -> str:
        return self._content