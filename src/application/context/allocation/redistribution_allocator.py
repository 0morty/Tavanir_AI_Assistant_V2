from collections.abc import Sequence
from dataclasses import replace

from src.application.context.allocation.expansion_request import ExpansionRequest
from src.application.dtos import RedistributionResult


class RedistributionAllocator:
    """Iteratively distribute free capacity among expansion requests by weight.

    Implements ``dynamic_section_capacity_allocation.md``:

    1. Distribute the currently available capacity according to the active
       Sections' normalized weights.
    2. Cap each allocation at the Section's actual remaining need.
    3. Return any unused allocation to the free-capacity pool.
    4. Remove Sections that are fully satisfied.
    5. Re-normalize the weights of the remaining Sections.
    6. Repeat until all Sections are satisfied or no free capacity remains.

    The allocator operates only on ``ExpansionRequest`` values; it never sees
    Sections or their items. Requests are returned with the awarded capacity
    baked into ``allocated_tokens``.
    """

    def redistribute(
        self,
        free_capacity_tokens: int,
        requests: Sequence[ExpansionRequest],
    ) -> RedistributionResult:
        if free_capacity_tokens < 0:
            raise ValueError("free_capacity_tokens must be non-negative")
        if free_capacity_tokens == 0 or not requests:
            return RedistributionResult(tuple(requests), free_capacity_tokens)

        updated: list[ExpansionRequest] = list(requests)
        available = free_capacity_tokens

        while True:
            pending = [
                i for i, request in enumerate(updated) if request.remaining_need > 0
            ]
            if not pending or available == 0:
                break
            total_weight = sum(updated[i].weight for i in pending)
            if total_weight == 0:
                break

            awarded_total = 0
            for index in pending:
                request = updated[index]
                award = min(
                    int(available * request.weight / total_weight),
                    request.remaining_need,
                )
                if award > 0:
                    updated[index] = replace(
                        request,
                        allocated_tokens=request.allocated_tokens + award,
                    )
                    awarded_total += award

            if awarded_total == 0:
                break
            available -= awarded_total

        return RedistributionResult(tuple(updated), available)