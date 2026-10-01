from __future__ import annotations

from typing import TYPE_CHECKING

from src.domain.context.tokenizer import Tokenizer

if TYPE_CHECKING:
    from transformers import PreTrainedTokenizerFast


class QwenTokenizer(Tokenizer):
    """Adapt an injected Hugging Face Qwen fast tokenizer for context budgeting."""

    def __init__(self, tokenizer: PreTrainedTokenizerFast) -> None:
        self._tokenizer = tokenizer

    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        encoding = self._tokenizer(
            text,
            add_special_tokens=False,
            return_offsets_mapping=True,
        )
        return list(zip(encoding["input_ids"], encoding["offset_mapping"]))

    def count_tokens(self, text: str) -> int:
        return len(self.encode(text))
