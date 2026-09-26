from abc import ABC, abstractmethod


class ITextSummarizer(ABC):
    """Aggregate application-layer port for LLM text summarization.

    This is the single seam every Generation summarizer adapter implements,
    covering both summarization flavors the prompt Sections consume:

    - :meth:`summarize` compresses a single text (used by
      :class:`~src.application.context.sections.referenced_section.ReferencedSection`).
    - :meth:`summarize_chunks` compresses a collection of chunks with a strict
      one-summary-per-chunk guarantee (used by reference-bearing collection
      sections such as :class:`~src.application.context.sections.chunks_section.ChunksSection`).

    Concrete adapters (e.g. OpenAI-compatible LLM summarizers) are injected
    from the infrastructure layer and must implement both capabilities; this
    port never references a concrete provider.
    """

    @abstractmethod
    def summarize(self, text: str, *, max_tokens: int | None = None) -> str:
        """Return an LLM-produced summary of ``text``.

        ``max_tokens`` is the target upper bound for the summary, when known.
        """
        pass

    @abstractmethod
    def summarize_chunks(self, chunks: list[str], *, capacity_tokens: int) -> list[str]:
        """Return exactly one summary per input chunk, preserving their order.

        ``capacity_tokens`` bounds the token budget a single batched LLM call
        may occupy. Raises when an adapter cannot map the LLM output strictly
        1:1 onto the input chunks after its retries are exhausted.
        """
        pass