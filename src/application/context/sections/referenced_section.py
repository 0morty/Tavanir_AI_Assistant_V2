from src.application.context.sections.prompt_section import PromptSection
from src.application.interfaces.i_reference_generator import IReferenceGenerator
from src.application.reference.deterministic_reference_generator import (
    DeterministicReferenceGenerator,
)
from src.domain.entities import Reference
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class ReferencedSection(PromptSection):
    """Base class for Sections that can associate a Reference with their content.

    A ``ReferencedSection`` holds a :class:`Reference` and applies its
    human-readable representation to the Section's own content. Content is
    obtained from ``body()``; subclasses never pass content explicitly.

    Subclasses own ``section_type`` and raw ``body()`` construction. The
    reference enrichment is applied automatically by ``render()`` through
    the Template Method pattern: ``compose_referenced_content()`` is the
    overridable composition hook, and the reference-resolution mechanics
    stay internal to this class.
    """

    def __init__(
        self,
        reference: Reference | None = None,
        reference_generator: IReferenceGenerator | None = None,
        *,
        separator: str = "\n\n",
        importance: float | None = None,
        demand: float | None = None,
        default_importance: float = 0.5,
        default_demand: float = 0.5,
        overflow_strategies: OverflowStrategyStack | None = None,
        default_overflow_strategies: OverflowStrategyStack | None = None,
    ) -> None:
        super().__init__(
            separator=separator,
            importance=importance,
            demand=demand,
            default_importance=default_importance,
            default_demand=default_demand,
            overflow_strategies=overflow_strategies,
            default_overflow_strategies=default_overflow_strategies,
        )
        self._reference = reference
        self._reference_generator = (
            reference_generator
            if reference_generator is not None
            else DeterministicReferenceGenerator()
        )

    @property
    def reference(self) -> Reference | None:
        """The Reference associated with this Section, if any."""
        return self._reference

    def _resolve_reference_text(self, reference: Reference) -> str:
        try:
            return reference.fluent_text()
        except NotImplementedError:
            return self._reference_generator.generate(reference)

    def append_reference(self) -> str:
        """Return the Section body enriched with its Reference text.

        The Reference text is resolved from ``body()`` content and composed
        through ``compose_referenced_content()``. Without a Reference, or
        when the Section body is empty, the content remains unchanged.
        """
        content = self.body()
        if not content or not content.strip():
            return ""
        if self._reference is None:
            return content

        reference_text = self._resolve_reference_text(self._reference)
        if not reference_text:
            return content
        return self.compose_referenced_content(reference_text, content)

    def compose_referenced_content(self, reference_text: str, content: str) -> str:
        """Compose the resolved Reference text with the Section content.

        Default composition is ``Reference Text + Content``. Subclasses may
        override this hook when their domain requires a different strategy.
        """
        return f"{reference_text}\n{content}"

    def render(self) -> str:
        """Render the Section with Reference enrichment applied to the body."""
        return self._compose(self.append_reference())