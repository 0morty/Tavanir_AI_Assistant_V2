import re

# Strip bare URLs and markdown link URLs so they do not pollute BM25 vocabulary
_URL_REGEX = re.compile(r"https?://\S+|www\.\S+")

# Replace any character that is NOT a unicode word character, whitespace,
# or Persian Zero-Width Non-Joiner (ZWNJ / \u200c) with a space.
# Note: Underscore (_) is part of \w in Python regex, but is a Markdown delimiter
# and snake_case separator, so it is explicitly treated as whitespace delimiter.
_NON_ALPHA_REGEX = re.compile(r"[^\w\s\u200c]|_")


def clean_text_for_bm25(text: str) -> str:
    """
    Sanitizes raw or Markdown text specifically for Persian lexical BM25 tokenization.

    Actions:
    1. Replaces URLs with whitespace to prevent web addresses from entering the vocabulary.
    2. Case-folds Latin characters to lowercase so technical acronyms (e.g. SCADA vs scada)
       produce matching token hashes regardless of casing (Persian is unaffected).
    3. Replaces all non-alphanumeric characters, Markdown delimiters (including underscores _),
       and punctuation with whitespace.
    4. Preserves Persian letters, numbers, and the Zero-Width Non-Joiner (نیم‌فاصله \u200c)
       to ensure compound words (e.g. صرفه‌جویی, پیشنهادها) remain intact.
    5. Guarantees word boundaries are maintained with spaces, avoiding the word-fusion bug
       where adjacent tokens fuse when punctuation is removed without space substitution.
    """
    if not text:
        return ""

    text_no_urls = _URL_REGEX.sub(" ", text).lower()
    return _NON_ALPHA_REGEX.sub(" ", text_no_urls)


__all__ = ["clean_text_for_bm25"]
