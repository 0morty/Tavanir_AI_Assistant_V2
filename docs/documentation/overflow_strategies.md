# Overflow Strategies: `OverflowStrategy` and `OverflowStrategyStack`

This document defines the **data model** for what happens when a section's
content exceeds its context capacity. It deliberately only describes
configuration/state — strategy **execution, fallback, success/failure detection,
retry, and restart algorithms are out of scope** and are not implemented.

## Vocabulary

`OverflowStrategy` (enum, `src/domain/enums.py`) is the strategy vocabulary:

| Member | Value | Intended meaning |
|---|---|---|
| `TRUNCATE` | `"truncate"` | Cut the section's content down to fit its allocation |
| `SUMMARIZE` | `"summarize"` | Replace the content with a summary |
| `IGNORE` | `"ignore"` | Drop the section from the context |

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

## Out of scope (for now)

The model does **not** execute a strategy, detect success/failure, allocate
tokens, or run retry/restart loops. Future overflow handling will consume this
configuration.

## Related documents

- [Section Properties: `importance` and `demand`](section_properties.md) — the two Section weights.
- [Section Mechanism](section_mechanism.md) — the `ISection` contract and how new sections are added.
- [Prompt-Builder Architecture](prompt_builder_entities.md) — `PromptBuilder`, canonical sections, and rendering.