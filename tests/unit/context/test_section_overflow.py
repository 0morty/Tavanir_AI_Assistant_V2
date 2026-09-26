from src.application.context.sections import CompressibleSection, ReferencedCollectionSection
from src.application.context.sections.output_format_section import OutputFormatSection
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import GenerationChunk, Reference
from src.infrastructure.services.summarizers import FakeSummarizer


class FakeTokenizer(Tokenizer):
    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        return [(i, (i, i + 1)) for i in range(len(text))]

    def count_tokens(self, text: str) -> int:
        return len(text)


class PlainCollectionSection(ReferencedCollectionSection):
    @property
    def section_type(self) -> str:
        return "TEST-COLLECTION"


class FluentReference(Reference):
    @property
    def description(self) -> str:
        return "A reference with native fluent text."

    def fluent_text(self) -> str:
        return "REF:"


def _chunks(*contents: str) -> list[GenerationChunk]:
    return [GenerationChunk(str(index), content) for index, content in enumerate(contents)]


def test_plain_text_within_capacity_is_returned_unchanged():
    section = OutputFormatSection("short content")
    prepared = section.prepare()
    assert section.truncate(prepared, 100, tokenizer=FakeTokenizer()).content == "short content"
    assert section.prepare() == prepared


def test_plain_text_exceeding_capacity_is_truncated():
    section = OutputFormatSection("abcdefghij")
    prepared = section.prepare()
    result = section.truncate(prepared, 3, tokenizer=FakeTokenizer())
    assert result.content == "abc"
    assert prepared.content == "abcdefghij"


def test_plain_text_truncate_empty_or_zero_capacity():
    assert OutputFormatSection("").truncate(
        OutputFormatSection("").prepare(), 100, tokenizer=FakeTokenizer()
    ).content == ""
    section = OutputFormatSection("abcdef")
    assert section.truncate(section.prepare(), 0, tokenizer=FakeTokenizer()).content == ""


def test_plain_text_summarize_delegates_to_summarizer():
    section = OutputFormatSection("x" * 100, summarizer=FakeSummarizer())
    result = section.summarize(section.prepare(), 30)
    assert result.content == "[fake-summarizer-output]"
    assert section.body() == "x" * 100


def test_plain_text_summarize_empty_and_missing_summarizer():
    section = OutputFormatSection("", summarizer=FakeSummarizer())
    assert section.summarize(section.prepare(), 30).content == ""
    section = OutputFormatSection("x" * 10)
    assert section.summarize(section.prepare(), 30) is None


def test_plain_text_ignore_is_not_applicable():
    section = OutputFormatSection("abcdefghij")
    assert section.ignore(section.prepare(), 3, tokenizer=FakeTokenizer()) is None


def test_collection_is_compressible():
    assert isinstance(PlainCollectionSection([]), CompressibleSection)


def test_collection_truncate_is_an_explicit_no_op():
    section = PlainCollectionSection(_chunks("ab", "cd", "ef", "gh"))
    prepared = section.prepare()
    assert section.truncate(prepared, 7, tokenizer=FakeTokenizer()) is prepared
    assert section.truncate(prepared, 0, tokenizer=FakeTokenizer()) is prepared


def test_collection_summarize_processes_items_independently():
    section = PlainCollectionSection(_chunks("ab", "cd"), summarizer=FakeSummarizer())
    prepared = section.prepare()
    result = section.summarize(prepared, 30)
    assert result.content == "[fake-summarizer-output]\n\n[fake-summarizer-output]"
    assert [item.content for item in result.items] == [
        "[fake-summarizer-output]", "[fake-summarizer-output]"
    ]
    assert [item.content for item in section.items] == ["ab", "cd"]


def test_collection_ignore_keeps_whole_items_that_fit_in_order():
    section = PlainCollectionSection(_chunks("ab", "cd", "ef", "gh"))
    result = section.ignore(section.prepare(), 7, tokenizer=FakeTokenizer())
    assert result.content == "ab\n\ncd"
    assert [item.content for item in result.items] == ["ab", "cd"]


def test_collection_ignore_nothing_fits_or_zero_capacity():
    section = PlainCollectionSection(_chunks("abhijklm", "cd"))
    assert section.ignore(section.prepare(), 3, tokenizer=FakeTokenizer()).items == ()
    assert section.ignore(section.prepare(), 0, tokenizer=FakeTokenizer()).content == ""


def test_collection_ignore_counts_reference_text_toward_capacity():
    chunks = [
        GenerationChunk("0", "ab", FluentReference()),
        GenerationChunk("1", "cd", FluentReference()),
        GenerationChunk("2", "ef", FluentReference()),
    ]
    section = PlainCollectionSection(chunks)
    result = section.ignore(section.prepare(), 10, tokenizer=FakeTokenizer())
    assert result.content == "REF:\nab"
    assert result.items == (chunks[0],)
