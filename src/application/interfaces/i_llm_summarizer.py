from abc import ABC, abstractmethod


class ILLMSummarizer(ABC):
    """Application-layer port for LLM-based text summarization.

    This is the seam :class:`ReferencedSection` uses when the ``SUMMARIZE``
    overflow strategy is driven by an LLM summarizer. Concrete adapters (e.g.
    an OpenAI-compatible LLM summarizer) are injected from the infrastructure
    layer; this port never references a concrete provider.

    The optional ``max_tokens`` carries the Section's allocated token budget
    into the summary instruction so the adapter can target it directly; the
    ``ContextBuilder`` truncation safety net still enforces the budget exactly
    when the summary overflows.
    """

    @abstractmethod
    def summarize(self, text: str, *, max_tokens: int | None = None) -> str:
        """Return an LLM-produced summary of ``text``.

        ``max_tokens`` is the target upper bound for the summary, when known.
        """
        pass