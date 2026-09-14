# Overflow Strategies: `OverflowStrategy` and `OverflowStrategyStack`

This document defines the **data model** for what happens when a Section's
content cannot fit within its allocated context capacity, and the **conceptual
semantics** of each strategy. It deliberately does **not** describe implementation
algorithms — strategy **execution, fallback, success/failure detection, retry,
and restart algorithms are out of scope** and are not implemented.

## Vocabulary

`OverflowStrategy` (enum, `src/domain/enums.py`) is the strategy vocabulary:

| Member | Value | Intended meaning |
|---|---|---|
| `TRUNCATE` | `"truncate"` | Reduce the Section's text to a prefix that fits the token budget |
| `SUMMARIZE` | `"summarize"` | LLM-based semantic compression that reduces token usage while preserving meaning |
| `IGNORE` | `"ignore"` | Exclude individual items (in list-based Sections) that cannot fit within the available capacity |

See [Strategy Semantics](#strategy-semantics) below for the precise meaning of
each strategy.

## Strategy Semantics

An overflow strategy defines **what a Section does when its content cannot fit
into its available capacity**. Strategies operate on a Section's own content;
they do **not** allocate capacity. Capacity allocation is owned by the Context
Manager (see [Architectural Boundary](#architectural-boundary)).

### `TRUNCATE`

`TRUNCATE` reduces a text to fit within a specified token capacity by taking a
**prefix** of the original text.

```text
original text
    ↓
text[0:n]
    ↓
exactly m tokens (or the maximum number of tokens that can fit)
```

Semantic points:

- Truncation operates on **text**.
- The retained portion starts at index `0`.
- The retained content is a **prefix** of the original text — nothing before the
  truncation boundary is altered.
- The target constraint is a **token budget**, not a character count.
- Token accounting must go through the model-neutral tokenizer abstraction
  (`ITokenizer`, `src/application/interfaces/i_tokenizer.py`), never a
  model-specific tokenizer directly — characters are **not** assumed to
  correspond to tokens.
- `TRUNCATE` **loses information**: content after the truncation boundary is
  discarded.

### `SUMMARIZE`

`SUMMARIZE` should be understood more precisely as **compression** rather than
merely producing a short natural-language summary. Its purpose is to reduce the
token footprint of a text while preserving as much of its relevant semantic
information as possible.

```text
original text
    ↓
LLM-based semantic compression
    ↓
shorter text
    ↓
fits within the allocated token capacity
```

Semantic points:

- Compression is performed by an **LLM**.
- The objective is to reduce **token usage**.
- The compressed representation should preserve the meaning and information
  relevant to the **Section's purpose**.
- Unlike `TRUNCATE`, compression does **not** simply retain a prefix.
- The resulting text may be **substantially different in wording and structure**
  from the original.
- Because compression is performed by an LLM, semantic information loss
  **cannot be guaranteed to be zero**.

### `IGNORE`

`IGNORE` has a different semantic from the previous two strategies. It applies
particularly to Sections whose content consists of a **collection/list of items**,
such as a `ChunksSection`.

The Section adds items to the context while capacity is available. Once the
Section reaches its available capacity, remaining items are ignored.

```text
items:
[A, B, C, D, E, F]

capacity allows:
[A, B, C, D]

result:
[A, B, C, D]

ignored:
[E, F]
```

Semantic points:

- `IGNORE` does **not** modify an individual item.
- It does **not** truncate the item's text.
- It does **not** summarize/compress the item.
- It simply **excludes items** that cannot fit within the Section's available
  capacity.
- This strategy is particularly natural for list-based Sections such as retrieved
  Chunks.
- The **Section-specific logic** determines which items are considered and in what
  order.
- The **Context Manager/Allocator** is responsible for capacity allocation;
  `IGNORE` does **not** perform global capacity allocation.

### Strategy Semantics Summary

```text
TRUNCATE   → keep a prefix of the text, discard the rest (token-budget-targeted)
SUMMARIZE  → LLM-compress the text to reduce token usage while preserving meaning
IGNORE     → exclude whole items (in list-based Sections) that cannot fit
```

## Configuration object

`OverflowStrategyStack` (`src/domain/overflow_strategy_stack.py`) is a pure
configuration/state value object that pairs with the enum:

| Member | Type | Description |
|---|---|---|
| `strategies` | `tuple[OverflowStrategy, ...]` (property) | Ordered strategy list; **a lower index means a higher priority** (`strategies[0]` is tried first) |
| `restart` | `bool` (property) | Whether the sequence may restart after all strategies are exhausted |
| `max_restarts` | `int` (property) | How many times the sequence may restart |

Constructor defaults: `strategies=None` → `(TRUNCATE, IGNORE)`,
`restart=False`, `max_restarts=0`.

For example, `[SUMMARIZE, TRUNCATE, IGNORE]` means `SUMMARIZE` has the highest
priority, falling back to `TRUNCATE`, then `IGNORE`.

Validation:

- at least one strategy is required
- every entry must be an `OverflowStrategy` member
- `restart` must be a real `bool`
- `max_restarts` must be a non-negative `int`

## On a section

The `ISection` interface (`src/application/interfaces/i_section.py`) exposes
`overflow_strategies` (an `OverflowStrategyStack`). The base constructor accepts:

- `overflow_strategies` — the explicit stack for this section.
- `default_overflow_strategies` — the default stack used when no explicit stack
  is given (mirrors `default_importance` / `default_demand`).

When neither is provided, the section falls back to `OverflowStrategyStack()`,
i.e. `(TRUNCATE, IGNORE)` with no restart.

```python
from src.domain.enums import OverflowStrategy
from src.domain.overflow_strategy_stack import OverflowStrategyStack
from src.application.context import ChunksSection

stack = OverflowStrategyStack(
    [OverflowStrategy.SUMMARIZE, OverflowStrategy.TRUNCATE, OverflowStrategy.IGNORE],
    restart=False,
)
section = ChunksSection([], overflow_strategies=stack)
assert section.overflow_strategies.strategies[0] is OverflowStrategy.SUMMARIZE
```

## Architectural Boundary

An overflow strategy must preserve the separation between capacity allocation,
content fitting, and overflow handling:

```text
Context Manager
    │
    └── allocates capacity to Sections

Section-specific logic
    │
    └── decides how its content fits into that capacity

Overflow Strategy
    │
    └── defines what to do when the Section's content
        cannot fit into its available capacity
```

In particular, an overflow strategy must **not** make the Context Manager aware of
individual Chunks or other Section-specific items. The Context Manager deals only
with capacity; which items a list-based Section keeps, drops, or compresses is the
Section's own concern. See
[`dynamic_section_capacity_allocation.md`](../../dynamic_section_capacity_allocation.md)
for the full allocation model.

## Implementation status (for now)

The `TRUNCATE`, `SUMMARIZE`, and `IGNORE` semantics above are the contract that
future overflow handling and the Context Manager will implement and consume.
The model does **not** execute a strategy, run LLM compression, or perform
capacity allocation. The tokenizer abstraction (`ITokenizer`) exists as a port;
concrete tokenizer implementations, the strategy algorithms, and the allocation
logic are not implemented yet.

## Related documents

- [Section Properties: `importance` and `demand`](section_properties.md) — the two Section weights.
- [Section Mechanism](section_mechanism.md) — the `ISection` contract and how new sections are added.
- [Prompt-Builder Architecture](prompt_builder_entities.md) — `PromptBuilder`, canonical sections, and rendering.
- [Dynamic Section Capacity Allocation](../../dynamic_section_capacity_allocation.md) — the Context Manager's capacity-allocation model.
