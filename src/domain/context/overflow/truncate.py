from src.domain.context.overflow.strategy import OverflowStrategy
from src.domain.context.tokenizer import Tokenizer


class TruncateStrategy(OverflowStrategy):
    """Overflow strategy that reduces a Section's text to a prefix that fits the token budget.

    Selects the token boundary directly from a single tokenization pass: the
    injected :class:`Tokenizer` returns each token paired with its character
    offsets, and those offsets are used to slice a byte-exact prefix of the
    original text. The output is never decoded or reconstructed.
    """

    def __init__(self, tokenizer: Tokenizer) -> None:
        self._tokenizer = tokenizer

    def apply(self, content: str, capacity: int) -> str:
        """Apply the overflow behavior to ``content`` under ``capacity``.

        Truncates *content* to the longest prefix whose token count does not
        exceed *capacity* by selecting the fitting token boundary directly
        from the offset mapping of a single encoder call. The result is a
        byte-exact slice of the original string.

        Args:
            content: The Section's content that does not fit its capacity.
            capacity: The available token capacity allocated to the Section.

        Returns:
            The transformed content after applying the overflow behavior.
        """
        if not content or capacity <= 0:
            return ""

        encoding = self._tokenizer.encode(content)

        if len(encoding) <= capacity:
            return content

        content_tokens = [
            (token_id, (start, end))
            for token_id, (start, end) in encoding
            if (start, end) != (0, 0)
        ]

        allowed_content_tokens = capacity - (len(encoding) - len(content_tokens))

        if allowed_content_tokens <= 0:
            return ""

        cutoff = content_tokens[allowed_content_tokens - 1][1][1]
        return content[:cutoff]