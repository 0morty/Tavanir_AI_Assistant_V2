from abc import ABC, abstractmethod


class OverflowStrategy(ABC):
    """Contract for a strategy applied when a Section's content exceeds its allocated token capacity.

    A concrete strategy receives the Section's content and the available token
    capacity, and returns the transformed content after applying the overflow
    behavior. This contract only defines the interface; implementations such as
    token-boundary-aware truncation, LLM-based summarization, and item removal
    are provided separately.
    """

    @abstractmethod
    def apply(self, content: str, capacity: int) -> str:
        """Apply the overflow behavior to ``content`` under ``capacity``.

        Args:
            content: The Section's content that does not fit its capacity.
            capacity: The available token capacity allocated to the Section.

        Returns:
            The transformed content after applying the overflow behavior.
        """
        pass