import pytest

from src.application.context import ContextBuilder
from src.application.exceptions import ChunkSummarizationError
from src.application.interfaces.i_chunk_summarizer import IChunkSummarizer
from src.domain.context.tokenizer import Tokenizer
from src.infrastructure.services.summarizers import (
    ChunkPromptBuilder,
    ChunkSummarizationPrompts,
    LLMChunkSummarizer,
)


class CharTokenizer(Tokenizer):
    """Char-based tokenizer: every character counts as one token."""

    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        return [(i, (i, i + 1)) for i in range(len(text))]

    def count_tokens(self, text: str) -> int:
        return len(text)


class RecordingLLM:
    """Records every prompt and serves canned completions in order."""

    def __init__(self, *responses: str) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._responses:
            return ""
        return self._responses.pop(0)


def make_responses(*counts: int) -> list[str]:
    return [
        "\n---\n".join(f"s{index}-{j + 1}" for j in range(count))
        for index, count in enumerate(counts)
    ]


def test_llm_chunk_summarizer_implements_i_chunk_summarizer_port():
    assert isinstance(
        LLMChunkSummarizer(RecordingLLM(), CharTokenizer()), IChunkSummarizer
    )


def test_llm_chunk_summarizer_requires_llm_client_and_tokenizer():
    with pytest.raises(TypeError):
        LLMChunkSummarizer()
    with pytest.raises(TypeError):
        LLMChunkSummarizer(RecordingLLM())


def test_llm_chunk_summarizer_rejects_invalid_options():
    with pytest.raises(ValueError):
        LLMChunkSummarizer(RecordingLLM(), CharTokenizer(), max_attempts=0)
    with pytest.raises(ValueError):
        LLMChunkSummarizer(RecordingLLM(), CharTokenizer(), capacity_reserve=-1)


def test_llm_chunk_summarizer_returns_empty_for_no_input():
    llm = RecordingLLM()
    summarizer = LLMChunkSummarizer(llm, CharTokenizer())

    assert summarizer.summarize([], capacity_tokens=100) == []
    assert summarizer.summarize(["آ"], capacity_tokens=0) == []
    assert llm.prompts == []


def test_llm_chunk_summarizer_maps_all_chunks_in_one_call():
    chunks = ["aaaa", "bbbb", "cccc"]
    llm = RecordingLLM("s0-1\n---\ns0-2\n---\ns0-3")
    summarizer = LLMChunkSummarizer(llm, CharTokenizer(), max_attempts=1)

    result = summarizer.summarize(chunks, capacity_tokens=100000)

    assert result == ["s0-1", "s0-2", "s0-3"]
    assert len(llm.prompts) == 1
    assert "aaaa\n---\nbbbb\n---\ncccc" in llm.prompts[0]


def test_llm_chunk_summarizer_splits_batches_across_calls():
    chunks = ["aaaaaaaaaa", "bbbbbbbbbb", "cccccccccc"]
    builder = ChunkPromptBuilder()
    overhead = len(builder.build([]))
    separator = len(builder.CHUNK_SEPARATOR)
    llm = RecordingLLM("s0-1\n---\ns0-2", "s1-1")
    summarizer = LLMChunkSummarizer(llm, CharTokenizer(), max_attempts=1)

    result = summarizer.summarize(
        chunks, capacity_tokens=overhead + 2 * (separator + 10)
    )

    assert result == ["s0-1", "s0-2", "s1-1"]
    assert len(llm.prompts) == 2


def test_llm_chunk_summarizer_retries_unmapped_response_then_succeeds():
    llm = RecordingLLM("WRONG-SINGLE-SUMMARY", "s0-1\n---\ns0-2")
    summarizer = LLMChunkSummarizer(
        llm, CharTokenizer(), max_attempts=3
    )

    result = summarizer.summarize(["aaaa", "bbbb"], capacity_tokens=100000)

    assert result == ["s0-1", "s0-2"]
    assert len(llm.prompts) == 2


def test_llm_chunk_summarizer_raises_after_exhausted_attempts():
    llm = RecordingLLM("still-not-1:1", "neither-is-this")
    summarizer = LLMChunkSummarizer(llm, CharTokenizer(), max_attempts=2)

    with pytest.raises(ChunkSummarizationError):
        summarizer.summarize(["aaaa", "bbbb"], capacity_tokens=100000)

    assert len(llm.prompts) == 2


def test_llm_chunk_summarizer_guarantees_progress_on_tiny_capacity():
    llm = RecordingLLM("s0-1", "s1-1")
    summarizer = LLMChunkSummarizer(llm, CharTokenizer(), max_attempts=1)

    result = summarizer.summarize(["aaaa", "bbbb"], capacity_tokens=5)

    assert result == ["s0-1", "s1-1"]
    assert len(llm.prompts) == 2


def test_llm_chunk_summarizer_uses_injected_builder():
    prompts = ChunkSummarizationPrompts(role="custom-role")
    custom_builder = ChunkPromptBuilder(prompts=prompts)
    llm = RecordingLLM("s0-1\n---\ns0-2")
    summarizer = LLMChunkSummarizer(llm, CharTokenizer(), builder=custom_builder)

    summarizer.summarize(["aaaa", "bbbb"], capacity_tokens=100000)

    assert "custom-role" in llm.prompts[0]