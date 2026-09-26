from src.application.context.sections import CompressibleSection, ReferencedCollectionSection
from src.application.context.sections.output_format_section import (
    OutputFormatSection,
)
from src.domain.context.overflow.summarize import SummarizeStrategy
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import GenerationChunk, Reference
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


class FluentReference(Reference):
    """Reference whose native fluent text is a fixed prefix."""

    @property
    def description(self) -> str:
        return "A reference with native fluent text."

    def fluent_text(self) -> str:
        return "REF:"


def _chunks(*contents: str) -> list[GenerationChunk]:
    return [
        GenerationChunk(chunk_id=str(index), content=content)
        for index, content in enumerate(contents)
    ]


# --- plain text (PromptSection default) ---


def test_plain_text_within_capacity_is_returned_unchanged():
    section = OutputFormatSection("short content")
    result = section.truncate("short content", 100, tokenizer=FakeTokenizer())
    assert result == "short content"


def test_plain_text_exceeding_capacity_is_truncated():
    section = OutputFormatSection("abcdefghij")
    result = section.truncate("abcdefghij", 3, tokenizer=FakeTokenizer())
    assert result == "abc"


def test_plain_text_truncate_empty_returns_empty_string():
    section = OutputFormatSection("")
    assert section.truncate("", 100, tokenizer=FakeTokenizer()) == ""


def test_plain_text_truncate_zero_capacity_returns_empty_string():
    section = OutputFormatSection("abcdef")
    assert section.truncate("abcdef", 0, tokenizer=FakeTokenizer()) == ""


def test_plain_text_summarize_delegates_to_summarizer():
    section = OutputFormatSection("x" * 100, summarizer=FakeSummarizer())
    result = section.summarize("x" * 100, 30)
    assert result == "[fake-summarizer-output]"


def test_plain_text_summarize_empty_returns_empty_string():
    section = OutputFormatSection("", summarizer=FakeSummarizer())
    assert section.summarize("", 30) == ""


def test_plain_text_summarize_without_summarizer_returns_none():
    section = OutputFormatSection("x" * 10)
    assert section.summarize("x" * 10, 30) is None


def test_plain_text_ignore_is_not_applicable():
    section = OutputFormatSection("abcdefghij")
    assert section.ignore("abcdefghij", 3, tokenizer=FakeTokenizer()) is None


# --- collection (ReferencedCollectionSection) ---


def test_collection_is_compressible():
    assert isinstance(PlainCollectionSection([]), CompressibleSection)


def test_collection_truncates_joined_text():
    section = PlainCollectionSection(_chunks("ab", "cd", "ef", "gh"))
    result = section.truncate(
        "ab\n\ncd\n\nef\n\ngh", 7, tokenizer=FakeTokenizer()
    )
    assert result == "ab\n\ncd\n"


def test_collection_truncate_empty_returns_empty_string():
    section = PlainCollectionSection([])
    assert section.truncate("", 100, tokenizer=FakeTokenizer()) == ""


def test_collection_truncate_zero_capacity_returns_empty_string():
    section = PlainCollectionSection(_chunks("ab"))
    assert section.truncate("ab", 0, tokenizer=FakeTokenizer()) == ""


def test_collection_summarize_processes_items_independently():
    section = PlainCollectionSection(
        _chunks("ab", "cd"), summarizer=FakeSummarizer()
    )
    result = section.summarize("ab\n\ncd", 30)
    assert result == "[fake-summarizer-output]\n\n[fake-summarizer-output]"


def test_collection_ignore_keeps_items_that_fit_in_order():
    section = PlainCollectionSection(_chunks("ab", "cd", "ef", "gh"))
    result = section.ignore(
        "ab\n\ncd\n\nef\n\ngh", 7, tokenizer=FakeTokenizer()
    )
    assert result == "ab\n\ncd"


def test_collection_ignore_nothing_fits_returns_empty_string():
    section = PlainCollectionSection(_chunks("abhijklm", "cd"))
    result = section.ignore(
        "abhijklm\n\ncd", 3, tokenizer=FakeTokenizer()
    )
    assert result == ""


def test_collection_ignore_empty_returns_empty_string():
    section = PlainCollectionSection([])
    assert section.ignore("", 100, tokenizer=FakeTokenizer()) == ""


def test_collection_ignore_zero_capacity_returns_empty_string():
    section = PlainCollectionSection(_chunks("ab"))
    assert section.ignore("ab", 0, tokenizer=FakeTokenizer()) == ""


def test_collection_ignore_counts_reference_text_toward_capacity():
    chunks = [
        GenerationChunk(chunk_id="0", content="ab", reference=FluentReference()),
        GenerationChunk(chunk_id="1", content="cd", reference=FluentReference()),
        GenerationChunk(chunk_id="2", content="ef", reference=FluentReference()),
    ]
    section = PlainCollectionSection(chunks)
    result = section.ignore(
        "REF:\nab\n\nREF:\ncd\n\nREF:\nef", 10, tokenizer=FakeTokenizer()
    )
    assert result == "REF:\nab"