from src.application.prompt_architecture.prompt_section import PromptSection


class RoleSection(PromptSection):
    """Assigns the model its role."""

    def __init__(self, content: str) -> None:
        super().__init__()
        self._content = content

    @property
    def section_type(self) -> str:
        return "ROLE"

    def body(self) -> str:
        return self._content