from src.application.context.section import Section


class RoleSection(Section):
    """Assigns the model its role."""

    def __init__(
        self, content: str, *, importance: float | None = None, demand: float | None = None
    ) -> None:
        super().__init__(
            importance=importance,
            demand=demand,
            default_importance=0.5,
            default_demand=0.3,
        )
        self._content = content

    @property
    def section_type(self) -> str:
        return "ROLE"

    def body(self) -> str:
        return self._content