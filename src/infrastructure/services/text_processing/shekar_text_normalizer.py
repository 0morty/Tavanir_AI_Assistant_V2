import asyncio
import re
from collections.abc import Sequence
from typing import cast
from uuid import uuid4

import structlog
from shekar.preprocessing import (
    AlphabetNormalizer,
    ArabicUnicodeNormalizer,
    EmojiRemover,
    PunctuationNormalizer,
    RemoveDiacritics,
    RepeatedLetterNormalizer,
    SpacingNormalizer,
    YaNormalizer,
)

from src.application.exceptions import TextNormalizationError
from src.application.interfaces.i_text_normalizer import ITextNormalizer

_logger = structlog.stdlib.get_logger(__name__)

# Translation table mapping both Persian (U+06F0-U+06F9) and Arabic-Indic (U+0660-U+0669) digits to ASCII (0-9)
_DIGIT_TO_ASCII_TABLE = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)

# Regex to detect and protect fenced code blocks (e.g., ```python ... ``` or ~~~ ... ~~~)
_CODE_BLOCK_REGEX = re.compile(r"^(```+|~~~+)[^\n]*\n[\s\S]*?\n\1\s*$", re.MULTILINE)

# Regex to detect and protect inline code spans (`...` or ``...``)
_INLINE_CODE_REGEX = re.compile(r"(`+)[^\n`]+?\1")

# Regex to detect and protect LaTeX / Math expressions ($...$ and $$...$$)
_MATH_BLOCK_REGEX = re.compile(r"\$\$[\s\S]*?\$\$|\$[^\$\n]+?\$")

# Regex to detect and protect HTML comments and tags
_HTML_REGEX = re.compile(r"<!--[\s\S]*?-->|<[a-zA-Z/][^>]*>")

# Regex to detect and protect horizontal rules (---, ***, ___)
_HORIZONTAL_RULE_REGEX = re.compile(
    r"^[ \t]*([*-_])(?:[ \t]*\1){2,}[ \t]*$", re.MULTILINE
)

# Regex to detect and protect Markdown table separator rows (e.g., | :---: | --- |)
_TABLE_DIVIDER_REGEX = re.compile(r"^[ \t]*\|(?:\s*:?-+:?\s*\|)+[ \t]*$", re.MULTILINE)

# Regex to detect and protect Markdown links and images:
# Keeps '![' and target '](url)' intact while allowing anchor/alt text to be Persian-normalized
_MD_LINK_OR_IMG_REGEX = re.compile(r"(!?\[)([^\]\r\n]*?)(\]\([^\)\r\n]+\))")

# Regex to detect bare URLs
_BARE_URL_REGEX = re.compile(r"https?://[^\s<>\"')]+|www\.[^\s<>\"')]+")

# Regex to detect and protect GitHub alert / callout tags (e.g., [!NOTE], [!IMPORTANT])
_ALERT_TAG_REGEX = re.compile(r"(\[!?(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION)\])")

# Regex to detect and protect ATX heading markers (e.g., '# ', '### ') to prevent RepeatedLetterNormalizer from collapsing '###' to '##'
_HEADING_PREFIX_REGEX = re.compile(r"^[ \t]*(#{1,6}[ \t]+)", re.MULTILINE)

# Regex to detect and protect task list checkboxes (e.g., '- [ ] ', '* [x] ') to prevent SpacingNormalizer from stripping space inside '[ ]'
_TASK_LIST_REGEX = re.compile(r"^[ \t]*([-*+][ \t]+\[[ xX]\][ \t]+)", re.MULTILINE)

# Regex to detect and protect blockquote prefixes (e.g., '> ', '>> ')
_BLOCKQUOTE_PREFIX_REGEX = re.compile(r"^[ \t]*((?:>[ \t]*)+)", re.MULTILINE)

# Regex to detect and protect list indentation (2 or more leading spaces with a bullet)
_NESTED_LIST_INDENT_REGEX = re.compile(
    r"^([ \t]{2,}(?:[-*+]|\d+\.)[ \t]+)", re.MULTILINE
)

# Regex to detect and protect triple bold-italic delimiters (*** or ___)
_BOLD_ITALIC_DELIM_REGEX = re.compile(r"(\*{3,}|_{3,})")

# Post-processing regexes to repair formatting artifacts introduced by spacing normalizers:
# 1. Decimal number space repair (e.g., '0. 5' -> '0.5')
_DECIMAL_SPACE_REGEX = re.compile(r"(?<=\d)\.\s+(?=\d)")
# 2. Closing bold/italic delimiter space repair after Persian/ASCII punctuation (e.g., 'متن. **' -> 'متن.**')
_CLOSING_DELIM_SPACE_REGEX = re.compile(
    r"([…،:\.؟!؛])[^\S\r\n]+(\*+|_+)(?=[^\S\r\n]|$)"
)

# Declarative registry: patterns whose full match (group 0) is masked verbatim
_VERBATIM_PATTERNS: tuple[re.Pattern[str], ...] = (
    _CODE_BLOCK_REGEX,
    _INLINE_CODE_REGEX,
    _MATH_BLOCK_REGEX,
    _HTML_REGEX,
    _HORIZONTAL_RULE_REGEX,
    _TABLE_DIVIDER_REGEX,
    _BARE_URL_REGEX,
)

# Declarative registry: structural patterns whose prefix capture (group 1) is masked
_PREFIX_PATTERNS: tuple[re.Pattern[str], ...] = (
    _ALERT_TAG_REGEX,
    _HEADING_PREFIX_REGEX,
    _TASK_LIST_REGEX,
    _BLOCKQUOTE_PREFIX_REGEX,
    _NESTED_LIST_INDENT_REGEX,
    _BOLD_ITALIC_DELIM_REGEX,
)


import secrets
import string


def _generate_nonce(length: int = 16) -> str:
    chars = string.ascii_uppercase + string.digits
    nonce: list[str] = []
    last: str | None = None
    for _ in range(length):
        c = secrets.choice(chars)
        while c == last:
            c = secrets.choice(chars)
        nonce.append(c)
        last = c
    return "".join(nonce)


class TokenStore:
    """
    Encapsulates thread-safe, call-local token masking and restoration
    for preserving Markdown architecture during Persian text normalization.
    Uses dynamic per-instance nonces to prevent collision with literal text.
    """

    __slots__ = ("_tokens", "_nonce")

    def __init__(self) -> None:
        self._tokens: list[str] = []
        self._nonce: str = _generate_nonce()

    def mask(self, val: str) -> str:
        """Stores a raw string slice and returns a collision-safe placeholder."""
        self._tokens.append(val)
        return f"__TAV_{self._nonce}_{len(self._tokens) - 1}__"

    def restore(self, text: str) -> str:
        """Restores all protected tokens in reverse order of discovery."""
        for i in range(len(self._tokens) - 1, -1, -1):
            text = text.replace(f"__TAV_{self._nonce}_{i}__", self._tokens[i])
        return text


class ShekarTextNormalizer(ITextNormalizer):
    """
    Persian text normalization service powered by the Shekar library.

    Responsibilities:
    - Standardizes Persian alphabet and characters (ي -> ی, ك -> ک, etc.)
    - Removes emojis and diacritics (harakat/erab)
    - Normalizes repeated characters and zero-width non-joiners (half-spaces)
    - Converts Persian/Arabic digits uniformly to English/ASCII digits (0-9)
    - Strictly preserves Markdown architecture and syntax (headings, code blocks,
      inline code, tables, links, images, task lists, blockquotes, math, and lists)
    - Provides non-blocking asynchronous execution via asyncio.to_thread
    """

    def __init__(self, normalize_digits_to_ascii: bool = True):
        self._normalize_digits_to_ascii = normalize_digits_to_ascii
        self._normalizer = (
            AlphabetNormalizer()
            | ArabicUnicodeNormalizer()
            | PunctuationNormalizer()
            | RemoveDiacritics()
            | RepeatedLetterNormalizer()
            | SpacingNormalizer()
            | YaNormalizer(style="joda")
            | EmojiRemover()
        )

    def normalize(self, text: str) -> str:
        """
        Synchronously normalizes a Persian text string while protecting Markdown syntax.

        Args:
            text: Raw input string.

        Returns:
            Normalized and cleaned string.

        Raises:
            TextNormalizationError: If an unexpected error occurs during normalization.
        """
        if not text:
            return ""

        try:
            store = TokenStore()

            # 1. Declarative verbatim block masking (code blocks, inline code, math, HTML, rules, tables, bare URLs)
            for pattern in _VERBATIM_PATTERNS:
                text = pattern.sub(lambda m: store.mask(m.group(0)), text)

            # 2. Markdown links and images masking (preserves syntax and URL, leaves anchor text unmasked for NLP)
            text = _MD_LINK_OR_IMG_REGEX.sub(
                lambda m: (
                    f"{store.mask('![') if m.group(1) == '![' else '['}{m.group(2)}{store.mask(m.group(3))}"
                ),
                text,
            )

            # 3. Declarative structural prefix masking (alerts, headings, tasks, quotes, indents, bold-italic)
            for pattern in _PREFIX_PATTERNS:
                text = pattern.sub(lambda m: store.mask(m.group(1)), text)

            # 4. Apply Shekar normalization pipeline
            cleaned_text = cast(str, self._normalizer.fit_transform(text))

            # 5. Convert Persian/Arabic digits to ASCII digits
            if self._normalize_digits_to_ascii:
                cleaned_text = cleaned_text.translate(_DIGIT_TO_ASCII_TABLE)

            # 6. Repair decimal spacing and restore original Markdown tokens
            cleaned_text = _DECIMAL_SPACE_REGEX.sub(".", cleaned_text)
            cleaned_text = store.restore(cleaned_text)

            # 7. Repair closing delimiter whitespace after tokens are restored (e.g., 'متن. ***' -> 'متن.***')
            return _CLOSING_DELIM_SPACE_REGEX.sub(r"\1\2", cleaned_text)

        except Exception as e:
            _logger.error("Persian text normalization failed", error=str(e))
            raise TextNormalizationError(
                f"Failed to normalize Persian text: {e}"
            ) from e

    async def normalize_async(self, text: str) -> str:
        """
        Asynchronously normalizes a text string on a worker thread.

        Prevents blocking FastAPI's event loop during CPU-bound NLP transformations.
        """
        return await asyncio.to_thread(self.normalize, text)

    def normalize_batch(self, texts: Sequence[str]) -> list[str]:
        """
        Synchronously normalizes a sequence of text strings.

        Returns an empty list if `texts` is empty.
        """
        if not texts:
            return []
        return [self.normalize(t) for t in texts]

    async def normalize_batch_async(self, texts: Sequence[str]) -> list[str]:
        """
        Asynchronously normalizes a sequence of text strings via worker thread.
        """
        return await asyncio.to_thread(self.normalize_batch, texts)
