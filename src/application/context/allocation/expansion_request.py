from dataclasses import dataclass


@dataclass(frozen=True)
class ExpansionRequest:
    """A Section's request for additional capacity beyond its current allocation.

    ``requested_tokens`` is the additional capacity the Section can actually
    use, ``weight`` is the Section's relative share of the free capacity
    (its ``weight``/importance), and ``allocated_tokens`` records how much
    was actually assigned during the allocation process.

    See ``dynamic_section_capacity_allocation.md`` for the allocation model.
    """

    requested_tokens: int
    weight: float
    allocated_tokens: int = 0

    def __post_init__(self) -> None:
        if self.requested_tokens < 0:
            raise ValueError("requested_tokens must be non-negative")
        if self.allocated_tokens < 0:
            raise ValueError("allocated_tokens must be non-negative")
        if self.allocated_tokens > self.requested_tokens:
            raise ValueError("allocated_tokens cannot exceed requested_tokens")
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError("weight must be in [0.0, 1.0]")

    @property
    def remaining_need(self) -> int:
        """Capacity still required to fully satisfy this request."""
        return self.requested_tokens - self.allocated_tokens