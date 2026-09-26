from dataclasses import replace

from src.application.context.sections.prompt_section import PromptSection
from src.application.dtos import SectionProcessingResult
from src.application.interfaces.i_reference_generator import IReferenceGenerator
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.application.reference.deterministic_reference_generator import (
    DeterministicReferenceGenerator,
)
from src.domain.context.summarizer import Summarizer
from src.domain.entities import Reference
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class ReferenceSupport:
    """Reference injection shared by text and collection sections."""

    def __init__(
        self,
        reference: Reference | None,
        reference_generator: IReferenceGenerator | None,
    ) -> None:
        self._reference = reference
        self._reference_generator = (
            reference_generator
            if reference_generator is not None
            else DeterministicReferenceGenerator()
        )

    @property
    def reference(self) -> Reference | None:
        return self._reference

    def _resolve_reference_text(self, reference: Reference) -> str:
        try:
            return reference.fluent_text()
        except NotImplementedError:
            return self._reference_generator.generate(reference)

    def compose_referenced_content(self, reference_text: str, content: str) -> str:
        """Place reference text immediately before the content it describes."""
        return f"{reference_text}\n{content}"

    def _with_section_reference(self, content: str) -> str:
        if not content or not content.strip() or self._reference is None:
            return content
        reference_text = self._resolve_reference_text(self._reference)
        return (
            self.compose_referenced_content(reference_text, content)
            if reference_text
            else content
        )


class ReferencedSection(PromptSection, ReferenceSupport):
    """Single-text section with reference enrichment before overflow processing."""

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
        summarizer: Summarizer | None = None,
        llm_summarizer: ITextSummarizer | None = None,
    ) -> None:
        PromptSection.__init__(
            self,
            separator=separator,
            importance=importance,
            demand=demand,
            default_importance=default_importance,
            default_demand=default_demand,
            overflow_strategies=overflow_strategies,
            default_overflow_strategies=default_overflow_strategies,
            summarizer=summarizer,
        )
        ReferenceSupport.__init__(self, reference, reference_generator)
        self._llm_summarizer = llm_summarizer

    def append_reference(self) -> str:
        """Return the single body with its reference injected."""
        return self._with_section_reference(self.body())

    def summarize(
        self,
        content: SectionProcessingResult,
        capacity_tokens: int,
    ) -> SectionProcessingResult | None:
        """Summarize the complete prepared text, including framing/reference."""
        if self._llm_summarizer is None:
            return super().summarize(content, capacity_tokens)
        if not content.content or capacity_tokens <= 0:
            return replace(content, content="")
        return replace(
            content,
            content=self._llm_summarizer.summarize(
                content.content, max_tokens=capacity_tokens
            ),
        )

    def render(self) -> str:
        return self._compose(self.append_reference())
