from src.application.context.sections.output_format_section import (
    OutputFormatSection,
)
from src.application.context.sections.referenced_collection_section import (
    ReferencedCollectionSection,
)
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import GenerationChunk
from src.domain.enums import OverflowStrategy
from src.domain.overflow_strategy_stack import OverflowStrategyStack
from src.infrastructure.services.summarizers import FakeSummarizer


class FakeTokenizer(Tokenizer):
    """Char-based tokenizer: every character counts as one token."""

    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        return [(i, (i, i + 1)) for i in range(len(text))]

    def count_tokens(self, text: str) -> int:
        return len(text)


class PlainCollectionSection(ReferencedCollectionSection):
    """Concrete collection Section that renders raw item content."""

    @property
    def section_type(self) -> str:
        return "TEST-COLLECTION"


def _chunks(*contents: str) -> list[GenerationChunk]:
    return [
        GenerationChunk(chunk_id=str(index), content=content)
        for index, content in enumerate(contents)
    ]


# --- single plain text (ReferencedSection) ---


def test_plain_text_within_capacity_is_returned_unchanged():
    section = OutputFormatSection("short content")
    result = section.fit_to_capacity(
        "short content", 100, tokenizer=FakeTokenizer()
    )
    assert result == "short content"


def test_plain_text_exceeding_capacity_is_truncated_with_default_stack():
    section = OutputFormatSection("abcdefghij")
    result = section.fit_to_capacity(
        "abcdefghij", 3, tokenizer=FakeTokenizer()
    )
    assert result == "abc"


def test_plain_text_empty_returns_empty_string():
    section = OutputFormatSection("")
    assert section.fit_to_capacity("", 100, tokenizer=FakeTokenizer()) == ""


def test_zero_capacity_returns_empty_string():
    section = OutputFormatSection("abcdef")
    assert section.fit_to_capacity("abcdef", 0, tokenizer=FakeTokenizer()) == ""


def test_summarize_strategy_is_used_when_configured():
    stack = OverflowStrategyStack([OverflowStrategy.SUMMARIZE])
    section = OutputFormatSection("x" * 100, overflow_strategies=stack)
    result = section.fit_to_capacity(
        "x" * 100, 30, tokenizer=FakeTokenizer(), summarizer=FakeSummarizer()
    )
    assert result == "[fake-summarizer-output]"


def test_summarize_without_summarizer_falls_back_to_best_effort():
    stack = OverflowStrategyStack([OverflowStrategy.SUMMARIZE])
    section = OutputFormatSection("x" * 100, overflow_strategies=stack)
    result = section.fit_to_capacity(
        "x" * 100, 30, tokenizer=FakeTokenizer()
    )
    assert result == "x" * 100


# --- collection (ReferencedCollectionSection) ---


def test_collection_within_capacity_is_returned_unchanged():
    section = PlainCollectionSection(_chunks("ab", "cd"))
    result = section.fit_to_capacity(
        _chunks("ab", "cd"), 10, tokenizer=FakeTokenizer()
    )
    assert result == "ab\n\ncd"


def test_collection_truncates_joined_text_with_default_stack():
    section = PlainCollectionSection(_chunks("ab", "cd", "ef", "gh"))
    result = section.fit_to_capacity(
        _chunks("ab", "cd", "ef", "gh"), 7, tokenizer=FakeTokenizer()
    )
    assert result == "ab\n\ncd\n"


def test_collection_ignores_items_that_cannot_fit_in_order():
    stack = OverflowStrategyStack(
        [OverflowStrategy.IGNORE, OverflowStrategy.TRUNCATE]
    )
    section = PlainCollectionSection(
        _chunks("ab", "cd", "ef", "gh"), overflow_strategies=stack
    )
    result = section.fit_to_capacity(
        _chunks("ab", "cd", "ef", "gh"), 7, tokenizer=FakeTokenizer()
    )
    assert result == "ab\n\ncd"


def test_collection_empty_returns_empty_string():
    section = PlainCollectionSection([])
    assert section.fit_to_capacity([], 100, tokenizer=FakeTokenizer()) == ""


def test_collection_zero_capacity_returns_empty_string():
    section = PlainCollectionSection(_chunks("ab"))
    assert section.fit_to_capacity(_chunks("ab"), 0, tokenizer=FakeTokenizer()) == ""


def test_collection_fitting_keeps_items_untouched():
    stack = OverflowStrategyStack(
        [OverflowStrategy.IGNORE, OverflowStrategy.TRUNCATE]
    )
    items = _chunks("ab", "cd", "ef", "gh")
    section = PlainCollectionSection(items, overflow_strategies=stack)
    result = section.fit_to_capacity(items, 100, tokenizer=FakeTokenizer())
    assert result == "ab\n\ncd\n\nef\n\ngh"