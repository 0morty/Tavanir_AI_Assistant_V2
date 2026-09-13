from src.application.context.section import Section


class RoleSection(Section):
    """Assigns the model its role."""

    def __init__(self, content: str, *, importance: float | None = None) -> None:
        super().__init__(importance=importance, default_importance=0.5)
        self._content = content

    @property
    def section_type(self) -> str:
        return "ROLE"

    def body(self) -> str:
        return self._content