from src.application.prompt_architecture.prompt_section import PromptSection


class OutputFormatSection(PromptSection):
    """Describes the expected output format."""

    def __init__(self, content: str) -> None:
        super().__init__()
        self._content = content

    @property
    def section_type(self) -> str:
        return "OUTPUT-FORMAT"

    def body(self) -> str:
        return self._content