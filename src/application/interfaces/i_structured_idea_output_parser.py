"""Application port for the idea model's ordered plain-text output."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.application.dtos import StructuredIdeaResult


class IStructuredIdeaOutputParser(ABC):
    @abstractmethod
    def parse(self, raw_output: str) -> StructuredIdeaResult:
        """Extract the exact five marked blocks or raise an LLM output error."""
