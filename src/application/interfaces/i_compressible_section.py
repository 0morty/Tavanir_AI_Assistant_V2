from abc import ABC, abstractmethod

from src.domain.context.summarizer import Summarizer
from src.domain.context.tokenizer import Tokenizer


class CompressibleSection(ABC):
    """Contract for Sections whose content can be reduced to consume less space.

    A ``CompressibleSection`` can be truncated, summarized, or partially
    ignored when its content exceeds its allocated capacity. This abstract
    class defines the contract only -- it contains no implementation of any
    operation. The plain-text defaults live on the ``PromptSection`` skeleton;
    ``ReferencedSection`` inherits the contract for the reference-aware branch
    and uses those same defaults, while ``ReferencedCollectionSection``
    overrides the operations according to its own item-aware representation.

    Every operation receives the Section's ``content`` plus the available
    ``capacity_tokens`` and returns the reduced content, or ``None`` when the
    operation is not applicable to (or cannot be executed for) this Section --
    in which case the caller moves on to the next strategy in the Section's
    overflow stack.

    ``truncate`` is a universal operation: ``text + maximum_allowed_tokens ->
    truncated text``. It knows nothing about chunks, references, list
    semantics, or domain models; a Section decides how to apply this universal
    behavior to its own representation.
    """

    @abstractmethod
    def truncate(
        self,
        content: str,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> str | None:
        """Reduce ``content`` to the largest prefix that fits ``capacity_tokens``.

        ``tokenizer`` drives the universal truncation algorithm.
        """

    @abstractmethod
    def summarize(
        self,
        content: str,
        capacity_tokens: int,
        *,
        summarizer: Summarizer,
    ) -> str | None:
        """Compress ``content`` through ``summarizer`` to reduce its token usage."""

    @abstractmethod
    def ignore(
        self,
        content: str,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> str | None:
        """Exclude parts of ``content`` that cannot fit within ``capacity_tokens``.

        Returns ``None`` when there is nothing to drop (e.g. a single plain
        text), so the caller can fall through to the next strategy.
        """