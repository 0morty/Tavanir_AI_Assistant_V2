from abc import ABC, abstractmethod


class Summarizer(ABC):
    """Summarization capability contract for context overflow handling.

    This abstraction exposes the capability the ``SUMMARIZE`` overflow strategy
    needs: compressing a text into a shorter representation while preserving as
    much relevant meaning as possible. Concrete summarizer implementations
    (e.g. an LLM-based semantic compressor) are injected from outside; this
    class never instantiates or references them.
    """

    @abstractmethod
    def summarize(self, text: str) -> str:
        """Return a compressed/summarized representation of ``text``."""
        pass