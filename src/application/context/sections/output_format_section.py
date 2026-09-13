from src.application.context.section import Section


class OutputFormatSection(Section):
    """Describes the expected output format."""

    def __init__(self, content: str, *, importance: float | None = None) -> None:
        super().__init__(importance=importance, default_importance=0.1)
        self._content = content

    @property
    def section_type(self) -> str:
        return "OUTPUT-FORMAT"

    def body(self) -> str:
        return self._content