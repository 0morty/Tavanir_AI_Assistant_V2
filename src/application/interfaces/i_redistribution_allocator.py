from abc import ABC, abstractmethod
from collections.abc import Sequence

from src.application.context.allocation.expansion_request import ExpansionRequest
from src.application.dtos import RedistributionResult


class IRedistributionAllocator(ABC):
    """Port for iteratively distributing free capacity among expansion requests."""

    @abstractmethod
    def redistribute(
        self,
        free_capacity_tokens: int,
        requests: Sequence[ExpansionRequest],
    ) -> RedistributionResult:
        """Return requests with awarded capacity and any unused capacity."""