from abc import ABC, abstractmethod

from src.domain.context.summarizer import Summarizer
from src.domain.context.tokenizer import Tokenizer
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class IPromptSection(ABC):
    """Pure interface (port) every prompt section must satisfy.

    ``IPromptSection`` declares the prompt-section contract only -- no state
    and no default behavior. The ``PromptSection`` skeleton
    (``src/application/context/sections/prompt_section.py``) implements this
    port and ships the default prompt-section behavior on top of the
    contract: the tuning properties with validation, the optional pre/post
    context framing, and the default overflow interpretation via
    ``fit_to_capacity``.

    Developers building a new section subclass the ``PromptSection`` skeleton
    to inherit the defaults; they only need to provide ``section_type`` and
    ``body()``. Code that merely *consumes* sections (such as the
    ``PromptBuilder``) can depend on this port alone.
    """

    @property
    @abstractmethod
    def section_type(self) -> str:
        """Identity/name of this section, e.g. "HISTORY" or "CHUNKS"."""

    @property
    @abstractmethod
    def importance(self) -> float:
        """Intrinsic semantic importance in the range ``[0.0, 1.0]``."""

    @property
    @abstractmethod
    def demand(self) -> float:
        """Relative context-capacity demand in the range ``[0.0, 1.0]``."""

    @property
    @abstractmethod
    def overflow_strategies(self) -> OverflowStrategyStack:
        """Ordered overflow strategies for this section, highest priority first."""

    @property
    @abstractmethod
    def pre_context(self) -> str:
        """Text rendered above the body, or the empty string."""

    @property
    @abstractmethod
    def post_context(self) -> str:
        """Text rendered below the body, or the empty string."""

    @abstractmethod
    def body(self) -> str:
        """Return the section's main content."""

    @abstractmethod
    def fit_to_capacity(
        self,
        content: str,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
        summarizer: Summarizer | None = None,
    ) -> str:
        """Fit ``content`` into ``capacity_tokens`` per the section's overflow policy.

        ``tokenizer`` drives token accounting; ``summarizer`` enables the
        ``SUMMARIZE`` strategy when configured.
        """

    @abstractmethod
    def render(self) -> str:
        """Render the complete section (framing around the body)."""