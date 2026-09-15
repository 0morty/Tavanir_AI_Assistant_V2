from src.domain.context.overflow.strategy import OverflowStrategy
from src.domain.context.summarizer import Summarizer


class SummarizeStrategy(OverflowStrategy):
    """Overflow strategy that compresses a Section's text to reduce its token usage.

    Compresses the Section's content through an injected :class:`Summarizer`,
    reducing the token footprint while preserving as much relevant meaning as
    possible. The summarizer is injected through the constructor (mirroring how
    :class:`TruncateStrategy` receives its :class:`Tokenizer`), so the strategy
    stays decoupled from any concrete LLM or prompt-building implementation.
    """

    def __init__(self, summarizer: Summarizer) -> None:
        self._summarizer = summarizer

    def apply(self, content: str, capacity: int) -> str:
        """Apply the overflow behavior to ``content`` under ``capacity``.

        Delegates to the injected summarizer, which returns a compressed
        representation of ``content``. ``capacity`` is accepted to satisfy the
        overflow strategy contract; a real summarizer implementation targets it
        when producing the summary, while the fake summarizer ignores it.

        Args:
            content: The Section's content that does not fit its capacity.
            capacity: The available token capacity allocated to the Section.

        Returns:
            The transformed content after applying the overflow behavior.
        """
        return self._summarizer.summarize(content)