from typing import ClassVar

from src.application.context.section import Section


class OutputFormatSection(Section):
    """Describes the expected output format."""

    default_importance: ClassVar[float] = 0.1

    def __init__(self, content: str, *, importance: float | None = None) -> None:
        super().__init__(importance=importance)
        self._content = content

    @property
    def section_type(self) -> str:
        return "OUTPUT-FORMAT"

    def body(self) -> str:
        return self._content