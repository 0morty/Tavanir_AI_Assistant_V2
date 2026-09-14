from abc import ABC, abstractmethod
from collections.abc import Sequence


class ITokenizer(ABC):
    """
    Abstract interface (Port) for model-neutral LLM text tokenization.

    This service hides all model-specific tokenizer details (Hugging Face,
    vLLM, or any particular LLM) from the rest of the Generation API. Token-based
    logic (e.g. the TRUNCATE overflow strategy) depends only on this interface,
    exposing text as integer token IDs and nothing else.
    """

    @abstractmethod
    def tokenize(self, text: str) -> list[int]:
        """
        Tokenizes a text into its constituent token IDs.

        Args:
            text: The input string to tokenize.

        Returns:
            A list of integer token IDs in tokenization order. Returns an
            empty list for an empty string.

        Raises:
            TokenizerError: If tokenization fails.
        """
        pass

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """
        Determines the token count of a text.

        Args:
            text: The input string to count.

        Returns:
            The number of tokens the text would produce. Returns 0 for an
            empty string.

        Raises:
            TokenizerError: If token counting fails.
        """
        pass

    @abstractmethod
    def decode(self, tokens: Sequence[int]) -> str:
        """
        Reconstructs text from token IDs.

        Args:
            tokens: A sequence of integer token IDs, e.g. the result of
                truncating a tokenized text.

        Returns:
            The decoded string. Returns an empty string for an empty sequence.

        Raises:
            TokenizerError: If decoding fails or a token ID is invalid.
        """
        pass