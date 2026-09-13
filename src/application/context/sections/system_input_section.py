from src.application.context.section import Section


class SystemInputSection(Section):
    """System-level input passed to the model."""

    def __init__(
        self, content: str, *, importance: float | None = None, demand: float | None = None
    ) -> None:
        super().__init__(
            importance=importance,
            demand=demand,
            default_importance=0.5,
            default_demand=0.5,
        )
        self._content = content

    @property
    def section_type(self) -> str:
        return "SYSTEM-INPUT"

    def body(self) -> str:
        return self._content