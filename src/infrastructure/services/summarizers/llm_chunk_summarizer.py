from collections.abc import Sequence

from src.application.exceptions import ChunkSummarizationError
from src.application.interfaces.i_llm_client import ILLMClient
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.infrastructure.services.summarizers.chunk_prompt_builder import (
    ChunkPromptBuilder,
)

_DEFAULT_SUMMARIZE_BUDGET = 2048
_DEFAULT_BATCH_SIZE = 32


class LLMChunkSummarizer(ITextSummarizer):
    """Summarize chunks with batch inference, each chunk through its own prompt.

    Chunks are never merged. Every chunk is rendered as its own independent
    prompt (see :class:`ChunkPromptBuilder`) and the ready prompts are handed
    to the LLM through :meth:`ILLMClient.complete_many` as a batch, so the
    provider can submit them in a single HTTP request while keeping a strict
    1:1 ``chunk -> prompt -> summary`` mapping with the input order preserved.
    When the collection spans multiple batches, the remaining chunks are
    processed in subsequent batches.

    Validation is strict per chunk: a summary that comes back empty is
    re-requested up to ``max_attempts`` rounds (retrying only the unresolved
    chunks); persistent failure raises :class:`ChunkSummarizationError` instead
    of silently continuing with a corrupted mapping.

    As part of the aggregate :class:`ITextSummarizer` contract it also exposes
    the single-text :meth:`summarize`, which maps onto the batched path with a
    single chunk.

    The LLM client is injected through the constructor (:class:`ILLMClient`),
    never instantiated here. ``capacity_tokens`` only gates the whole call
    (``<= 0`` produces no summaries); final fitting against the section budget
    is handled downstream by the ``ContextBuilder`` truncation safety net.
    """

    def __init__(
        self,
        llm_client: ILLMClient,
        *,
        builder: ChunkPromptBuilder | None = None,
        max_attempts: int = 3,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self._llm_client = llm_client
        self._builder = builder if builder is not None else ChunkPromptBuilder()
        self._max_attempts = max_attempts
        self._batch_size = batch_size

    def summarize(self, text: str, *, max_tokens: int | None = None) -> str:
        """Return an LLM-produced summary of a single ``text``.

        Routes through the strict batched path with one chunk; ``max_tokens``
        (when given and positive) becomes the batch capacity, otherwise a
        documented default budget is used. The default only gates whether the
        call runs at all, never the prompt contents.
        """
        if not text or not text.strip():
            return ""
        capacity = (
            max_tokens
            if max_tokens is not None and max_tokens > 0
            else _DEFAULT_SUMMARIZE_BUDGET
        )
        return self.summarize_chunks([text], capacity_tokens=capacity)[0]

    def summarize_chunks(
        self, chunks: Sequence[str], *, capacity_tokens: int
    ) -> list[str]:
        """Return exactly one summary per input chunk, preserving their order."""
        if not chunks or capacity_tokens <= 0:
            return []
        results: list[str] = []
        for start in range(0, len(chunks), self._batch_size):
            group = chunks[start : start + self._batch_size]
            results.extend(self._summarize_group(group))
        return results

    def _summarize_group(self, chunks: Sequence[str]) -> list[str]:
        """Summarize one batch of chunks, retrying only unresolved chunks."""
        prompts = [self._builder.build(chunk) for chunk in chunks]
        summaries: list[str] = [""] * len(chunks)
        pending = list(range(len(chunks)))
        attempt = 0
        while pending:
            if attempt >= self._max_attempts:
                raise ChunkSummarizationError(
                    f"Chunk summarization failed after {self._max_attempts} "
                    f"attempt(s): {len(pending)} of {len(chunks)} chunk(s) still "
                    f"have no summary."
                )
            responses = self._llm_client.complete_many([prompts[i] for i in pending])
            unresolved: list[int] = []
            for position, chunk_index in enumerate(pending):
                summary = responses[position] if position < len(responses) else ""
                stripped = (summary or "").strip()
                if stripped:
                    summaries[chunk_index] = stripped
                else:
                    unresolved.append(chunk_index)
            pending = unresolved
            attempt += 1
        return summaries