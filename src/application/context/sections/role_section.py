from typing import ClassVar

from src.application.context.section import Section


class RoleSection(Section):
    """Assigns the model its role."""

    default_importance: ClassVar[float] = 0.5

    def __init__(self, content: str, *, importance: float | None = None) -> None:
        super().__init__(importance=importance)
        self._content = content

    @property
    def section_type(self) -> str:
        return "ROLE"

    def body(self) -> str:
        return self._content