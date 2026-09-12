from typing import ClassVar

from src.application.context.section import Section


class StringSection(Section):
    """Generic string-backed section identified by an arbitrary name.

    This is the escape hatch for sections that are plain text:
    ``PromptBuilder.set_section(name, content)`` wraps a raw string in a
    ``StringSection``, so developers can introduce sections such as
    ``REGULATION`` or ``METADATA`` without touching any central enum or
    subclasses.
    """

    default_importance: ClassVar[float] = 0.5

    def __init__(
        self, name: str, content: str, *, importance: float | None = None
    ) -> None:
        super().__init__(importance=importance)
        self._name = name
        self._content = content

    @property
    def section_type(self) -> str:
        return self._name

    def body(self) -> str:
        return self._content