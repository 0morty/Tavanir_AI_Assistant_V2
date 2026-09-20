from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from src.application.context.allocation.demand_allocator import DemandAllocator
from src.application.context.allocation.expansion_request import ExpansionRequest
from src.application.context.allocation.redistribution_allocator import (
    RedistributionAllocator,
)


@dataclass(frozen=True)
class CapacityRequest:
    """Per-section allocation information consumed by :class:`CapacityAllocator`.

    ``demand`` is the Section's relative request for initial capacity, and
    ``importance`` is its weight when the free capacity is redistributed --
    two independent values in ``[0.0, 1.0]`` that do not need to sum to one.
    ``needed_tokens`` is the amount of capacity the Section can actually use
    (its already-rendered content size).
    """

    key: str
    demand: float
    importance: float
    needed_tokens: int

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("CapacityRequest key must be a non-empty string")
        if not 0.0 <= self.demand <= 1.0:
            raise ValueError(
                f"CapacityRequest demand must be in [0.0, 1.0], got {self.demand!r}"
            )
        if not 0.0 <= self.importance <= 1.0:
            raise ValueError(
                f"CapacityRequest importance must be in [0.0, 1.0], "
                f"got {self.importance!r}"
            )
        if self.needed_tokens < 0:
            raise ValueError(
                f"CapacityRequest needed_tokens must be non-negative, "
                f"got {self.needed_tokens!r}"
            )


@dataclass(frozen=True)
class CapacityAllocation:
    """The outcome of :meth:`CapacityAllocator.allocate`."""

    capacities: Mapping[str, int]
    unused_tokens: int


class CapacityAllocator:
    """Turn Section allocation properties into final capacities.

    This is the Section-level allocation policy of
    ``dynamic_section_capacity_allocation.md``, orchestrated by
    ``ContextBuilder``:

    1. Split the budget into initial capacities proportional to ``demand``
       (``DemandAllocator``).
    2. Sections that need less than their share give the difference back to
       the free-capacity pool.
    3. Sections that need more submit expansion requests weighted by
       ``importance``, which are satisfied from the free pool by iterative
       weighted redistribution, capped at each Section's actual need
       (``RedistributionAllocator``).

    The policy works only on values -- ``CapacityRequest`` entries -- and
    never sees Sections, chunks, the tokenizer, or the LLM. Overflow handling
    (packing content into the returned capacity) is deliberately out of scope.
    """

    def allocate(
        self,
        requests: Sequence[CapacityRequest],
        budget_tokens: int,
    ) -> CapacityAllocation:
        if budget_tokens < 0:
            raise ValueError("budget_tokens must be non-negative")
        if not requests:
            return CapacityAllocation({}, budget_tokens)

        seen = set()
        for request in requests:
            if request.key in seen:
                raise ValueError(f"Duplicate CapacityRequest key {request.key!r}")
            seen.add(request.key)

        initial = DemandAllocator().allocate(
            {request.key: request.demand for request in requests},
            budget_tokens,
        )

        capacities: dict[str, int] = {}
        free_capacity = 0
        request_keys: list[str] = []
        expansion_requests: list[ExpansionRequest] = []
        for request in requests:
            share = initial[request.key]
            need = request.needed_tokens
            if need < share:
                free_capacity += share - need
                capacities[request.key] = need
            else:
                capacities[request.key] = share
                request_keys.append(request.key)
                expansion_requests.append(
                    ExpansionRequest(
                        requested_tokens=need - share,
                        weight=request.importance,
                    )
                )

        result = RedistributionAllocator().redistribute(
            free_capacity, expansion_requests
        )
        for key, updated in zip(request_keys, result.allocations):
            capacities[key] += updated.allocated_tokens

        return CapacityAllocation(capacities, result.unused_capacity)