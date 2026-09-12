from abc import ABC, abstractmethod


class PromptSection(ABC):
    """Contract and general rendering algorithm for every prompt section.

    Every section renders as three stacked parts:

    +--------------+
    | pre-context  |
    +--------------+
    |     body     |
    +--------------+
    | post-context |
    +--------------+

    Subclasses own the section's identity and body construction by
    overriding ``section_type`` and ``body()``; pre/post context framing
    is optional and defaults to empty strings. A section whose ``body()``
    is empty renders as an empty string, so unconfigured sections never
    leak framing or separators into the final prompt.
    """

    def __init__(self, separator: str = "\n\n") -> None:
        self.separator = separator

    @property
    @abstractmethod
    def section_type(self) -> str:
        """Identity/name of this section, e.g. "HISTORY" or "CHUNKS"."""

    @property
    def pre_context(self) -> str:
        return ""

    @property
    def post_context(self) -> str:
        return ""

    @abstractmethod
    def body(self) -> str:
        """Build the section's main content."""

    def render(self) -> str:
        """Render the complete section by combining pre-context, body, and post-context.

        Returns an empty string when the body is empty, so that an
        unconfigured section is skipped entirely by the builder.
        """
        body = self.body()
        if not body or not body.strip():
            return ""
        parts = [self.pre_context, body, self.post_context]
        return self.separator.join(part for part in parts if part)