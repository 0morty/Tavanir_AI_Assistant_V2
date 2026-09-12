from src.application.prompt_architecture.prompt_section import PromptSection


class SystemInputSection(PromptSection):
    """System-level input passed to the model."""

    def __init__(self, content: str) -> None:
        super().__init__()
        self._content = content

    @property
    def section_type(self) -> str:
        return "SYSTEM-INPUT"

    def body(self) -> str:
        return self._content