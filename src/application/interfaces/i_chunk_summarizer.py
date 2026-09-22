from abc import ABC, abstractmethod


class IChunkSummarizer(ABC):
    """Application-layer port for batched LLM chunk summarization.

    Summarizes a collection of chunks, carrying the guarantee of a strict 1:1
    input-to-output mapping: every input chunk yields exactly one summary, in
    the same order, with none lost, merged, reordered, or omitted. Concrete
    adapters (e.g. an OpenAI-compatible LLM chunk summarizer) are injected
    from the infrastructure layer; this port never references a concrete
    provider.
    """

    @abstractmethod
    def summarize(self, chunks: list[str], *, capacity_tokens: int) -> list[str]:
        """Return exactly one summary per input chunk, preserving their order.

        ``capacity_tokens`` bounds the token budget a single batched LLM call
        may occupy; the adapter decides how many chunks fit in each call.
        Raises when the LLM output cannot be mapped strictly 1:1 onto the input
        chunks after the adapter's retries are exhausted.
        """
        pass