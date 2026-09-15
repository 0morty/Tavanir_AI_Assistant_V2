from src.domain.context.overflow.strategy import OverflowStrategy


class SummarizeStrategy(OverflowStrategy):
    """Overflow strategy that LLM-compresses a Section's text to reduce its token usage.

    Placeholder for future LLM-based semantic compression. No business logic is
    implemented yet.
    """

    def apply(self, content: str, capacity: int) -> str:
        """Apply the overflow behavior to ``content`` under ``capacity``.

        Args:
            content: The Section's content that does not fit its capacity.
            capacity: The available token capacity allocated to the Section.

        Returns:
            The transformed content after applying the overflow behavior.
        """
        raise NotImplementedError