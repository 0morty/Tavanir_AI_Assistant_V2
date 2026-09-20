from collections.abc import Iterable, Mapping

from src.domain.entities import GenerationChunk, HistoryMessage
from src.application.interfaces import IPromptSection
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
    """Composes :class:`IPromptSection` instances into an ordered prompt.

    The builder owns exactly two concerns: the **order** of the sections and
    the **concatenation** of their already-rendered content (``assemble``).
    It does not decide how much capacity a section gets (that belongs to
    ``ContextBuilder``) and it does not render or reduce content itself (that
    belongs to the sections).

    The builder relies on the
    :class:`~src.application.interfaces.i_prompt_section.IPromptSection`
    port rather than on any fixed set of section types. Section identity
    is the string returned by ``IPromptSection.section_type``, so new
    sections (REGULATION, METADATA, INSTRUCTIONS, ...) can be introduced
    without modifying central code -- by implementing the port, typically
    through the ``PromptSection`` skeleton.

    The default builder ships with the canonical sections:

        ROLE, HISTORY, CHUNKS, SYSTEM-INPUT, USER-INPUT, OUTPUT-FORMAT

    They are configured through the dedicated ``set_*`` methods. Custom
    sections are registered as ``IPromptSection`` instances (usually
    ``PromptSection`` subclasses) through :meth:`set_section`, which appends a
    new slot after the defaults (or replaces an already registered one,
    keeping its position).
    """

    SECTION_SEPARATOR = "\n\n"

    def __init__(
        self,
        sections: Iterable[IPromptSection] | None = None,
        *,
        seed_defaults: bool = True,
    ) -> None:
        self._sections: dict[str, IPromptSection] = {}
        if seed_defaults:
            self.set_role("")
            self.set_history([])
            self.set_chunks([])
            self.set_system_input("")
            self.set_user_input("")
            self.set_output_format("")
        for section in sections or []:
            self.set_section(section.section_type, section)

    def set_section(self, name: str, value: IPromptSection) -> None:
        """Register a section under ``name``.

        ``value`` must be an ``IPromptSection`` instance whose own
        ``section_type`` matches ``name``. An existing name is replaced
        in place; a new name appends the section to the end.
        """
        canonical = _canonical_name(name)
        if not isinstance(value, IPromptSection):
            raise TypeError(
                f"value must be an IPromptSection instance, got {type(value).__name__}."
            )
        if _canonical_name(value.section_type) != canonical:
            raise ValueError(
                f"Section name {name!r} does not match the section's "
                f"identity {value.section_type!r}."
            )
        self._sections[canonical] = value

    def add_section(self, section: IPromptSection) -> None:
        """Append a section keyed by its own ``section_type``.

        Raises ``ValueError`` if that name is already registered; use
        :meth:`set_section` to replace an existing section.
        """
        canonical = _canonical_name(section.section_type)
        if canonical in self._sections:
            raise ValueError(f"A section named {canonical!r} is already registered.")
        self._sections[canonical] = section

    def get_section(self, name: str) -> IPromptSection | None:
        """Return the section registered under ``name``, or ``None``."""
        return self._sections.get(_canonical_name(name))

    def has_section(self, name: str) -> bool:
        """Return whether a section is registered under ``name``."""
        return _canonical_name(name) in self._sections

    def set_role(self, content: str) -> None:
        self.set_section("ROLE", RoleSection(content))

    def set_history(self, messages: list[HistoryMessage]) -> None:
        self.set_section("HISTORY", HistorySection(messages))

    def set_chunks(self, chunks: list[GenerationChunk]) -> None:
        self.set_section("CHUNKS", ChunksSection(chunks))

    def set_system_input(self, content: str) -> None:
        self.set_section("SYSTEM-INPUT", SystemInputSection(content))

    def set_user_input(self, content: str) -> None:
        self.set_section("USER-INPUT", UserInputSection(content))

    def set_output_format(self, content: str) -> None:
        self.set_section("OUTPUT-FORMAT", OutputFormatSection(content))

    @property
    def sections(self) -> list[IPromptSection]:
        return list(self._sections.values())

    def assemble(self, rendered: Mapping[str, str]) -> str:
        """Concatenate already-rendered section content into the final prompt.

        Iterates the registered sections **in their registration order** and
        joins each section's content from ``rendered`` (keyed by
        ``section_type``) with :attr:`SECTION_SEPARATOR`. Missing or empty
        entries are skipped, so callers may pass content for a subset of the
        registered sections.
        """
        parts = []
        for section_type in self._sections:
            content = rendered.get(section_type)
            if content:
                parts.append(content)
        return self.SECTION_SEPARATOR.join(parts)

    def render(self) -> str:
        """Render every section and assemble the result in registration order.

        Each section renders its own content (including reference handling);
        this method only invokes them and delegates the concatenation to
        :meth:`assemble`.
        """
        return self.assemble(
            {
                section.section_type: section.render()
                for section in self._sections.values()
            }
        )