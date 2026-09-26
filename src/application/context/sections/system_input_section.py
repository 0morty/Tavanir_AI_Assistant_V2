from src.application.context.sections.referenced_section import ReferencedSection
from src.application.interfaces.i_reference_generator import IReferenceGenerator
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.domain.context.summarizer import Summarizer
from src.domain.entities import Reference
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class SystemInputSection(ReferencedSection):
    """System-level input passed to the model."""

    def __init__(
        self,
        content: str,
        reference: Reference | None = None,
        reference_generator: IReferenceGenerator | None = None,
        *,
        importance: float | None = None,
        demand: float | None = None,
        overflow_strategies: OverflowStrategyStack | None = None,
        summarizer: Summarizer | None = None,
        llm_summarizer: ITextSummarizer | None = None,
    ) -> None:
        super().__init__(
            reference=reference,
            reference_generator=reference_generator,
            importance=importance,
            demand=demand,
            default_importance=0.5,
            default_demand=0.5,
            overflow_strategies=overflow_strategies,
            summarizer=summarizer,
            llm_summarizer=llm_summarizer,
        )
        self._content = content

    @property
    def section_type(self) -> str:
        return "SYSTEM-INPUT"

    def body(self) -> str:
        return self._content