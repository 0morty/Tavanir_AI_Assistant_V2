"""Port for turning fitted Generation context into chat messages."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.application.dtos import ContextBuilderResult


class ILLMRequestBuilder(ABC):
    @abstractmethod
    def build_messages(
        self, context_result: ContextBuilderResult
    ) -> list[dict[str, str]]:
        """Return model messages from already-fitted section outputs."""
        raise NotImplementedError
