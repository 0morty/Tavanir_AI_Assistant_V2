from collections.abc import Mapping
from typing import TypeVar

K = TypeVar("K")


class DemandAllocator:
    """Split a token budget into initial proportional capacities by demand.

    The initial capacity of every Section is proportional to its ``demand``,
    normalized against the demand of the other active Sections
    (``section_properties.md``). The allocator works only on capacity numbers;
    it never sees Sections or their items.

    Budget tokens are assigned with the largest-remainder (Hamilton) method so
    the integer capacities always sum exactly to the budget. A Section whose
    demand is zero receives no initial capacity. Sections that cannot use all
    of their initial share give it back during redistribution.
    """

    def allocate(
        self,
        demands: Mapping[K, float],
        budget_tokens: int,
    ) -> dict[K, int]:
        if budget_tokens < 0:
            raise ValueError("budget_tokens must be non-negative")
        if not demands:
            return {}
        for value in demands.values():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"demand must be in [0.0, 1.0], got {value!r}")

        if budget_tokens == 0:
            return {key: 0 for key in demands}

        total_demand = sum(demands.values())
        if total_demand == 0:
            base, remainder = divmod(budget_tokens, len(demands))
            capacities = {key: base for key in demands}
            for key in list(demands)[:remainder]:
                capacities[key] += 1
            return capacities

        capacities: dict[K, int] = {}
        fractional_parts: dict[K, float] = {}
        assigned = 0
        for key, demand in demands.items():
            exact = budget_tokens * demand / total_demand
            floor = int(exact)
            capacities[key] = floor
            fractional_parts[key] = exact - floor
            assigned += floor

        leftover = budget_tokens - assigned
        for key in sorted(demands, key=lambda k: -fractional_parts[k]):
            if leftover == 0:
                break
            capacities[key] += 1
            leftover -= 1
        return capacities