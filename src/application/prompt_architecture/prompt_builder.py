from collections.abc import Iterable

from src.domain.entities import Chunk, HistoryMessage
from src.application.prompt_architecture.chunks_section import ChunksSection
from src.application.prompt_architecture.history_section import HistorySection
from src.application.prompt_architecture.output_format_section import OutputFormatSection
from src.application.prompt_architecture.prompt_section import PromptSection
from src.application.prompt_architecture.role_section import RoleSection
from src.application.prompt_architecture.string_section import StringSection
from src.application.prompt_architecture.system_input_section import SystemInputSection
from src.application.prompt_architecture.system_output_section import SystemOutputSection


def _canonical_name(name: str) -> str:
    """Normalize a section name into its registry identity."""
    canonical = name.strip().upper()
    if not canonical:
        raise ValueError("Prompt section name must be a non-empty string.")
    return canonical


class PromptBuilder:
    """Composes :class:`PromptSection` instances into an ordered prompt.

    The builder relies on the ``PromptSection`` contract rather than on any
    fixed set of section types. Section identity is the string returned by
    ``PromptSection.section_type``, so new sections (REGULATION, METADATA,
    INSTRUCTIONS, ...) can be introduced without modifying central code --
    either by subclassing ``PromptSection`` or by passing a raw string to
    :meth:`set_section`.

    The default builder ships with the canonical sections:

        ROLE, HISTORY, CHUNKS, SYSTEM-INPUT, SYSTEM-OUTPUT, OUTPUT-FORMAT

    They are configured through the dedicated ``set_*`` methods. Custom
    sections are registered by name through :meth:`set_section`, which
    appends a new slot after the defaults (or replaces an already
    registered one, keeping its position).
    """

    def __init__(
        self,
        sections: Iterable[PromptSection] | None = None,
        *,
        seed_defaults: bool = True,
    ) -> None:
        self._sections: dict[str, PromptSection] = {}
        if seed_defaults:
            self.set_role("")
            self.set_history([])
            self.set_chunks([])
            self.set_system_input("")
            self.set_system_output("")
            self.set_output_format("")
        for section in sections or []:
            self.set_section(section.section_type, section)

    def set_section(self, name: str, value: str | PromptSection) -> None:
        """Register a section under ``name``.

        ``value`` may be a ``PromptSection`` instance (whose own
        ``section_type`` must match ``name``) or a raw string, which is
        wrapped in a :class:`StringSection`. An existing name is replaced
        in place; a new name appends the section to the end.
        """
        canonical = _canonical_name(name)
        if isinstance(value, PromptSection):
            if _canonical_name(value.section_type) != canonical:
                raise ValueError(
                    f"Section name {name!r} does not match the section's "
                    f"identity {value.section_type!r}."
                )
            section = value
        else:
            section = StringSection(canonical, value)
        self._sections[canonical] = section

    def add_section(self, section: PromptSection) -> None:
        """Append a section keyed by its own ``section_type``.

        Raises ``ValueError`` if that name is already registered; use
        :meth:`set_section` to replace an existing section.
        """
        canonical = _canonical_name(section.section_type)
        if canonical in self._sections:
            raise ValueError(f"A section named {canonical!r} is already registered.")
        self._sections[canonical] = section

    def get_section(self, name: str) -> PromptSection | None:
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

    def set_system_output(self, content: str) -> None:
        self.set_section("SYSTEM-OUTPUT", SystemOutputSection(content))

    def set_output_format(self, content: str) -> None:
        self.set_section("OUTPUT-FORMAT", OutputFormatSection(content))

    @property
    def sections(self) -> list[PromptSection]:
        return list(self._sections.values())

    def render(self) -> str:
        parts = []
        for section in self._sections.values():
            rendered = section.render()
            if rendered:
                parts.append(rendered)
        return "\n\n".join(parts)