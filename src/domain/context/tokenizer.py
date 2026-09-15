from abc import ABC, abstractmethod


class Tokenizer(ABC):
    """Tokenization capability contract for context overflow handling.

    This abstraction exposes the capabilities the overflow strategies need:
    token encoding, token counting, and (when supported) token-to-original-text
    offset mapping. Concrete tokenizer implementations (e.g. HuggingFace Gemma)
    are injected from outside; this class never instantiates or references them.
    """

    @property
    @abstractmethod
    def supports_offset_mapping(self) -> bool:
        """Indicates whether this tokenizer can provide token-to-original-text offsets.

        The capability is read-only and cannot be configured externally.
        """
        pass

    @abstractmethod
    def encode(self, text: str) -> list[int]:
        """Encode ``text`` into a list of token IDs in tokenization order."""
        pass

    @abstractmethod
    def encode_with_offsets(self, text: str) -> list[tuple[int, int]]:
        """Encode ``text`` and return the per-token character offsets.

        Each tuple is the ``(start, end)`` character offset of a token relative
        to the beginning of the original ``text``.
        """
        pass

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Return the number of tokens that encoding ``text`` would produce."""
        pass