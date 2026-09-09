from abc import ABC, abstractmethod

from src.application.prompt_architecture.section_type import PromptSectionType


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
    is optional and defaults to empty strings.
    """

    def __init__(self, separator: str = "\n\n") -> None:
        self.separator = separator

    @property
    @abstractmethod
    def section_type(self) -> PromptSectionType:
        """First-class identity of this section (e.g. HISTORY, CHUNKS)."""

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
        """Render the complete section by combining pre-context, body, and post-context."""
        parts = [self.pre_context, self.body(), self.post_context]
        return self.separator.join(part for part in parts if part)