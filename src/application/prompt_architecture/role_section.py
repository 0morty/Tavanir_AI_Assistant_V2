from src.application.prompt_architecture.prompt_section import PromptSection
from src.application.prompt_architecture.section_type import PromptSectionType


class RoleSection(PromptSection):
    """Assigns the model its role."""

    def __init__(self, content: str) -> None:
        super().__init__()
        self._content = content

    @property
    def section_type(self) -> PromptSectionType:
        return PromptSectionType.ROLE

    def body(self) -> str:
        return self._content