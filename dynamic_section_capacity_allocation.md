# Dynamic Section Capacity Allocation

## Implementation status

This model is implemented by the context pipeline in `src/application/context/`:

- **`ContextBuilder`** (`context_builder.py`) — the Context Manager / orchestrator.
  It renders the `PromptBuilder`'s sections (reference resolution happens inside
  each section's `render()`), builds `CapacityRequest` values, delegates the
  allocation to `CapacityAllocator`, fits over-capacity sections through their
  overflow strategy chain, and hands the fitted content to
  `PromptBuilder.assemble()` for the final join. The separator token cost is
  reserved out of the budget, so the resulting prompt never exceeds the limit.
- **`CapacityAllocator`** (`allocation/capacity_allocator.py`) — the allocation
  policy, a plain value-operating algorithm. It splits the budget into initial
  capacities **proportional to each section's `demand`** (`DemandAllocator`),
  returns the unused share of under-filled sections to the free pool, then
  satisfies the over-filled sections' expansion requests by iterative weighted
  redistribution **by `importance`** (`RedistributionAllocator` +
  `ExpansionRequest`), capped at each section's actual need.
- `CapacityRequest(key, demand, importance, needed_tokens)` maps the General
  Model below: `demand` = initial-share weight, `importance` = redistribution
  weight (this model's "weight" concept), `needed_tokens` = the section's content
  size. `demand` and `importance` are independent values in `[0.0, 1.0]` that do
  **not** need to sum to one.

## Overview

The Context Manager is responsible for allocating the available token capacity among prompt sections.

It does **not** decide which specific items should be included inside a section. For example, the Context Manager does not select individual chunks from the `CHUNKS` section. It only determines how much capacity the `CHUNKS` section is allowed to use.

This creates a clear separation of responsibilities:

```text
Context Manager
    → Determines how much capacity each section receives.

Section-specific logic
    → Determines what content fits inside that allocated capacity.
```

## Core Idea

The allocation process works dynamically.

First, all sections are populated with the content they can currently hold. The system calculates how much of the overall context budget remains unused.

For example:

```text
Context Window = 32K
Initial usage  = 22K
Free capacity  = 10K
```

The sections that can make use of additional capacity then submit expansion requests.

Each request contains:

- `requested_tokens`: the amount of additional capacity the section can use.
- `weight`: the section's share of the available capacity.
- `allocated_tokens`: the amount actually assigned during the allocation process.

The weight represents the **relative importance of the section when distributing free capacity**. It is not a relevance score for the content inside the section.

## Example

Assume the following sections need additional capacity:

```text
1. Chunks           → 7K needed
2. History          → 1K needed
3. Regulations      → 100 tokens needed
4. Output Format    → 50 tokens needed
```

Available capacity:

```text
10K
```

Section weights:

```text
1. Chunks           → 0.4
2. History          → 0.3
3. Regulations      → 0.2
4. Output Format    → 0.1
```

The initial weighted allocation is:

```text
Chunks           → 4K
History          → 3K
Regulations      → 2K
Output Format    → 1K
```

However, a section cannot receive more capacity than it actually needs.

Therefore:

```text
Chunks           → 4K allocated, 3K still needed
History          → 1K allocated, fully satisfied
Regulations      → 100 allocated, fully satisfied
Output Format    → 50 allocated, fully satisfied
```

The unused portions of the initial allocation are returned to the free-capacity pool:

```text
History          → 2K unused
Regulations      → 1.9K unused
Output Format    → 950 unused
--------------------------------
Returned capacity → 4.85K
```

The remaining unsatisfied section is:

```text
Chunks → 3K needed
```

Since it is now the only section requesting additional capacity, its normalized weight becomes:

```text
Chunks → 1.0
```

Therefore:

```text
Chunks → +3K
```

The remaining unused capacity is:

```text
4.85K - 3K = 1.85K
```

The allocation process ends because no section requires additional capacity.

## Iterative Redistribution

The allocation algorithm is iterative.

At every iteration:

1. Distribute the currently available capacity according to the active sections' weights.
2. Cap each allocation at the section's actual remaining need.
3. Return any unused allocation to the free-capacity pool.
4. Remove sections that are fully satisfied.
5. Re-normalize the weights of the remaining sections.
6. Repeat until either:
   - all sections are satisfied, or
   - no free capacity remains.

Conceptually:

```text
Free Capacity
      │
      ▼
Weighted Allocation
      │
      ▼
Cap by Actual Need
      │
      ▼
Return Unused Capacity
      │
      ▼
Remove Satisfied Sections
      │
      ▼
Normalize Remaining Weights
      │
      └───────────────► Repeat
```

## Responsibility Boundaries

The Context Manager owns **capacity allocation**, not content selection.

### Context Manager

Responsible for:

- Calculating available token capacity.
- Receiving expansion requests from sections.
- Allocating capacity using section weights.
- Redistributing unused capacity.
- Re-normalizing weights after sections are satisfied.
- Producing the final capacity limit for each section.

### Section-specific Logic

Responsible for:

- Deciding which content belongs in the section.
- Selecting and ordering individual items.
- Packing content within the allocated capacity.
- Truncating or otherwise adapting its own content to fit its capacity.

For example:

```text
Context Manager
    ↓
Chunks capacity = 15K
    ↓
Chunks Section
    ↓
Selects and packs chunks within 15K
```

The Context Manager does not know or care which individual chunks are selected.

## Important Distinction

Section weight and content relevance are different concepts.

```text
Section Weight
    → Determines how capacity is shared among sections.

Content Relevance
    → Determines which items are selected within a section.
```

For example:

```text
Chunks Section
    weight = 0.4
```

does **not** mean that a particular chunk has a relevance score of `0.4`.

It only means that the `CHUNKS` section receives a larger share of available capacity relative to lower-weight sections.

## General Model

A section can conceptually expose an expansion request such as:

```text
Section:
    current_tokens
    requested_tokens
    weight
    allocated_tokens
```

The allocator then operates only on these values.

No `min_tokens`, `max_tokens`, or `desired_tokens` values are required by this allocation model because the allocator works from the section's **actual current content size** and its **actual additional capacity requirement**.

## Design Principle

The key principle is:

> **The Context Manager decides how much space a section gets; the section decides how to use that space.**

This separation keeps budget allocation independent from section-specific content selection and allows each section to implement its own internal strategy without coupling it to the global context allocation algorithm.
