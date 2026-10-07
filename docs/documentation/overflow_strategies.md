# Overflow Strategies: `OverflowStrategy` and `OverflowStrategyStack`

This document defines the overflow policy and its implemented behavior when a section
cannot fit within its allocated token capacity. `ContextBuilder` prepares and sizes
sections, `OverflowStrategyDispatcher` invokes the matching section operation, and
the section decides how its content is reduced. The strategy names alone do not
guarantee that an operation applies to every section type.

## Vocabulary

`OverflowStrategy` (enum, `src/domain/enums.py`) is the strategy vocabulary:

| Member | Value | Intended meaning |
|---|---|---|
| `TRUNCATE` | `"truncate"` | Retain a fitting text prefix on single-text sections; collection sections leave whole items intact |
| `SUMMARIZE` | `"summarize"` | Use an injected summarizer to compress single text or prepared collection items |
| `IGNORE` | `"ignore"` | Exclude individual items (in list-based Sections) that cannot fit within the available capacity |

See [Strategy Semantics](#strategy-semantics) below for the precise meaning of
each strategy.

## Strategy Semantics

An overflow strategy defines **what a Section does when its content cannot fit
into its available capacity**. Strategies operate on a Section's own content;
they do **not** allocate capacity. Capacity allocation is owned by the Context
Manager (see [Architectural Boundary](#architectural-boundary)).

### `TRUNCATE`

For a single-text `PromptSection`, `TRUNCATE` reduces its prepared text to a
fitting **prefix**. A `ReferencedCollectionSection` overrides `truncate()` as a
no-op so it never cuts through an item or citation marker; its capacity fallback
uses `IGNORE` to remove trailing whole items.

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
- Token accounting goes through the injected domain `Tokenizer` abstraction
  (`src/domain/context/tokenizer.py`); characters are **not** assumed to
  correspond to tokens.
- On single text, `TRUNCATE` **loses information** after the truncation boundary.
  On a collection, it returns the unchanged prepared result and cannot by
  itself make an oversized collection fit.

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

- Compression uses an injected `Summarizer` or `ITextSummarizer`. The
  Generation container registers LLM-backed summarizers, but a section
  must receive one explicitly. If neither is present, the section returns
  `None` and the next strategy is tried.
- The objective is to reduce **token usage**.
- The compressed representation should preserve the meaning and information
  relevant to the **Section's purpose**.
- Unlike single-text `TRUNCATE`, compression does **not** simply retain a prefix.
- A referenced collection summarizes prepared items independently, then
  reattaches the original citation IDs to the corresponding processed items.
  `ContextBuilder` accepts the result only if its rendered text fits the
  allocated capacity.
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
- The **Context Manager/Allocator** (`ContextBuilder` orchestrated by
  `CapacityAllocator`) is responsible for capacity allocation;
  `IGNORE` does **not** perform global capacity allocation.

### Strategy Semantics Summary

```text
TRUNCATE   → single text: fitting prefix; collection: unchanged
SUMMARIZE  → injected compression of text or individual collection items
IGNORE     → fitting prefix of whole collection items
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
priority, falling back to `TRUNCATE`, then `IGNORE`. Individual section classes
may select a narrower stack; `SimilarSuggestionsSection` uses `IGNORE` only,
and the current `SuggestionPromptPreparer` does not inject a summarizer there.

Validation:

- at least one strategy is required
- every entry must be an `OverflowStrategy` member
- `restart` must be a real `bool`
- `max_restarts` must be a non-negative `int`

## On a section

The port `IPromptSection` (`src/application/interfaces/i_prompt_section.py`) declares
`overflow_strategies` (an `OverflowStrategyStack`); the `PromptSection` skeleton
(`src/application/context/sections/prompt_section.py`) implements it. The base constructor accepts:

- `overflow_strategies` — the explicit stack for this section.
- `default_overflow_strategies` — the default stack used when no explicit stack
  is given (mirrors `default_importance` / `default_demand`).

When neither is provided, the section falls back to `OverflowStrategyStack()`,
i.e. `(TRUNCATE, IGNORE)` with no restart.

`PromptSection` implements the `CompressibleSection` capability
(`src/application/interfaces/i_compressible_section.py`): its single-text
`truncate()` applies `TruncateStrategy`, `summarize()` uses an injected
`Summarizer`, and `ignore()` returns `None`. `ReferencedCollectionSection`
overrides the operations: `truncate()` is a no-op, `summarize()` processes
prepared items separately and preserves aligned citation IDs, and `ignore()`
keeps the longest fitting prefix of whole items.

The **runtime dispatch** of an `OverflowStrategy` to the matching operation is
owned by the external `OverflowStrategyDispatcher`
(`src/application/context/overflow_strategy_dispatcher.py`): it maps
`SUMMARIZE`→`section.summarize(...)`, `TRUNCATE`→`section.truncate(...)`,
`IGNORE`→`section.ignore(...)` and invokes the operation, but never implements
it. `ContextBuilder` walks the strategy stack in priority order (honouring the
configured restart count) and accepts the first result whose rendered token
count fits the section capacity. If none fits, it makes one final safety-net
call: `IGNORE` for collections and `TRUNCATE` for single text. It raises
`ValueError` if that result still does not fit.

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
Context Manager (`ContextBuilder` + `CapacityAllocator`)
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
[Token budget and overflow](llm_generation_api.md#5-token-budget-and-overflow)
for the implemented allocation and fitting pipeline.

## Implementation status (for now)

The `TRUNCATE`, `SUMMARIZE`, and `IGNORE` operations are available to the
context pipeline when a section's configured stack and collaborators enable
them:

- Single-text truncation and summarization use `TruncateStrategy` and
  `SummarizeStrategy` from `src/domain/context/overflow/` through section
  operations. Collection `IGNORE` is implemented by
  `ReferencedCollectionSection.ignore()`; the separate domain `IgnoreStrategy`
  class remains an unimplemented placeholder and is not used by this pipeline.
- Runtime dispatch from `OverflowStrategy` to the matching Section operation is
  owned by `OverflowStrategyDispatcher`
  (`src/application/context/overflow_strategy_dispatcher.py`); `ContextBuilder`
  walks each Section's `OverflowStrategyStack` through it.
- The tokenizer port is the domain `Tokenizer` (`src/domain/context/tokenizer.py`);
  `SUMMARIZE` additionally requires an injected `Summarizer` or
  `ITextSummarizer` (otherwise it is skipped as unavailable).
- Capacity allocation ([Token budget and overflow](llm_generation_api.md#5-token-budget-and-overflow))
  is orchestrated by `ContextBuilder` (`src/application/context/context_builder.py`).
  It applies overflow handling when a prepared section exceeds its allocated
  capacity. The final safety net truncates single text or drops collection
  items; each accepted section result is checked against its section capacity.

## Related documents

- [Section Properties: `importance` and `demand`](section_properties.md) — the two Section weights.
- [Section Mechanism](section_mechanism.md) — the `IPromptSection` port, the `PromptSection` skeleton, and how new sections are added.
- [Prompt-Builder Architecture](prompt_builder_entities.md) — `PromptBuilder`, canonical sections, and rendering.
- [Token budget and overflow](llm_generation_api.md#5-token-budget-and-overflow) — the implemented context-capacity pipeline.
