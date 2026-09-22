from abc import ABC, abstractmethod
from collections.abc import Sequence

from src.application.dtos import CapacityAllocation, CapacityRequest


class ICapacityAllocator(ABC):
    """Port for Section-level token budget allocation.

    The Section-level allocation policy orchestrated by ``ContextBuilder``:
    split the budget by ``demand``, reclaim unused shares, and redistribute
    the free pool to expansion requests weighted by ``importance``.
    """

    @abstractmethod
    def allocate(
        self,
        requests: Sequence[CapacityRequest],
        budget_tokens: int,
    ) -> CapacityAllocation:
        """Return the final per-key capacities and any unused tokens."""