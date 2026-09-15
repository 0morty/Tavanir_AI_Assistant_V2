from abc import ABC, abstractmethod


class Tokenizer(ABC):
    """Tokenization capability contract for context overflow handling.

    This abstraction exposes the capabilities the overflow strategies need:
    token encoding (with token-to-original-text offsets), token counting, and a
    read-only capability indicator for offset support. Concrete tokenizer
    implementations (e.g. HuggingFace Gemma) are injected from outside; this
    class never instantiates or references them.
    """

    @property
    @abstractmethod
    def supports_offset_mapping(self) -> bool:
        """Indicates whether this tokenizer can provide token-to-original-text offsets.

        The capability is read-only and cannot be configured externally.
        """
        pass

    @abstractmethod
    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        """Encode ``text`` and return each token ID paired with its character offsets.

        Each element is ``(token_id, (start, end))`` where ``start`` and ``end``
        are the character offsets of the token relative to the beginning of the
        original ``text``.
        """
        pass

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Return the number of tokens that encoding ``text`` would produce."""
        pass