# Prompt-Builder Architecture

This document describes the prompt-builder feature: a generic, extensible set of domain entities that model a prompt as ordered, renderable sections.

## Design Goals

- **Open/closed for real**: section identity is a plain string, not a closed enum. `PromptSection` subclasses own their identity, so new section types (`REGULATION`, `METADATA`, `INSTRUCTIONS`, ...) are added by subclassing — no central enum, no builder changes.
- **Name-keyed registry**: `PromptBuilder` addresses sections by canonical name (e.g. `REGULATION`), supports idempotent replacement, deterministic ordering, and unknown-name lookup.
- **Explicit structure**: every section is framed as `pre-context → body → post-context`.
- **Domain-agnostic**: the architecture does not know about suggestions, statutes, RAG, or any specific business domain; content is normalized into these building blocks first.
- **`HISTORY` is first-class**: conversation history is a distinct section type, separate from RAG `CHUNKS`.

## Location

The architecture is split across layers: the data entities (`Chunk`, `HistoryMessage`) live in the Domain layer alongside the other domain entities. The `PromptSection` concept is **prompt-scoped**: it represents a logical part of a prompt (not a generic section of anything else). Its abstract base class lives in `src/application/context/sections/`, alongside the developer-designed sections that implement it. `PromptBuilder` — the prompt consumer — lives under `prompt/` and composes `IPromptSection` instances into an ordered prompt:

```
src/domain/entities.py                  # Chunk, HistoryMessage (entities)
src/domain/enums.py                     # HistoryRole, OverflowStrategy (enums)
src/domain/overflow_strategy_stack.py   # OverflowStrategyStack (config value object)

src/application/interfaces/
├── __init__.py
├── i_prompt_section.py     # IPromptSection (pure interface / port, contract only)
└── ... (other pure ports: IDenseEmbedder, IReferenceGenerator, ISparseEmbedder, ITokenizer, ...)

src/application/context/
├── __init__.py
└── sections/
    ├── __init__.py
    ├── prompt_section.py      # PromptSection (skeleton: IPromptSection + default behavior)
    ├── role_section.py         # RoleSection
    ├── history_section.py      # HistorySection
    ├── chunks_section.py       # ChunksSection (RAG context)
    ├── system_input_section.py # SystemInputSection
    ├── user_input_section.py   # UserInputSection
    └── output_format_section.py# OutputFormatSection

src/application/prompt/
├── __init__.py
└── prompt_builder.py           # PromptBuilder (name-keyed registry)
```

The Application layer depends inward on the Domain: sections consume `Chunk`/`HistoryMessage` and render them for the LLM, and the `PromptSection` contract is typed against domain config (`OverflowStrategyStack`). The packages stay pure stdlib. A future context/token-allocation component consumes the same concept (via its `importance`, `demand`, and `overflow_strategies` values) without touching the prompt layer.

## Entities

### `Chunk` (domain-agnostic content unit, `src/domain/entities.py`)

A `Suggestion`, `StatuteDocument`, or any future document type is mapped into a `Chunk` before prompt assembly.

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Unique identifier |
| `title` | `str` | Display title |
| `content` | `str` | The text content |
| `metadata` | `dict[str, Any]` | Optional source-specific data (status, similarity, citation, ...) |

### `HistoryMessage` (a conversation turn, `src/domain/entities.py`)

Models one entry in conversation history, carrying the sender role and the message text.

| Field | Type | Description |
|---|---|---|
| `role` | `HistoryRole` | Sender role — OpenAI-compatible (`USER` → `"user"`, `SYSTEM` → `"system"`) |
| `content` | `str` | The message text |

### `HistoryRole` (enum, `src/domain/enums.py`)

Sender-role vocabulary for history messages, stored alongside the OpenAI role string as its value:

- `HistoryRole.USER` → `"user"`
- `HistoryRole.SYSTEM` → `"system"`
- `HistoryRole.ASSISTANT` → `"assistant"`

### Overflow strategy models (`src/domain/enums.py`, `src/domain/overflow_strategy_stack.py`)

`OverflowStrategy` (`TRUNCATE`, `SUMMARIZE`, `IGNORE`) and its companion value object `OverflowStrategyStack` (ordered, prioritized strategy list plus a restart policy) model how a section's content is handled when it exceeds its context capacity. The port exposes the stack via `IPromptSection.overflow_strategies` (implemented by `PromptSection`). See [Overflow Strategies](overflow_strategies.md) for the full data-model definition.

The prompt-section abstraction is split into two tiers: the pure port `IPromptSection` (`src/application/interfaces/i_prompt_section.py`) declares the contract only -- no state, no behavior. The `PromptSection` skeleton (`src/application/context/sections/prompt_section.py`) implements that port and ships the default behavior on top of it. New sections subclass the skeleton to inherit the defaults; consumer code (e.g. `PromptBuilder`) can depend on the port alone.

### `IPromptSection` (port, `src/application/interfaces/i_prompt_section.py`)

Declares the prompt-section contract: `section_type`, `importance`, `demand`, `overflow_strategies`, `pre_context`/`post_context`, `body()`, `fit_to_capacity()`, and `render()`. Every section must satisfy this contract; the port itself carries no implementation.

### `PromptSection` (skeleton, `src/application/context/sections/prompt_section.py`)

Implements `IPromptSection` and ships the **general rendering algorithm** plus the **default interpretation** of the overflow policy. It is the prompt-section abstraction, not a generic section of anything else: a section participates in prompt construction, so its `importance`, `demand`, and `overflow_strategies` are part of what a prompt section *is*. `PromptBuilder` is one consumer; a future context/token-allocation component operates on the same abstraction (via those values) without touching the prompt layer.

```
+--------------+
| pre-context  |
+--------------+
|     body     |
+--------------+
| post-context |
+--------------+
```

| Member | Kind | Responsibility |
|---|---|---|
| `separator` | attribute (via `__init__`, default `"\n\n"`) | Delimiter used when joining the section parts |
| `section_type` | abstract property (`str`) | **String-based** identity/name of the section, e.g. `"HISTORY"`, `"CHUNKS"`, or a custom `"REGULATION"` |
| `default_importance` | constructor parameter (`float`, default `0.5`) | Default importance applied by the base class when no explicit `importance` is given; each subclass passes its own via `super().__init__(..., default_importance=...)` |
| `default_demand` | constructor parameter (`float`, default `0.5`) | Default demand applied by the base class when no explicit `demand` is given; each subclass passes its own via `super().__init__(..., default_demand=...)` |
| `default_overflow_strategies` | constructor parameter (`OverflowStrategyStack | None`) | Default overflow stack applied when no explicit `overflow_strategies` is given; falls back to `OverflowStrategyStack()` (`(TRUNCATE, IGNORE)`, no restart) |
| `importance` | property (`float`) | Intrinsic semantic importance in `[0.0, 1.0]`, used as a weight when redistributing unused token capacity. **Not** a token percentage; validated per-section, never normalized, no sum-to-`1.0` rule |
| `demand` | property (`float`) | Relative context-capacity demand in `[0.0, 1.0]`, used to calculate the section's initial proportional token capacity. Validated per-section, never normalized, no sum-to-`1.0` rule |
| `overflow_strategies` | property (`OverflowStrategyStack`) | Ordered overflow strategies (lower index = higher priority) plus the restart policy; the base ships the default execution via `fit_to_capacity` |
| `fit_to_capacity(content, capacity_tokens, *, tokenizer, summarizer=None)` | default method | **Default overflow execution**: fits a single plain-text value by walking the strategy stack in priority order (honouring the restart policy) and returning the first result that fits; subclasses inherit it or override it |
| `pre_context` | property (default `""`) | Framing before the body |
| `post_context` | property (default `""`) | Framing after the body |
| `body()` | abstract method | Constructs the section's main content — behaves conceptually like a property |
| `render()` | method | Joins `pre_context` + `body()` + `post_context` into one string; returns `""` when the body is empty |

The base class holds **no** domain/business-specific implementation; it ships the generic default behavior of a prompt section — framing (`pre_context`/`post_context`/`separator`/`render()`), capacity weights (`importance`/`demand`), the overflow policy (`overflow_strategies`) and its default execution (`fit_to_capacity`). Subclasses override `section_type` and `body()` (and any hook they vary) and pass their default `importance`, `demand`, and overflow strategies to the base constructor. There is **no central enum of section names** — a subclass's `section_type` is its identity. `importance` and `demand` are instance properties owned by the base class; their values for several sections are independent and never normalized: the base class validates each value against `[0.0, 1.0]` but never enforces a sum of `1.0`. Normalization and allocation are the responsibility of the context/token-allocation logic.

**Collection sections** (`ReferencedCollectionSection` subclasses) expose their held collection as `items` and join entries with `item_separator` — independent of the framing `separator` used by `render()`.

### Concrete sections

One concrete section per canonical section type, each owning its `body()`, default importance, and default demand:

- **`RoleSection`** (`src/application/context/sections/role_section.py`) — `ROLE`, default importance `0.5`, default demand `0.3`. Assigns the model its role.
- **`HistorySection`** (`src/application/context/sections/history_section.py`) — `HISTORY`, default importance `0.3`, default demand `0.4`. Renders `HistoryMessage` turns as the body (each as `role: content`), framed by `pre_context = "History of previous interactions:"`.
- **`ChunksSection`** (`src/application/context/sections/chunks_section.py`) — `CHUNKS`, default importance `0.4`, default demand `0.5`. Renders RAG context as numbered `Chunk N:` blocks, framed by `pre_context = "Relevant context chunks:"`.
- **`SystemInputSection`** (`src/application/context/sections/system_input_section.py`) — `SYSTEM-INPUT`, default importance `0.5`, default demand `0.5`. System-level input passed to the model.
- **`UserInputSection`** (`src/application/context/sections/user_input_section.py`) — `USER-INPUT`, default importance `0.5`, default demand `0.4`. User-provided input passed to the model.
- **`OutputFormatSection`** (`src/application/context/sections/output_format_section.py`) — `OUTPUT-FORMAT`, default importance `0.1`, default demand `0.2`. Describes the expected output format.

### Adding a custom section

Every section is **designed by a developer**. There is no generic "string" section and no raw-text escape hatch: a new section must be an explicit `PromptSection` subclass that owns its identity (`section_type`), content (`body()`), default importance, and default demand. Adding one requires **no central enum or framework code changes**:

```python
class RegulationSection(PromptSection):

    @property
    def section_type(self) -> str:
        return "REGULATION"

    def body(self) -> str:
        return "Relevant regulations."
```

See [Section Mechanism](section_mechanism.md) for the full design rules.

### `PromptBuilder` (`src/application/prompt/prompt_builder.py`)

A **name-keyed ordered registry** of `PromptSection` instances. It ships the canonical sections and renders them in order:

| Member | Kind | Responsibility |
|---|---|---|
| `__init__(sections=None, *, seed_defaults=True)` | constructor | Seeds the canonical sections (empty) unless `seed_defaults=False`; merges any provided sections |
| `set_section(name, value)` | method | Register a section under `name`. `value` must be an `IPromptSection` instance whose `section_type` matches `name` (anything else raises `TypeError`). New names append; existing names replace in place |
| `add_section(section)` | method | Append a section keyed by its own `section_type`; raises `ValueError` on a duplicate name |
| `get_section(name)` | method | Return the registered section or `None` |
| `has_section(name)` | method | Whether a section is registered |
| `set_role(content)` | method | Configure the `ROLE` default section |
| `set_history(messages)` | method | Configure the `HISTORY` default section |
| `set_chunks(chunks)` | method | Configure the `CHUNKS` default section |
| `set_system_input(content)` | method | Configure the `SYSTEM-INPUT` default section |
| `set_user_input(content)` | method | Configure the `USER-INPUT` default section |
| `set_output_format(content)` | method | Configure the `OUTPUT-FORMAT` default section |
| `sections` | property | Ordered list of composed sections |
| `render()` | method | Render all non-empty sections in order, joined by `\n\n` |

**Canonical section order** (defaults): `ROLE, HISTORY, CHUNKS, SYSTEM-INPUT, USER-INPUT, OUTPUT-FORMAT`. Names are normalized with `strip().upper()`, so `"regulation"`, `"REGULATION"`, and `" Regulation "` address the same slot. Setting an existing name replaces it **in place**; a new name appends after the defaults.

Custom sections (developer-designed `PromptSection` subclasses) coexist with the defaults:

```python
builder = PromptBuilder()
builder.set_role("You are a legal analyst.")
builder.set_section("REGULATION", RegulationSection())
builder.set_section("INSTRUCTIONS", InstructionsSection("Be concise."))
```

## Rendering Logic

1. Each `PromptSection.render()` joins its `pre_context`, `body()`, and `post_context` with `\n\n`, skipping empty parts. A section whose body is empty renders as `""`, so unconfigured default slots never leak framing or separators.
2. `PromptBuilder.render()` renders every registered section and joins the non-empty results with `\n\n`.
3. The final result is a single assembled prompt string (not a multi-turn conversation).