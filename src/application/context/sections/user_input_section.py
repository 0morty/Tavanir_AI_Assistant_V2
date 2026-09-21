from src.application.context.sections.referenced_section import ReferencedSection
from src.application.interfaces.i_reference_generator import IReferenceGenerator
from src.domain.context.summarizer import Summarizer
from src.domain.entities import Reference
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class UserInputSection(ReferencedSection):
    """User-provided input passed to the model."""

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
    ) -> None:
        super().__init__(
            reference=reference,
            reference_generator=reference_generator,
            importance=importance,
            demand=demand,
            default_importance=0.5,
            default_demand=0.4,
            overflow_strategies=overflow_strategies,
            summarizer=summarizer,
        )
        self._content = content

    @property
    def section_type(self) -> str:
        return "USER-INPUT"

    def body(self) -> str:
        return self._content