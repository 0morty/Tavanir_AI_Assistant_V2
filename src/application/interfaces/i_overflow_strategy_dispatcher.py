from abc import ABC, abstractmethod

from src.application.interfaces.i_compressible_section import CompressibleSection
from src.domain.context.tokenizer import Tokenizer
from src.domain.enums import OverflowStrategy


class IOverflowStrategyDispatcher(ABC):
    """Port mapping an ``OverflowStrategy`` to the matching Section operation."""

    @abstractmethod
    def apply(
        self,
        section: CompressibleSection,
        strategy: OverflowStrategy,
        content: str,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> str | None:
        """Invoke the operation for ``strategy`` on ``section``.

        Return the reduced content as a ``str``, or ``None`` when the strategy
        is not applicable for this Section.
        """