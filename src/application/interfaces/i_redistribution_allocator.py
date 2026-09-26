from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING

from src.application.dtos import RedistributionResult

if TYPE_CHECKING:
    from src.application.context.allocation.expansion_request import ExpansionRequest


class IRedistributionAllocator(ABC):
    """Port for iteratively distributing free capacity among expansion requests."""

    @abstractmethod
    def redistribute(
        self,
        free_capacity_tokens: int,
        requests: Sequence[ExpansionRequest],
    ) -> RedistributionResult:
        """Return requests with awarded capacity and any unused capacity."""
