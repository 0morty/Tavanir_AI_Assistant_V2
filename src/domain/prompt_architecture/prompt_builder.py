from typing import Iterable

from src.domain.prompt_architecture.prompt_section import PromptSection


class PromptBuilder:
    """Composes and renders generic :class:`PromptSection` instances.

    The builder is deliberately unaware of each section's implementation:
    it only relies on the ``PromptSection.render()`` contract, so new
    section types can be added without touching this class.
    """

    def __init__(self, sections: Iterable[PromptSection] | None = None) -> None:
        self._sections: list[PromptSection] = list(sections or [])

    def add_section(self, section: PromptSection) -> None:
        self._sections.append(section)

    @property
    def sections(self) -> list[PromptSection]:
        return list(self._sections)

    def render(self) -> str:
        return "\n\n".join(section.render() for section in self._sections)