from abc import abstractmethod
from dataclasses import replace

from src.application.dtos import SectionProcessingResult
from src.application.interfaces.i_compressible_section import CompressibleSection
from src.application.interfaces.i_prompt_section import IPromptSection
from src.domain.context.overflow.summarize import SummarizeStrategy
from src.domain.context.overflow.truncate import TruncateStrategy
from src.domain.context.summarizer import Summarizer
from src.domain.context.tokenizer import Tokenizer
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class PromptSection(IPromptSection, CompressibleSection):
    """Base section with tuning, rendering, and single-text transformations.

    ``prepare`` captures the complete rendered input before ContextBuilder
    allocates tokens. Overflow operations return new SectionProcessingResult
    values and leave the source section untouched. Reference-aware text
    sections specialize rendering; collection sections specialize all three
    overflow operations without inheriting single-text semantics.
    """

    def __init__(
        self,
        separator: str = "\n\n",
        importance: float | None = None,
        demand: float | None = None,
        default_importance: float = 0.5,
        default_demand: float = 0.5,
        overflow_strategies: OverflowStrategyStack | None = None,
        default_overflow_strategies: OverflowStrategyStack | None = None,
        summarizer: Summarizer | None = None,
    ) -> None:
        self.separator = separator
        self._summarizer = summarizer
        self.importance = default_importance if importance is None else importance
        self.demand = default_demand if demand is None else demand
        resolved_default = (
            default_overflow_strategies
            if default_overflow_strategies is not None
            else OverflowStrategyStack()
        )
        self.overflow_strategies = (
            resolved_default if overflow_strategies is None else overflow_strategies
        )

    @property
    @abstractmethod
    def section_type(self) -> str:
        """Identity/name of this section, e.g. "HISTORY" or "CHUNKS"."""

    @property
    def importance(self) -> float:
        """Intrinsic semantic importance used when redistributing unused capacity."""
        return self._importance

    @importance.setter
    def importance(self, value: float) -> None:
        if not 0.0 <= value <= 1.0:
            raise ValueError(
                f"Section importance must be in the range [0.0, 1.0]; got {value!r}."
            )
        self._importance = value

    @property
    def demand(self) -> float:
        """Relative context-capacity demand used for the initial token capacity."""
        return self._demand

    @demand.setter
    def demand(self, value: float) -> None:
        if not 0.0 <= value <= 1.0:
            raise ValueError(
                f"Section demand must be in the range [0.0, 1.0]; got {value!r}."
            )
        self._demand = value

    @property
    def overflow_strategies(self) -> OverflowStrategyStack:
        """Ordered overflow strategies for this section, highest priority first."""
        return self._overflow_strategies

    @overflow_strategies.setter
    def overflow_strategies(self, value: OverflowStrategyStack) -> None:
        if not isinstance(value, OverflowStrategyStack):
            raise TypeError(
                "Section overflow_strategies must be an OverflowStrategyStack "
                f"instance, got {type(value).__name__}."
            )
        self._overflow_strategies = value

    @property
    def pre_context(self) -> str:
        return ""

    @property
    def post_context(self) -> str:
        return ""

    @abstractmethod
    def body(self) -> str:
        """Build the section's main content."""

    def truncate(
        self,
        content: SectionProcessingResult,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> SectionProcessingResult:
        """Truncate the complete prepared text without changing this section."""
        return replace(
            content,
            content=TruncateStrategy(tokenizer).apply(content.content, capacity_tokens),
        )

    def summarize(
        self,
        content: SectionProcessingResult,
        capacity_tokens: int,
    ) -> SectionProcessingResult | None:
        """Summarize the complete prepared text when a summarizer is present."""
        if self._summarizer is None:
            return None
        if not content.content or capacity_tokens <= 0:
            return replace(content, content="")
        return replace(
            content,
            content=SummarizeStrategy(self._summarizer).apply(
                content.content, capacity_tokens
            ),
        )

    def ignore(
        self,
        content: SectionProcessingResult,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> None:
        """Single text has no trailing items to drop."""
        return None

    def _compose(self, body: str) -> str:
        """Frame a rendered body with pre/post context, skipping empty parts.

        Returns an empty string when the body is empty, so that an
        unconfigured section is skipped entirely by the builder.
        """
        if not body or not body.strip():
            return ""
        parts = [self.pre_context, body, self.post_context]
        return self.separator.join(part for part in parts if part)

    def render(self) -> str:
        """Render the complete section by combining pre-context, body, and post-context."""
        return self._compose(self.body())
    def prepare(self) -> SectionProcessingResult:
        """Prepare the full section text, including its configured framing."""
        return SectionProcessingResult(content=self.render())
