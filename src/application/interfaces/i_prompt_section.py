from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.application.dtos import SectionProcessingResult
    from src.domain.overflow_strategy_stack import OverflowStrategyStack


class IPromptSection(ABC):
    """Section identity, tuning, rendering, and complete input preparation.

    ``render`` remains the text-only API used by PromptBuilder. ``prepare``
    produces the immutable value consumed by ContextBuilder and overflow
    operations, including structured collection items where applicable.
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
    def render(self) -> str:
        """Render the complete section (framing around the body)."""

    @abstractmethod
    def prepare(self) -> SectionProcessingResult:
        """Build the complete reference-enriched input before overflow handling."""
