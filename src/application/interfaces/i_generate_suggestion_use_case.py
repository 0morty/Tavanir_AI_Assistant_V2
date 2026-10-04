from abc import ABC, abstractmethod

from src.application.dtos import GenerationInput, GenerationResult


class IGenerateSuggestionUseCase(ABC):
    """Port for downstream suggestion generation orchestration."""

    @abstractmethod
    async def execute(self, generation_input: GenerationInput) -> GenerationResult:
        """Executes prompt preparation, chat completion, and output validation.

        Args:
            generation_input: Validated structured input for generation.

        Returns:
            GenerationResult containing answer narrative, citations, and uncertainty.
        """
        raise NotImplementedError
