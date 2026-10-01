import unittest
from pathlib import Path

from transformers import AutoTokenizer, PreTrainedTokenizerFast

from src.infrastructure.services.tokenizers.qwen_tokenizer import QwenTokenizer


TOKENIZER_DIR = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "tokenizers"
    / "Qwen2.5-7B-Instruct"
)


class LocalQwenTokenizerTests(unittest.TestCase):
    def test_offline_checkpoint_encodes_persian_and_chat_markers(self) -> None:
        raw = AutoTokenizer.from_pretrained(
            str(TOKENIZER_DIR), use_fast=True, local_files_only=True
        )
        self.assertIsInstance(raw, PreTrainedTokenizerFast)
        tokenizer = QwenTokenizer(raw)

        text = "سلام دنیا!"
        encoded = tokenizer.encode(text)
        self.assertEqual(
            [token_id for token_id, _ in encoded],
            [124941, 44330, 11798, 14391, 5703, 0],
        )
        self.assertEqual(tokenizer.count_tokens(text), 6)
        self.assertEqual(
            raw.decode([token_id for token_id, _ in encoded]), text
        )
        self.assertEqual(encoded[0][1], (0, 4))
        self.assertEqual(encoded[-1][1], (9, 10))

        chat = "<|im_start|>user\nسلام<|im_end|>"
        self.assertEqual(
            [token_id for token_id, _ in tokenizer.encode(chat)],
            [151644, 872, 198, 124941, 151645],
        )
        rendered = raw.apply_chat_template(
            [{"role": "user", "content": "سلام"}],
            tokenize=False,
            add_generation_prompt=True,
        )
        self.assertIn("<|im_start|>user\nسلام<|im_end|>", rendered)
        self.assertTrue(rendered.endswith("<|im_start|>assistant\n"))
