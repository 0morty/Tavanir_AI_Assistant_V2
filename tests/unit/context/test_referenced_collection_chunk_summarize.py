from src.application.context import OverflowStrategyDispatcher
from src.application.context.sections.chunks_section import ChunksSection
from src.application.context.sections.history_section import HistorySection
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.domain.entities import GenerationChunk, HistoryMessage
from src.domain.enums import HistoryRole, OverflowStrategy
from src.infrastructure.services.summarizers import FAKE_SUMMARY_TEXT, FakeSummarizer

CAPACITY = 400


class RecordingChunkSummarizer(ITextSummarizer):
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], int]] = []

    def summarize(self, text: str, *, max_tokens: int | None = None) -> str:
        return "llm-summary"

    def summarize_chunks(self, chunks: list[str], *, capacity_tokens: int) -> list[str]:
        self.calls.append((list(chunks), capacity_tokens))
        return [f"summary-{i + 1}" for i in range(len(chunks))]


def chunks_section_with_seam(summarizer=None):
    return ChunksSection(
        [GenerationChunk("1", "one"), GenerationChunk("2", "two")],
        chunk_summarizer=summarizer,
    )


def test_chunks_section_uses_injected_chunk_summarizer():
    summarizer = RecordingChunkSummarizer()
    section = chunks_section_with_seam(summarizer)
    result = section.summarize(section.prepare(), CAPACITY)
    assert [item.content for item in result.items] == ["summary-1", "summary-2"]
    assert summarizer.calls == [
        (["Relevant context chunks:\n\nUnique ID: [chunk 001]\n\none", "Relevant context chunks:\n\nUnique ID: [chunk 002]\n\ntwo"], CAPACITY)
    ]


def test_chunks_section_without_chunk_summarizer_uses_plain_default():
    section = ChunksSection([GenerationChunk("1", "one")], summarizer=FakeSummarizer())
    result = section.summarize(section.prepare(), CAPACITY)
    assert result.items[0].content == FAKE_SUMMARY_TEXT


def test_chunks_section_without_any_summarizer_falls_through():
    section = ChunksSection([GenerationChunk("1", "one")])
    assert section.summarize(section.prepare(), CAPACITY) is None


def test_chunks_section_skips_zero_capacity_for_chunk_summarizer():
    summarizer = RecordingChunkSummarizer()
    section = chunks_section_with_seam(summarizer)
    result = section.summarize(section.prepare(), 0)
    assert result.content == "" and result.items == ()
    assert summarizer.calls == []


def test_chunks_section_is_prepared_item_driven():
    summarizer = RecordingChunkSummarizer()
    section = chunks_section_with_seam(summarizer)
    prepared = section.prepare()
    result = section.summarize(prepared, CAPACITY)
    assert [item.content for item in result.items] == ["summary-1", "summary-2"]
    assert len(summarizer.calls[0][0]) == 2


def test_chunks_section_skips_empty_collection():
    summarizer = RecordingChunkSummarizer()
    section = ChunksSection([], chunk_summarizer=summarizer)
    assert section.summarize(section.prepare(), CAPACITY).items == ()
    assert summarizer.calls == []


def test_chunks_section_flows_through_dispatcher():
    summarizer = RecordingChunkSummarizer()
    section = chunks_section_with_seam(summarizer)
    result = OverflowStrategyDispatcher().apply(
        section, OverflowStrategy.SUMMARIZE, section.prepare(), CAPACITY,
        tokenizer=None,
    )
    assert [item.content for item in result.items] == ["summary-1", "summary-2"]
    assert len(summarizer.calls) == 1


def test_chunk_summarizer_is_injected_not_instantiated_in_section():
    summarizer = RecordingChunkSummarizer()
    section = chunks_section_with_seam(summarizer)
    assert section._chunk_summarizer is summarizer


def test_history_section_uses_same_batch_mapping_and_retains_roles():
    summarizer = RecordingChunkSummarizer()
    section = HistorySection(
        [
            HistoryMessage(HistoryRole.USER, "hi"),
            HistoryMessage(HistoryRole.ASSISTANT, "hello"),
        ],
        chunk_summarizer=summarizer,
    )
    result = section.summarize(section.prepare(), CAPACITY)
    assert [(item.role, item.content) for item in result.items] == [
        (HistoryRole.USER, "summary-1"),
        (HistoryRole.ASSISTANT, "summary-2"),
    ]
    assert section.items[0].content == "hi"
