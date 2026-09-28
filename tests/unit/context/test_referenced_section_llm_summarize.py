from src.application.context import OverflowStrategyDispatcher
from src.application.context.sections.output_format_section import OutputFormatSection
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.domain.enums import OverflowStrategy
from src.domain.entities import Reference
from src.infrastructure.services.summarizers import FAKE_SUMMARY_TEXT, FakeSummarizer

SUMMARY_CAPACITY = 200


class RecordingLLMSummarizer(ITextSummarizer):
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def summarize(self, text: str, *, max_tokens: int | None = None) -> str:
        self.calls.append((text, max_tokens))
        return "llm-summary"

    def summarize_chunks(self, chunks: list[str], *, capacity_tokens: int) -> list[str]:
        return [self.summarize(chunk, max_tokens=capacity_tokens) for chunk in chunks]


def test_referenced_section_uses_injected_llm_summarizer():
    summarizer = RecordingLLMSummarizer()
    section = OutputFormatSection("some content", llm_summarizer=summarizer)
    result = section.summarize(section.prepare(), SUMMARY_CAPACITY)
    assert result.content == "llm-summary"
    assert summarizer.calls == [("some content", SUMMARY_CAPACITY)]
    assert section.body() == "some content"


def test_referenced_section_without_llm_summarizer_uses_plain_default():
    section = OutputFormatSection("some content", summarizer=FakeSummarizer())
    assert section.summarize(section.prepare(), SUMMARY_CAPACITY).content == FAKE_SUMMARY_TEXT


def test_referenced_section_without_any_summarizer_falls_through():
    section = OutputFormatSection("some content")
    assert section.summarize(section.prepare(), SUMMARY_CAPACITY) is None


def test_referenced_section_skips_empty_input_for_llm_summarizer():
    summarizer = RecordingLLMSummarizer()
    empty = OutputFormatSection("", llm_summarizer=summarizer)
    full = OutputFormatSection("some content", llm_summarizer=summarizer)
    assert empty.summarize(empty.prepare(), SUMMARY_CAPACITY).content == ""
    assert full.summarize(full.prepare(), 0).content == ""
    assert summarizer.calls == []


def test_referenced_section_flows_through_dispatcher():
    summarizer = RecordingLLMSummarizer()
    section = OutputFormatSection("some content", llm_summarizer=summarizer)
    result = OverflowStrategyDispatcher().apply(
        section, OverflowStrategy.SUMMARIZE, section.prepare(), SUMMARY_CAPACITY,
        tokenizer=None,
    )
    assert result.content == "llm-summary"
    assert summarizer.calls == [("some content", SUMMARY_CAPACITY)]


def test_llm_summarizer_is_injected_not_instantiated_in_section():
    summarizer = RecordingLLMSummarizer()
    section = OutputFormatSection("some content", llm_summarizer=summarizer)
    assert section._llm_summarizer is summarizer


class FluentReference(Reference):
    @property
    def description(self) -> str:
        return "reference"

    def fluent_text(self) -> str:
        return "REF:"


class FramedOutputSection(OutputFormatSection):
    @property
    def pre_context(self) -> str:
        return "PRE"

    @property
    def post_context(self) -> str:
        return "POST"


def test_single_text_processing_input_includes_context_and_reference():
    summarizer = RecordingLLMSummarizer()
    section = FramedOutputSection(
        "body", reference=FluentReference(), llm_summarizer=summarizer
    )
    prepared = section.prepare()
    result = section.summarize(prepared, SUMMARY_CAPACITY)

    assert prepared.content == "PRE\n\nREF:\nbody\n\nPOST"
    assert summarizer.calls == [(prepared.content, SUMMARY_CAPACITY)]
    assert result.content == "llm-summary"
    assert section.prepare() == prepared
