from abc import ABC, abstractmethod
from collections.abc import Sequence


class ITextNormalizer(ABC):
    """
    Abstract interface (Port) for Persian text normalization.

    This service operates purely on strings, remaining completely decoupled
    from domain entities.
    """

    @abstractmethod
    def normalize(self, text: str) -> str:
        """
        Normalizes a single text string (synchronous).

        Args:
            text: Raw input text.

        Returns:
            Cleaned and normalized text.

        Raises:
            TextNormalizationError: If normalization fails.
        """
        pass

    @abstractmethod
    async def normalize_async(self, text: str) -> str:
        """
        Asynchronously normalizes a single text string, offloading CPU-bound
        transformation to a worker thread to prevent event loop blocking.

        Args:
            text: Raw input text.

        Returns:
            Cleaned and normalized text.

        Raises:
            TextNormalizationError: If normalization fails.
        """
        pass

    @abstractmethod
    def normalize_batch(self, texts: Sequence[str]) -> list[str]:
        """
        Normalizes a batch of text strings (synchronous).

        Args:
            texts: Sequence of raw input strings.

        Returns:
            List of cleaned and normalized strings in matching order.
        """
        pass

    @abstractmethod
    async def normalize_batch_async(self, texts: Sequence[str]) -> list[str]:
        """
        Asynchronously normalizes a batch of text strings via worker thread.

        Args:
            texts: Sequence of raw input strings.

        Returns:
            List of cleaned and normalized strings in matching order.
        """
        pass
