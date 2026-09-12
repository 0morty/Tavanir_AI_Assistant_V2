from typing import ClassVar

from src.application.context.section import Section


class SystemOutputSection(Section):
    """System-level output expected from the model."""

    default_importance: ClassVar[float] = 0.5

    def __init__(self, content: str, *, importance: float | None = None) -> None:
        super().__init__(importance=importance)
        self._content = content

    @property
    def section_type(self) -> str:
        return "SYSTEM-OUTPUT"

    def body(self) -> str:
        return self._content