import unittest

from src.domain.context.tokenizer import Tokenizer
from src.infrastructure.services.tokenizers.qwen_tokenizer import QwenTokenizer


class RecordingFastTokenizer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool, bool]] = []

    def __call__(
        self,
        text: str,
        *,
        add_special_tokens: bool,
        return_offsets_mapping: bool,
    ) -> dict[str, list]:
        self.calls.append((text, add_special_tokens, return_offsets_mapping))
        if not text:
            return {"input_ids": [], "offset_mapping": []}
        return {"input_ids": [101, 102], "offset_mapping": [(0, 3), (3, 5)]}


class QwenTokenizerTests(unittest.TestCase):
    def test_injected_tokenizer_supplies_ids_and_offsets(self) -> None:
        raw = RecordingFastTokenizer()
        tokenizer = QwenTokenizer(raw)

        self.assertIsInstance(tokenizer, Tokenizer)
        self.assertTrue(tokenizer.supports_offset_mapping)
        self.assertEqual(tokenizer.encode("hello"), [(101, (0, 3)), (102, (3, 5))])
        self.assertEqual(raw.calls, [("hello", False, True)])

    def test_count_uses_plain_text_tokens_without_added_special_tokens(self) -> None:
        raw = RecordingFastTokenizer()
        tokenizer = QwenTokenizer(raw)

        self.assertEqual(tokenizer.count_tokens("hello"), 2)
        self.assertEqual(tokenizer.count_tokens(""), 0)
        self.assertEqual(raw.calls, [("hello", False, True), ("", False, True)])

    def test_tokenizer_dependency_is_required(self) -> None:
        with self.assertRaises(TypeError):
            QwenTokenizer()
