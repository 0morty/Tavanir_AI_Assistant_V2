from src.domain.context.overflow.strategy import OverflowStrategy


class IgnoreStrategy(OverflowStrategy):
    """Overflow strategy that excludes items that cannot fit within the available capacity.

    Placeholder for the future list-based behavior where extra items are removed
    instead of modified. No business logic is implemented yet.
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