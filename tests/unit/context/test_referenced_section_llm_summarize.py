from src.application.context import ContextBuilder, OverflowStrategyDispatcher
from src.application.context.sections.output_format_section import (
    OutputFormatSection,
)
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.infrastructure.services.summarizers import FAKE_SUMMARY_TEXT, FakeSummarizer

SUMMARY_CAPACITY = 200


class RecordingLLMSummarizer(ITextSummarizer):
    """Records text/budget pairs and returns a predictable summary."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def summarize(self, text: str, *, max_tokens: int | None = None) -> str:
        self.calls.append((text, max_tokens))
        return "llm-summary"

    def summarize_chunks(
        self, chunks: list[str], *, capacity_tokens: int
    ) -> list[str]:
        return [self.summarize(chunk, max_tokens=capacity_tokens) for chunk in chunks]


def test_referenced_section_uses_injected_llm_summarizer():
    summarizer = RecordingLLMSummarizer()
    section = OutputFormatSection("some content", llm_summarizer=summarizer)

    result = section.summarize("some content", SUMMARY_CAPACITY)

    assert result == "llm-summary"
    assert summarizer.calls == [("some content", SUMMARY_CAPACITY)]


def test_referenced_section_without_llm_summarizer_uses_plain_default():
    section = OutputFormatSection("some content", summarizer=FakeSummarizer())

    result = section.summarize("some content", SUMMARY_CAPACITY)

    assert result == FAKE_SUMMARY_TEXT


def test_referenced_section_without_any_summarizer_falls_through():
    section = OutputFormatSection("some content")

    assert section.summarize("some content", SUMMARY_CAPACITY) is None


def test_referenced_section_skips_empty_input_for_llm_summarizer():
    summarizer = RecordingLLMSummarizer()
    section = OutputFormatSection("some content", llm_summarizer=summarizer)

    assert section.summarize("", SUMMARY_CAPACITY) == ""
    assert section.summarize("some content", 0) == ""
    assert summarizer.calls == []


def test_referenced_section_flows_through_dispatcher():
    from src.domain.enums import OverflowStrategy

    summarizer = RecordingLLMSummarizer()
    section = OutputFormatSection("some content", llm_summarizer=summarizer)

    result = OverflowStrategyDispatcher().apply(
        section,
        OverflowStrategy.SUMMARIZE,
        "some content",
        SUMMARY_CAPACITY,
        tokenizer=None,
    )

    assert result == "llm-summary"
    assert summarizer.calls == [("some content", SUMMARY_CAPACITY)]


def test_llm_summarizer_is_injected_not_instantiated_in_section():
    summarizer = RecordingLLMSummarizer()
    section = OutputFormatSection("some content", llm_summarizer=summarizer)

    assert section._llm_summarizer is summarizer