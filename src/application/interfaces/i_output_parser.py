"""Application contract for parsing the final Generation model response."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.application.dtos import GenerationResult, SimilarSuggestionInput
    from src.domain.entities import GenerationChunk


class IOutputParser(ABC):
    """Validate model JSON and resolve citations from the fitted prompt map."""

    @abstractmethod
    def parse(
        self,
        raw_output: str,
        *,
        citation_map: Mapping[str, GenerationChunk | SimilarSuggestionInput],
    ) -> GenerationResult:
        """Return an answer and original retained evidence objects."""
