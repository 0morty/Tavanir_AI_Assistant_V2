from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from src.application.dtos import ContextBuilderResult

if TYPE_CHECKING:  # pragma: no cover
    from src.application.prompt.prompt_builder import PromptBuilder


class IContextBuilder(ABC):
    """Port for assembling a token-budgeted prompt from a :class:`PromptBuilder`."""

    @abstractmethod
    def build(
        self,
        builder: "PromptBuilder",
        max_tokens: int,
    ) -> ContextBuilderResult:
        """Run the token-budget pipeline over ``builder``'s sections."""