from __future__ import annotations

from typing import TYPE_CHECKING

from src.domain.context.tokenizer import Tokenizer

if TYPE_CHECKING:
    from transformers import PreTrainedTokenizerFast


class GemmaTokenizer(Tokenizer):
    """Adapter between the :class:`Tokenizer` abstraction and the Hugging Face Gemma tokenizer.

    Wraps an externally created ``GemmaTokenizerFast`` instance; this class never
    loads or downloads a tokenizer itself. The Hugging Face instance is injected
    through the constructor, so this adapter only translates between the domain
    abstraction and the Hugging Face implementation.
    """

    def __init__(self, tokenizer: PreTrainedTokenizerFast) -> None:
        self._tokenizer = tokenizer

    @property
    def supports_offset_mapping(self) -> bool:
        """Hugging Face fast tokenizers (``GemmaTokenizerFast``) support offset mapping."""
        return True

    def encode(self, text: str) -> list[int]:
        """Encode ``text`` into token IDs using the wrapped Hugging Face tokenizer."""
        return list(self._tokenizer.encode(text))

    def encode_with_offsets(self, text: str) -> list[tuple[int, int]]:
        """Encode ``text`` and return per-token character offsets into the original text.

        Offsets are requested from Hugging Face with ``return_offsets_mapping=True``,
        preserving the original text boundaries.
        """
        encoding = self._tokenizer(text, return_offsets_mapping=True)
        return list(encoding["offset_mapping"])

    def count_tokens(self, text: str) -> int:
        """Return the number of tokens that encoding ``text`` would produce."""
        return len(self.encode(text))