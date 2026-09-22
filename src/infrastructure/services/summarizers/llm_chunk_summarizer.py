from src.application.exceptions import ChunkSummarizationError
from src.application.interfaces.i_llm_client import ILLMClient
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.domain.context.tokenizer import Tokenizer
from src.infrastructure.services.summarizers.chunk_prompt_builder import (
    ChunkPromptBuilder,
)

_DEFAULT_SUMMARIZE_BUDGET = 2048


class LLMChunkSummarizer(ITextSummarizer):
    """Summarize chunks in batches, one LLM call per batch.

    Each batch is the greedy prefix of the remaining chunks whose serialized
    prompt cost (fixed sections + chunk separators) fits ``capacity_tokens``,
    so as many chunks as possible share a single call while the collection can
    never exceed the token budget for that call. Progress is guaranteed: when
    even one chunk overflows the budget the batch still takes a single chunk
    (the outer ``ContextBuilder`` truncation safety net absorbs the excess).

    Validation is strict: the model response must contain exactly one non-empty
    summary per input chunk, in the same order. A response that merges, omits,
    reorders, or invents summaries is re-requested up to ``max_attempts`` times;
    persistent failure raises :class:`ChunkSummarizationError` instead of
    silently continuing with a corrupted mapping.

    As part of the aggregate :class:`ITextSummarizer` contract it also exposes
    the single-text :meth:`summarize`, which maps onto the batched path with a
    single chunk.

    The LLM client and tokenizer are injected through the constructor
    (:class:`ILLMClient` / :class:`Tokenizer`), never instantiated here.
    """

    def __init__(
        self,
        llm_client: ILLMClient,
        tokenizer: Tokenizer,
        *,
        builder: ChunkPromptBuilder | None = None,
        max_attempts: int = 3,
        capacity_reserve: int = 0,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if capacity_reserve < 0:
            raise ValueError("capacity_reserve must be non-negative")
        self._llm_client = llm_client
        self._tokenizer = tokenizer
        self._builder = builder if builder is not None else ChunkPromptBuilder()
        self._max_attempts = max_attempts
        self._capacity_reserve = capacity_reserve

    def summarize(self, text: str, *, max_tokens: int | None = None) -> str:
        """Return an LLM-produced summary of a single ``text``.

        Routes through the strict batched path with one chunk; ``max_tokens``
        (when given) becomes the batch capacity, otherwise a documented default
        budget is used.
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
        self, chunks: list[str], *, capacity_tokens: int
    ) -> list[str]:
        """Return exactly one summary per input chunk, preserving their order."""
        if not chunks or capacity_tokens <= 0:
            return []
        results: list[str] = []
        remaining = list(chunks)
        while remaining:
            batch = self._choose_batch(remaining, capacity_tokens)
            prompt = self._builder.build(batch)
            results.extend(self._summarize_batch(batch, prompt))
            remaining = remaining[len(batch) :]
        return results

    def _choose_batch(self, chunks: list[str], capacity_tokens: int) -> list[str]:
        """The greedy prefix of ``chunks`` whose prompt fits the capacity."""
        available = max(0, capacity_tokens - self._capacity_reserve)
        overhead = self._tokenizer.count_tokens(self._builder.build([]))
        separator_cost = self._tokenizer.count_tokens(self._builder.CHUNK_SEPARATOR)
        batch: list[str] = []
        used = 0
        for chunk in chunks:
            chunk_cost = self._tokenizer.count_tokens(chunk)
            cost = separator_cost if batch else 0
            if overhead + used + cost + chunk_cost > available:
                break
            batch.append(chunk)
            used += cost + chunk_cost
        if not batch:
            batch.append(chunks[0])
        return batch

    def _summarize_batch(self, batch: list[str], prompt: str) -> list[str]:
        """Strictly map the model response back onto the batch, with retries."""
        expected = len(batch)
        last_detail = "no response"
        for _ in range(self._max_attempts):
            response = self._llm_client.complete(prompt).strip()
            parts = self._builder.split(response)
            if len(parts) == expected and all(parts):
                return parts
            last_detail = f"expected {expected} summaries, got {len(parts)}"
        raise ChunkSummarizationError(
            f"Chunk summarization failed after {self._max_attempts} attempt(s): "
            f"{last_detail}."
        )