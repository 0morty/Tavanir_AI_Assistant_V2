from src.domain.context.overflow.strategy import OverflowStrategy
from src.domain.context.tokenizer import Tokenizer


class TruncateStrategy(OverflowStrategy):
    """Overflow strategy that reduces a Section's text to a prefix that fits the token budget.

    Placeholder for the future token-boundary-aware truncation implementation.
    No business logic is implemented yet.
    """

    def __init__(self, tokenizer: Tokenizer) -> None:
        self._tokenizer = tokenizer

    def apply(self, content: str, capacity: int) -> str:
        """Apply the overflow behavior to ``content`` under ``capacity``.

        Args:
            content: The Section's content that does not fit its capacity.
            capacity: The available token capacity allocated to the Section.

        Returns:
            The transformed content after applying the overflow behavior.
        """
        raise NotImplementedError