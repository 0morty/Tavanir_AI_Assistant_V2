from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from src.application.context.allocation.expansion_request import ExpansionRequest
    from src.domain.entities import HistoryMessage


@dataclass
class AnalyzeSuggestionResponse:
    # 1. Dynamic LLM Output (Markdown)
    analysis: str

    # 2. Complete Provenance for all 5 Status Partitions
    similar_executed_ids: list[str] = field(default_factory=list)
    similar_approved_ids: list[str] = field(default_factory=list)
    similar_pending_ids: list[str] = field(default_factory=list)
    similar_rejected_ids: list[str] = field(default_factory=list)
    similar_not_accepted_ids: list[str] = field(default_factory=list)

    # 3. Applicable Statutes & Distances
    applied_statute_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SectionOutput:
    """Per-section result after budgeting, reference handling, and overflow fitting.

    history_messages contains fitted chat turns for HISTORY. It is None for
    other sections and a tuple (possibly empty) for processed history.
    """

    section_type: str
    content: str
    requested_tokens: int
    capacity_tokens: int
    fitted_tokens: int
    overflowed: bool
    history_messages: tuple[HistoryMessage, ...] | None = None


@dataclass(frozen=True)
class ContextBuilderResult:
    """Final rendered prompt, per-section accounting, and assembly separator."""

    prompt: str
    sections: tuple[SectionOutput, ...]
    budget_tokens: int
    total_tokens: int
    section_separator: str = "\n\n"


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


@dataclass(frozen=True)
class RedistributionResult:
    """The outcome of a redistribution pass over expansion requests."""

    allocations: tuple[ExpansionRequest, ...]
    unused_capacity: int