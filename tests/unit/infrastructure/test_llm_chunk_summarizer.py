import pytest

from src.application.context import ContextBuilder
from src.application.exceptions import ChunkSummarizationError
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.infrastructure.services.summarizers import (
    ChunkPromptBuilder,
    ChunkSummarizationPrompts,
    LLMChunkSummarizer,
)


class RecordingLLM:
    """Records every unfulfilled-response batch and serves canned summaries in order."""

    def __init__(self, *responses: str) -> None:
        self._responses = list(responses)
        self.batches: list[list[str]] = []

    def complete(self, prompt: str) -> str:
        raise AssertionError("LLMChunkSummarizer must call complete_many")

    def complete_many(self, prompts):
        batch = list(prompts)
        self.batches.append(batch)
        return [self._serve() for _ in batch]

    def _serve(self) -> str:
        if not self._responses:
            return ""
        return self._responses.pop(0)


class BatchOnlyLLM:
    """Implements only the batching port to prove :meth:`complete_many` is used."""

    def __init__(self, *contents: str) -> None:
        self._contents = list(contents)
        self.batches: list[list[str]] = []

    def complete(self, prompt: str) -> str:
        raise AssertionError("complete_many must be the only entry point")

    def complete_many(self, prompts):
        self.batches.append(list(prompts))
        return [self._contents.pop(0) if self._contents else "" for _ in prompts]


def test_llm_chunk_summarizer_implements_i_text_summarizer_port():
    assert isinstance(LLMChunkSummarizer(RecordingLLM()), ITextSummarizer)


def test_llm_chunk_summarizer_requires_llm_client():
    with pytest.raises(TypeError):
        LLMChunkSummarizer()


def test_llm_chunk_summarizer_rejects_invalid_options():
    with pytest.raises(ValueError):
        LLMChunkSummarizer(RecordingLLM(), max_attempts=0)
    with pytest.raises(ValueError):
        LLMChunkSummarizer(RecordingLLM(), batch_size=0)


def test_llm_chunk_summarizer_submits_prompts_through_complete_many():
    llm = BatchOnlyLLM("s0", "s1")
    summarizer = LLMChunkSummarizer(llm, max_attempts=1)

    result = summarizer.summarize_chunks(["aaaa", "bbbb"], capacity_tokens=100)

    assert result == ["s0", "s1"]
    assert len(llm.batches) == 1


def test_llm_chunk_summarizer_returns_empty_for_no_input():
    llm = RecordingLLM()
    summarizer = LLMChunkSummarizer(llm)

    assert summarizer.summarize_chunks([], capacity_tokens=100) == []
    assert summarizer.summarize_chunks(["آ"], capacity_tokens=0) == []
    assert llm.batches == []


def test_llm_chunk_summarizer_sends_whole_collection_in_one_batch():
    chunks = ["chunk-آ", "chunk-ب", "chunk-ج"]
    llm = RecordingLLM("s0", "s1", "s2")
    summarizer = LLMChunkSummarizer(llm, max_attempts=1)

    result = summarizer.summarize_chunks(chunks, capacity_tokens=100000)

    assert result == ["s0", "s1", "s2"]
    assert len(llm.batches) == 1
    prompts = llm.batches[0]
    assert len(prompts) == 3
    for index, chunk in enumerate(chunks):
        assert chunk in prompts[index]
        assert all(chunk not in prompts[other] for other in range(3) if other != index)


def test_llm_chunk_summarizer_rounds_remaining_chunks_into_followup_batches():
    chunks = ["c0", "c1", "c2", "c3", "c4"]
    llm = RecordingLLM("s0", "s1", "s2", "s3", "s4")
    summarizer = LLMChunkSummarizer(llm, max_attempts=1, batch_size=2)

    result = summarizer.summarize_chunks(chunks, capacity_tokens=100000)

    assert result == ["s0", "s1", "s2", "s3", "s4"]
    assert [len(batch) for batch in llm.batches] == [2, 2, 1]
    assert "c0" in llm.batches[0][0] and "c1" in llm.batches[0][1]
    assert "c2" in llm.batches[1][0] and "c3" in llm.batches[1][1]
    assert "c4" in llm.batches[2][0]
    assert len(sum(llm.batches, [])) == 5


def test_llm_chunk_summarizer_retries_only_unresolved_chunks():
    llm = RecordingLLM("", "", "", "s1", "s0")
    summarizer = LLMChunkSummarizer(llm, max_attempts=3)

    result = summarizer.summarize_chunks(["aaaa", "bbbb"], capacity_tokens=100000)

    assert result == ["s0", "s1"]
    assert len(llm.batches) == 3
    assert len(llm.batches[0]) == 2
    assert len(llm.batches[1]) == 2
    assert len(llm.batches[2]) == 1
    assert "aaaa" in llm.batches[2][0]


def test_llm_chunk_summarizer_raises_after_exhausted_attempts():
    llm = RecordingLLM("", "", "", "")
    summarizer = LLMChunkSummarizer(llm, max_attempts=2)

    with pytest.raises(ChunkSummarizationError):
        summarizer.summarize_chunks(["aaaa", "bbbb"], capacity_tokens=100000)

    assert len(llm.batches) == 2


def test_llm_chunk_summarizer_tiny_but_positive_capacity_still_summarizes():
    llm = RecordingLLM("s0", "s1")
    summarizer = LLMChunkSummarizer(llm, max_attempts=1)

    result = summarizer.summarize_chunks(["aaaa", "bbbb"], capacity_tokens=1)

    assert result == ["s0", "s1"]
    assert len(llm.batches) == 1


def test_llm_chunk_summarizer_uses_injected_builder():
    prompts = ChunkSummarizationPrompts(role="custom-role")
    custom_builder = ChunkPromptBuilder(prompts=prompts)
    llm = RecordingLLM("s0", "s1")
    summarizer = LLMChunkSummarizer(llm, builder=custom_builder, max_attempts=1)

    summarizer.summarize_chunks(["aaaa", "bbbb"], capacity_tokens=100000)

    assert "custom-role" in llm.batches[0][0]


def test_llm_chunk_summarizer_single_text_summarize_uses_given_budget():
    llm = RecordingLLM("single-summary")
    summarizer = LLMChunkSummarizer(llm, max_attempts=1)

    assert summarizer.summarize("some text", max_tokens=200) == "single-summary"
    assert len(llm.batches) == 1


def test_llm_chunk_summarizer_single_text_summarize_defaults_budget():
    llm = RecordingLLM("single-summary")
    summarizer = LLMChunkSummarizer(llm, max_attempts=1)

    assert summarizer.summarize("some text") == "single-summary"


def test_llm_chunk_summarizer_single_text_summarize_empty_input():
    summarizer = LLMChunkSummarizer(RecordingLLM())

    assert summarizer.summarize("") == ""
    assert summarizer.summarize("   ") == ""