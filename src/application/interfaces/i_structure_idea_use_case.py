"""Application boundary for structuring an idea without retrieval."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.application.dtos import StructureIdeaDTO, StructuredIdeaResult


class IStructureIdeaUseCase(ABC):
    @abstractmethod
    async def execute(self, dto: StructureIdeaDTO) -> StructuredIdeaResult:
        """Validate the idea, execute Generation, and return its five fields."""
