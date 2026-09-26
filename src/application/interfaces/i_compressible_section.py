from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.application.dtos import SectionProcessingResult
    from src.domain.context.tokenizer import Tokenizer


class CompressibleSection(ABC):
    """Transform prepared section content without mutating the source section."""

    @abstractmethod
    def truncate(
        self,
        content: SectionProcessingResult,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> SectionProcessingResult | None:
        """Return the section-specific truncated result."""

    @abstractmethod
    def summarize(
        self,
        content: SectionProcessingResult,
        capacity_tokens: int,
    ) -> SectionProcessingResult | None:
        """Return summarized content, or None when unavailable."""

    @abstractmethod
    def ignore(
        self,
        content: SectionProcessingResult,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> SectionProcessingResult | None:
        """Drop trailing collection items, or return None when inapplicable."""
