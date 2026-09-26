from abc import ABC, abstractmethod

from src.application.dtos import ContextBuilderResult, GenerationInput


class ISuggestionPromptPreparer(ABC):
    """Port for suggestion prompt assembly and upfront token budgeting."""

    @abstractmethod
    def prepare(
        self,
        generation_input: GenerationInput,
        max_prompt_tokens: int,
    ) -> ContextBuilderResult:
        """Assembles prompt sections, enforces token budgets, and returns the result.

        Args:
            generation_input: Validated input containing current suggestion, similar suggestions, and regulations.
            max_prompt_tokens: Hard ceiling for total prompt tokens.

        Returns:
            ContextBuilderResult containing the assembled prompt string and per-section accounting.

        Raises:
            PromptBudgetExceededError: When fixed sections exceed max_prompt_tokens.
            InsufficientEvidenceBudgetError: When remaining budget cannot fit even 1 similar suggestion.
        """
        raise NotImplementedError
