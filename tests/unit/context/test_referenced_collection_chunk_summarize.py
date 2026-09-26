from src.application.context import ContextBuilder, OverflowStrategyDispatcher
from src.application.context.sections.chunks_section import ChunksSection
from src.application.context.sections.history_section import HistorySection
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.domain.entities import GenerationChunk, HistoryMessage
from src.domain.enums import HistoryRole, OverflowStrategy
from src.infrastructure.services.summarizers import FAKE_SUMMARY_TEXT, FakeSummarizer

CAPACITY = 400


class RecordingChunkSummarizer(ITextSummarizer):
    """Records chunk/capacity pairs and returns one summary per chunk in order."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], int]] = []

    def summarize(self, text: str, *, max_tokens: int | None = None) -> str:
        return "llm-summary"

    def summarize_chunks(self, chunks: list[str], *, capacity_tokens: int) -> list[str]:
        self.calls.append((chunks, capacity_tokens))
        return [f"summary-{i + 1}" for i in range(len(chunks))]


def chunks_section_with_seam(summarizer=None):
    chunks = [
        GenerationChunk(chunk_id="1", content="one"),
        GenerationChunk(chunk_id="2", content="two"),
    ]
    return ChunksSection(chunks, chunk_summarizer=summarizer)


def test_chunks_section_uses_injected_chunk_summarizer():
    summarizer = RecordingChunkSummarizer()
    section = chunks_section_with_seam(summarizer)

    result = section.summarize("some content", CAPACITY)

    assert result == "summary-1\n\nsummary-2"
    assert summarizer.calls == [
        (["Chunk 1:\none", "Chunk 2:\ntwo"], CAPACITY)
    ]


def test_chunks_section_without_chunk_summarizer_uses_plain_default():
    section = ChunksSection(
        [GenerationChunk(chunk_id="1", content="one")],
        summarizer=FakeSummarizer(),
    )

    result = section.summarize("some content", CAPACITY)

    assert result == FAKE_SUMMARY_TEXT


def test_chunks_section_without_any_summarizer_falls_through():
    section = ChunksSection([GenerationChunk(chunk_id="1", content="one")])

    assert section.summarize("some content", CAPACITY) is None


def test_chunks_section_skips_zero_capacity_for_chunk_summarizer():
    summarizer = RecordingChunkSummarizer()
    section = chunks_section_with_seam(summarizer)

    assert section.summarize("some content", 0) == ""
    assert summarizer.calls == []


def test_chunks_section_is_item_driven_ignoring_content_param():
    summarizer = RecordingChunkSummarizer()
    section = chunks_section_with_seam(summarizer)

    result = section.summarize("", CAPACITY)

    assert result == "summary-1\n\nsummary-2"
    assert summarizer.calls == [
        (["Chunk 1:\none", "Chunk 2:\ntwo"], CAPACITY)
    ]


def test_chunks_section_skips_empty_items_for_chunk_summarizer():
    summarizer = RecordingChunkSummarizer()

    section = ChunksSection([], chunk_summarizer=summarizer)

    assert section.summarize("some content", CAPACITY) == ""
    assert summarizer.calls == []


def test_chunks_section_flows_through_dispatcher():
    summarizer = RecordingChunkSummarizer()
    section = chunks_section_with_seam(summarizer)

    result = OverflowStrategyDispatcher().apply(
        section,
        OverflowStrategy.SUMMARIZE,
        "some content",
        CAPACITY,
        tokenizer=None,
    )

    assert result == "summary-1\n\nsummary-2"
    assert summarizer.calls == [
        (["Chunk 1:\none", "Chunk 2:\ntwo"], CAPACITY)
    ]


def test_chunk_summarizer_is_injected_not_instantiated_in_section():
    summarizer = RecordingChunkSummarizer()
    section = chunks_section_with_seam(summarizer)

    assert section._chunk_summarizer is summarizer


def test_history_section_forwards_chunk_summarizer():
    summarizer = RecordingChunkSummarizer()
    section = HistorySection(
        [
            HistoryMessage(role=HistoryRole.USER, content="hi"),
            HistoryMessage(role=HistoryRole.ASSISTANT, content="hello"),
        ],
        chunk_summarizer=summarizer,
    )

    result = section.summarize("some content", CAPACITY)

    assert result == "summary-1\n\nsummary-2"
    assert section._chunk_summarizer is summarizer