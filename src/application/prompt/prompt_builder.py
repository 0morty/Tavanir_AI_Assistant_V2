from collections.abc import Iterable

from src.domain.entities import Chunk, HistoryMessage
from src.application.interfaces import ISection
from src.application.context.sections.chunks_section import ChunksSection
from src.application.context.sections.history_section import HistorySection
from src.application.context.sections.output_format_section import OutputFormatSection
from src.application.context.sections.role_section import RoleSection
from src.application.context.sections.system_input_section import SystemInputSection
from src.application.context.sections.user_input_section import UserInputSection


def _canonical_name(name: str) -> str:
    """Normalize a section name into its registry identity."""
    canonical = name.strip().upper()
    if not canonical:
        raise ValueError("Section name must be a non-empty string.")
    return canonical


class PromptBuilder:
    """Composes :class:`ISection` instances into an ordered prompt.

    The builder relies on the :class:`~src.application.interfaces.i_section.ISection`
    contract rather than on any fixed set of section types. Section identity
    is the string returned by ``ISection.section_type``, so new sections
    (REGULATION, METADATA, INSTRUCTIONS, ...) can be introduced without
    modifying central code -- by subclassing ``ISection``.

    The default builder ships with the canonical sections:

        ROLE, HISTORY, CHUNKS, SYSTEM-INPUT, USER-INPUT, OUTPUT-FORMAT

    They are configured through the dedicated ``set_*`` methods. Custom
    sections are registered with an instance of a developer-designed
    ``ISection`` subclass through :meth:`set_section`, which appends a new
    slot after the defaults (or replaces an already registered one,
    keeping its position).
    """

    def __init__(
        self,
        sections: Iterable[ISection] | None = None,
        *,
        seed_defaults: bool = True,
    ) -> None:
        self._sections: dict[str, ISection] = {}
        if seed_defaults:
            self.set_role("")
            self.set_history([])
            self.set_chunks([])
            self.set_system_input("")
            self.set_user_input("")
            self.set_output_format("")
        for section in sections or []:
            self.set_section(section.section_type, section)

    def set_section(self, name: str, value: ISection) -> None:
        """Register a section under ``name``.

        ``value`` must be an ``ISection`` instance whose own
        ``section_type`` matches ``name``. An existing name is replaced
        in place; a new name appends the section to the end.
        """
        canonical = _canonical_name(name)
        if not isinstance(value, ISection):
            raise TypeError(
                f"value must be a Section instance, got {type(value).__name__}."
            )
        if _canonical_name(value.section_type) != canonical:
            raise ValueError(
                f"Section name {name!r} does not match the section's "
                f"identity {value.section_type!r}."
            )
        self._sections[canonical] = value

    def add_section(self, section: ISection) -> None:
        """Append a section keyed by its own ``section_type``.

        Raises ``ValueError`` if that name is already registered; use
        :meth:`set_section` to replace an existing section.
        """
        canonical = _canonical_name(section.section_type)
        if canonical in self._sections:
            raise ValueError(f"A section named {canonical!r} is already registered.")
        self._sections[canonical] = section

    def get_section(self, name: str) -> ISection | None:
        """Return the section registered under ``name``, or ``None``."""
        return self._sections.get(_canonical_name(name))

    def has_section(self, name: str) -> bool:
        """Return whether a section is registered under ``name``."""
        return _canonical_name(name) in self._sections

    def set_role(self, content: str) -> None:
        self.set_section("ROLE", RoleSection(content))

    def set_history(self, messages: list[HistoryMessage]) -> None:
        self.set_section("HISTORY", HistorySection(messages))

    def set_chunks(self, chunks: list[Chunk]) -> None:
        self.set_section("CHUNKS", ChunksSection(chunks))

    def set_system_input(self, content: str) -> None:
        self.set_section("SYSTEM-INPUT", SystemInputSection(content))

    def set_user_input(self, content: str) -> None:
        self.set_section("USER-INPUT", UserInputSection(content))

    def set_output_format(self, content: str) -> None:
        self.set_section("OUTPUT-FORMAT", OutputFormatSection(content))

    @property
    def sections(self) -> list[ISection]:
        return list(self._sections.values())

    def render(self) -> str:
        parts = []
        for section in self._sections.values():
            rendered = section.render()
            if rendered:
                parts.append(rendered)
        return "\n\n".join(parts)