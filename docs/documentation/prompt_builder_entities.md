# Prompt-Builder Architecture

This document describes the prompt-builder feature: a generic, extensible set of domain entities that model a prompt as ordered, renderable sections.

## Design Goals

- **Open/closed for real**: section identity is a plain string, not a closed enum. `Section.subclasses` own their identity, so new section types (`REGULATION`, `METADATA`, `INSTRUCTIONS`, ...) are added by subclassing — no central enum, no builder changes.
- **Name-keyed registry**: `PromptBuilder` addresses sections by canonical name (e.g. `REGULATION`), supports idempotent replacement, deterministic ordering, and unknown-name lookup.
- **Explicit structure**: every section is framed as `pre-context → body → post-context`.
- **Domain-agnostic**: the architecture does not know about suggestions, statutes, RAG, or any specific business domain; content is normalized into these building blocks first.
- **`HISTORY` is first-class**: conversation history is a distinct section type, separate from RAG `CHUNKS`.

## Location

The architecture is split across layers: the data entities (`Chunk`, `HistoryMessage`) live in the Domain layer alongside the other domain entities. The `Section` concept is **general-purpose**: it represents a logical part of a context (not necessarily a prompt) and lives in its own Application-layer package. `PromptBuilder` — the prompt-specific consumer — lives under `prompt_architecture/` and composes `Section` instances into an ordered prompt:

```
src/domain/entities.py          # Chunk, HistoryMessage (entities)
src/application/context/
├── __init__.py
├── section.py                  # Section (abstract base class)
└── sections/
    ├── __init__.py
    ├── role_section.py         # RoleSection
    ├── history_section.py      # HistorySection
    ├── chunks_section.py       # ChunksSection (RAG context)
    ├── system_input_section.py # SystemInputSection
    ├── system_output_section.py# SystemOutputSection
    ├── user_input_section.py   # UserInputSection
    ├── output_format_section.py# OutputFormatSection
    └── string_section.py       # StringSection (generic, name + raw string)
src/application/prompt_architecture/
├── __init__.py
└── prompt_builder.py           # PromptBuilder (name-keyed registry)
```

The Application layer depends inward on the Domain: sections consume `Chunk`/`HistoryMessage` and render them for the LLM. The packages stay pure stdlib. A future context/token-allocation component consumes the same `Section` concept (via its `importance` weight) without touching the prompt layer.

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

### `Section` (abstract base class, `src/application/context/section.py`)

Defines the **contract** and the **general rendering algorithm** for every section. It is a general-purpose logical section of a context, not a prompt-specific concept: `PromptBuilder` is just one consumer, and a future context/token-allocation component can use the same concept (especially the `importance` weight) without touching the prompt layer.

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
| `default_importance` | class attribute (`float`, default `0.5`) | Subclass-provided default importance, applied when no explicit value is given |
| `importance` | property (`float`) | Relative importance in `[0.0, 1.0]` used when allocating token capacity; validated per-section, never normalized, no sum-to-`1.0` rule |
| `pre_context` | property (default `""`) | Framing before the body |
| `post_context` | property (default `""`) | Framing after the body |
| `body()` | abstract method | Constructs the section's main content — behaves conceptually like a property |
| `render()` | method | Joins `pre_context` + `body()` + `post_context` into one string; returns `""` when the body is empty |

The base class holds **no** section-specific implementation; subclasses override `default_importance`, `section_type`, and `body()` (and framing where needed). There is **no central enum of section names** — a subclass's `section_type` is its identity. `importance` values of several sections are independent weights: the base class validates each value against `[0.0, 1.0]` but never normalizes them and never enforces a sum of `1.0`. Normalization and allocation are the responsibility of the context/token-allocation logic.

### Concrete sections

One concrete section per canonical section type, each owning its `default_importance` and `body()`:

- **`RoleSection`** (`src/application/context/sections/role_section.py`) — `ROLE`, default importance `0.5`. Assigns the model its role.
- **`HistorySection`** (`src/application/context/sections/history_section.py`) — `HISTORY`, default importance `0.3`. Renders `HistoryMessage` turns as the body (each as `role: content`), framed by `pre_context = "History of previous interactions:"`.
- **`ChunksSection`** (`src/application/context/sections/chunks_section.py`) — `CHUNKS`, default importance `0.4`. Renders RAG context as numbered `Chunk N:` blocks, framed by `pre_context = "Relevant context chunks:"`.
- **`SystemInputSection`** (`src/application/context/sections/system_input_section.py`) — `SYSTEM-INPUT`, default importance `0.5`. System-level input passed to the model.
- **`SystemOutputSection`** (`src/application/context/sections/system_output_section.py`) — `SYSTEM-OUTPUT`, default importance `0.5`. System-level output expected from the model.
- **`UserInputSection`** (`src/application/context/sections/user_input_section.py`) — `USER-INPUT`, default importance `0.5`. User-provided input passed to the model.
- **`OutputFormatSection`** (`src/application/context/sections/output_format_section.py`) — `OUTPUT-FORMAT`, default importance `0.1`. Describes the expected output format.
- **`StringSection`** (`src/application/context/sections/string_section.py`) — arbitrary `name` + raw string content, default importance `0.5`. The escape hatch used by `PromptBuilder.set_section(name, "text")` for custom text-only sections.

### Adding a custom section

A developer introduces a new section by subclassing — **no central enum or framework code changes required**:

```python
class RegulationSection(Section):

    @property
    def section_type(self) -> str:
        return "REGULATION"

    def body(self) -> str:
        return "Relevant regulations."
```

### `PromptBuilder` (`src/application/prompt_architecture/prompt_builder.py`)

A **name-keyed ordered registry** of `Section` instances. It ships the canonical sections and renders them in order:

| Member | Kind | Responsibility |
|---|---|---|
| `__init__(sections=None, *, seed_defaults=True)` | constructor | Seeds the canonical sections (empty) unless `seed_defaults=False`; merges any provided sections |
| `set_section(name, value)` | method | Register a section under `name`. `value` is a `Section` instance (its `section_type` must match `name`) or a raw string (wrapped in `StringSection`). New names append; existing names replace in place |
| `add_section(section)` | method | Append a section keyed by its own `section_type`; raises `ValueError` on a duplicate name |
| `get_section(name)` | method | Return the registered section or `None` |
| `has_section(name)` | method | Whether a section is registered |
| `set_role(content)` | method | Configure the `ROLE` default section |
| `set_history(messages)` | method | Configure the `HISTORY` default section |
| `set_chunks(chunks)` | method | Configure the `CHUNKS` default section |
| `set_system_input(content)` | method | Configure the `SYSTEM-INPUT` default section |
| `set_system_output(content)` | method | Configure the `SYSTEM-OUTPUT` default section |
| `set_output_format(content)` | method | Configure the `OUTPUT-FORMAT` default section |
| `sections` | property | Ordered list of composed sections |
| `render()` | method | Render all non-empty sections in order, joined by `\n\n` |

**Canonical section order** (defaults): `ROLE, HISTORY, CHUNKS, SYSTEM-INPUT, SYSTEM-OUTPUT, OUTPUT-FORMAT`. Names are normalized with `strip().upper()`, so `"regulation"`, `"REGULATION"`, and `" Regulation "` address the same slot. Setting an existing name replaces it **in place**; a new name appends after the defaults.

Custom sections coexist with the defaults:

```python
builder = PromptBuilder()
builder.set_role("You are a legal analyst.")
builder.set_section("REGULATION", RegulationSection())
builder.set_section("INSTRUCTIONS", "Be concise.")
```

## Rendering Logic

1. Each `Section.render()` joins its `pre_context`, `body()`, and `post_context` with `\n\n`, skipping empty parts. A section whose body is empty renders as `""`, so unconfigured default slots never leak framing or separators.
2. `PromptBuilder.render()` renders every registered section and joins the non-empty results with `\n\n`.
3. The final result is a single assembled prompt string (not a multi-turn conversation).