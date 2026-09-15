from src.domain.context.summarizer import Summarizer


FAKE_SUMMARY_TEXT = "[fake-summarizer-output]"


class FakeSummarizer(Summarizer):
    """Deterministic stand-in for the real LLM-based summarizer.

    Always returns the static :data:`FAKE_SUMMARY_TEXT` regardless of the input
    text, giving tests and callers a predictable result until the real
    LLM-driven summarizer exists. The real implementation can be swapped in at
    the injection point without touching :class:`SummarizeStrategy`.
    """

    def summarize(self, text: str) -> str:
        """Return the static fake summary, ignoring ``text``."""
        return FAKE_SUMMARY_TEXT