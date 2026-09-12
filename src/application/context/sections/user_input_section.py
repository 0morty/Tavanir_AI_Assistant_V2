from typing import ClassVar

from src.application.context.section import Section


class UserInputSection(Section):
    """User-provided input passed to the model."""

    default_importance: ClassVar[float] = 0.5

    def __init__(self, content: str, *, importance: float | None = None) -> None:
        super().__init__(importance=importance)
        self._content = content

    @property
    def section_type(self) -> str:
        return "USER-INPUT"

    def body(self) -> str:
        return self._content