from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import TypeVar

K = TypeVar("K")


class IDemandAllocator(ABC):
    """Port for the proportional initial token split by ``demand``."""

    @abstractmethod
    def allocate(
        self,
        demands: Mapping[K, float],
        budget_tokens: int,
    ) -> dict[K, int]:
        """Return per-key initial capacities summing exactly to ``budget_tokens``."""