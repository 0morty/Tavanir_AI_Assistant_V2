# Section Mechanism

This document describes **how prompt/context sections are designed and registered**. It is the companion to [Prompt-Builder Architecture](prompt_builder_entities.md), which describes `PromptBuilder` itself; this document focuses on the design rules that govern sections.

## The core rule: every section is designed by a developer

> **A new section must be an explicit `PromptSection` subclass designed by the developer. There is no generic section and no raw-text escape hatch.**

Every logical part of a prompt is a dedicated, named, developer-owned class:

- each class owns its **identity** (`section_type`)
- each class owns its **content** (`body()`)
- each class supplies its **default importance** and **default demand** to the base constructor
- each class owns its **framing** (`pre_context` / `post_context`) when needed

This rule is what makes the architecture **open/closed**: you extend the prompt by adding a subclass, never by weakening the contract. A developer must *think* about what the section is for, give it a meaningful identity, and decide how it renders.

## Why there is no generic section

Earlier iterations shipped two convenience classes that violated this rule and were removed:

- `SystemOutputSection` — a plain-text section that did not belong to the table of contents; removing it left the writer's job to `OutputFormatSection`.
- `StringSection` — a catch-all that allowed registering any raw string under any name.

`StringSection` was the real anti-pattern: it let `set_section("INSTRUCTIONS", "Be concise.")` create a section without any dedicated class, so section types multiplied without design intent, and `section_type` stopped being reliable identity. With it gone:

- `PromptBuilder.set_section(name, value)` accepts **only** `IPromptSection` instances (in practice `PromptSection` subclasses).
- A non-`IPromptSection` value raises `TypeError` immediately.
- Every section in the prompt is traceable to a real `PromptSection` subclass.

## The prompt-section contract

The contract itself is declared on the pure port `IPromptSection` (`src/application/interfaces/i_prompt_section.py`); the `PromptSection` skeleton (`src/application/context/sections/prompt_section.py`) implements that port and ships the default behavior on top of the contract. Each section is an explicit `PromptSection` subclass, so it inherits both the contract (via the port) and the defaults (via the skeleton). A `PromptSection` subclass decides what the section is; `importance`, `demand`, and `overflow_strategies` are instance properties **owned by the base class**, not class-level contracts redeclared in each subclass. They are part of the *prompt-section* abstraction itself — every prompt section carries its capacity weights and overflow policy — not generic properties of every possible section:

| Member | Role |
|---|---|
| `section_type` (abstract property) | String identity, e.g. `"HISTORY"`, `"CHUNKS"`, `"REGULATION"`. Cannot be empty and is normalized to uppercase |
| `body()` (abstract method) | The section's main content |
| `importance` (base-owned property) | Intrinsic semantic importance in `[0.0, 1.0]`, used as a weight when redistributing unused token capacity. **Not** a token percentage |
| `demand` (base-owned property) | Relative context-capacity demand in `[0.0, 1.0]`, used to calculate the section's initial proportional token capacity |
| `overflow_strategies` (base-owned property) | The section's `OverflowStrategyStack`: ordered overflow strategies (lower index = higher priority) plus the restart policy. The base ships the **default interpretation** of the policy through the `CompressibleSection` operations; subclasses inherit them or override them |
| `truncate` / `summarize` / `ignore` (from `CompressibleSection`) | The section's overflow operations. `PromptSection` ships plain-text defaults (`truncate` applies the universal `TruncateStrategy`, `summarize` delegates to an injected `Summarizer`, `ignore` is not applicable to a single plain text). `ReferencedCollectionSection` overrides them for a collection: `truncate`/`summarize` apply the universal algorithms to the joined (reference-enriched) text, `IGNORE` keeps items in order while they fit |
| `render()` (base default) | Joins `pre_context`, `body()`, and `post_context` (skipping empty parts) into a single string |
| `default_importance` (base-constructor parameter, default `0.5`) | Default importance used when no explicit `importance` is passed; each subclass passes its own via `super().__init__(..., default_importance=...)` |
| `default_demand` (base-constructor parameter, default `0.5`) | Default demand used when no explicit `demand` is passed; each subclass passes its own via `super().__init__(..., default_demand=...)` |
| `default_overflow_strategies` (base-constructor parameter) | Default overflow stack used when no explicit `overflow_strategies` is passed; falls back to `OverflowStrategyStack()` (`(TRUNCATE, IGNORE)`, no restart) |
| `pre_context` / `post_context` (properties) | Optional framing around the body (default empty) |

Neither `importance` nor `demand` is a token percentage, neither needs to sum to `1.0` across sections, and `PromptSection` never normalizes them or allocates capacity itself.

On a **collection section** (`ReferencedCollectionSection`), the held collection is exposed as `items` and its entries are joined with `item_separator` — independent of the framing `separator` used by `render()`.

## Adding a new section

1. Create an `PromptSection` subclass in `src/application/context/sections/` (the port contract lives in `src/application/interfaces/i_prompt_section.py`; the `PromptSection` skeleton that implements it lives in `src/application/context/sections/prompt_section.py`).
2. Give it a stable `section_type` and a `body()`.
3. Choose a default importance and a default demand, each in `[0.0, 1.0]`, and pass them to the base constructor (both default to `0.5` when omitted). Configure `overflow_strategies` only when the section needs a non-default overflow stack.
4. Export it from `src/application/context/sections/__init__.py` (and `src/application/context/__init__.py` if it should be part of the public `context` API).
5. Register it on a builder with `set_section("...", MySection(...))` or `add_section(MySection(...))`.

Example — a regulation section designed for the job:

```python
from src.application.context.sections import PromptSection


class RegulationSection(PromptSection):

    def __init__(
        self,
        content: str,
        *,
        importance: float | None = None,
        demand: float | None = None,
    ) -> None:
        super().__init__(
            importance=importance,
            demand=demand,
            default_importance=0.4,
            default_demand=0.5,
        )
        self._content = content

    @property
    def section_type(self) -> str:
        return "REGULATION"

    def body(self) -> str:
        return self._content
```

Registered via the builder:

```python
builder.set_section("REGULATION", RegulationSection("Law 137 ..."))
```

## Registration constraints

- `set_section(name, value)` requires `isinstance(value, IPromptSection)`; otherwise it raises `TypeError`.
- `name` must match the section's `section_type` after normalization (`strip().upper()`); a mismatch raises `ValueError`.
- A blank name raises `ValueError`.
- `add_section(section)` appends a section keyed by its own `section_type` and rejects duplicates with `ValueError`.
- Both `importance` and `demand` are validated against `[0.0, 1.0]` per section; the base class never normalizes or sums them.

## Where custom sections come from

```text
                    IPromptSection (port)
                   contract only, no behavior
                             │
                             ▼
                    PromptSection (skeleton)
                 contract + default behavior
                             │
           ┌─────────────────┼──────────────────────┐
           │                 │                      │
   Canonical (default)   Developer-designed    -- no generic --
   Role / History /      RegulationSection        StringSection
   Chunks / SystemInput  InstructionsSection           ✗
   / UserInput /         MetadataSection
   OutputFormat
```

Custom sections live in the same package as the canonicals and are plain subclasses. Adding one never touches `PromptBuilder`, a central enum, or any framework code.

## Related documents

- [Section Properties: `importance` and `demand`](section_properties.md) — definitions of the two Section weights.
- [Overflow Strategies: `OverflowStrategy` and `OverflowStrategyStack`](overflow_strategies.md) — the section overflow-strategy data model.
- [Prompt-Builder Architecture](prompt_builder_entities.md) — the `PromptBuilder` registry, canonical sections, and rendering logic.