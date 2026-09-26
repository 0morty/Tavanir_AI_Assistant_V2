from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.application.dtos import SectionProcessingResult
    from src.application.interfaces.i_compressible_section import CompressibleSection
    from src.domain.context.tokenizer import Tokenizer
    from src.domain.enums import OverflowStrategy


class IOverflowStrategyDispatcher(ABC):
    """Port mapping each configured overflow strategy to a section operation."""

    @abstractmethod
    def apply(
        self,
        section: CompressibleSection,
        strategy: OverflowStrategy,
        content: SectionProcessingResult,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> SectionProcessingResult | None:
        """Return the transformed value, or None when the operation is unavailable."""
