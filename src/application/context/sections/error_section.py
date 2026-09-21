from src.application.context.sections.prompt_section import PromptSection
from src.domain.context.summarizer import Summarizer
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class ErrorSection(PromptSection):
    """Feedback from the previous template-validation attempt.

    Carries the exact error output reported by the ``TemplateValidator`` on the
    previous generation attempt so the LLM can correct its mistake. On the
    first attempt the content is the empty string; an empty section renders as
    an empty string and is skipped by the ``PromptBuilder``.
    """

    def __init__(
        self,
        content: str = "",
        *,
        importance: float | None = None,
        demand: float | None = None,
        overflow_strategies: OverflowStrategyStack | None = None,
        summarizer: Summarizer | None = None,
    ) -> None:
        super().__init__(
            importance=importance,
            demand=demand,
            default_importance=0.3,
            default_demand=0.3,
            overflow_strategies=overflow_strategies,
            summarizer=summarizer,
        )
        self._content = content

    @property
    def section_type(self) -> str:
        return "ERROR"

    def body(self) -> str:
        return self._content