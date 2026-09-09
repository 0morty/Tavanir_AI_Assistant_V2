# Prompt-Builder Architecture

This document describes the prompt-builder feature: a generic, extensible set of domain entities that model a prompt as ordered, renderable sections.

## Design Goals

- **Open/closed**: `PromptBuilder` composes and renders `PromptSection` instances without knowing each section's internals. New section types are added by subclassing — no builder changes required.
- **Explicit structure**: every section is framed as `pre-context → body → post-context`.
- **Domain-agnostic**: the architecture does not know about suggestions, statutes, RAG, or any specific business domain; content is normalized into these building blocks first.
- **`HISTORY` is first-class**: conversation history is a distinct section type, separate from RAG `CHUNKS`.

## Location

The architecture is split across layers: the data entities (`Chunk`, `HistoryMessage`) live in the Domain layer alongside the other domain entities, while the section contracts, concrete sections, and the builder live in the Application layer:

```
src/domain/entities.py          # Chunk, HistoryMessage (entities)
src/application/prompt_architecture/
├── __init__.py
├── section_type.py             # PromptSectionType (enum)
├── prompt_section.py           # PromptSection (abstract base class)
├── role_section.py             # RoleSection
├── history_section.py          # HistorySection
├── chunks_section.py           # ChunksSection (RAG context)
├── system_input_section.py     # SystemInputSection
├── user_input_section.py       # UserInputSection
├── output_format_section.py    # OutputFormatSection
└── prompt_builder.py           # PromptBuilder
```

The Application layer depends inward on the Domain: prompt sections consume `Chunk`/`HistoryMessage` and render them for the LLM. The package stays pure stdlib.

## Entities

### `PromptSectionType` (enum, `src/application/prompt_architecture/section_type.py`)

First-class section labels, in natural prompt order:

- `ROLE`
- `HISTORY`
- `CHUNKS`
- `SYSTEM_INPUT`
- `USER_INPUT`
- `OUTPUT_FORMAT`

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

### `PromptSection` (abstract base class, `src/application/prompt_architecture/prompt_section.py`)

Defines the **contract** and the **general rendering algorithm** for every section:

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
| `section_type` | abstract property | First-class identity of the section |
| `pre_context` | property (default `""`) | Framing before the body |
| `post_context` | property (default `""`) | Framing after the body |
| `body()` | abstract method | Constructs the section's main content — behaves conceptually like a property |
| `render()` | method | Joins `pre_context` + `body()` + `post_context` into one string |

The base class holds **no** section-specific implementation; subclasses override `body()` (and framing where needed).

### Concrete sections

One concrete section per first-class section type, each owning its `body()`:

- **`RoleSection`** (`src/application/prompt_architecture/role_section.py`) — `ROLE`. Assigns the model its role.
- **`HistorySection`** (`src/application/prompt_architecture/history_section.py`) — `HISTORY`. Renders `HistoryMessage` turns as the body (each as `role: content`), framed by `pre_context = "History of previous interactions:"`.
- **`ChunksSection`** (`src/application/prompt_architecture/chunks_section.py`) — `CHUNKS`. Renders RAG context as numbered `Chunk N:` blocks, framed by `pre_context = "Relevant context chunks:"`.
- **`SystemInputSection`** (`src/application/prompt_architecture/system_input_section.py`) — `SYSTEM_INPUT`. System-level input passed to the model.
- **`UserInputSection`** (`src/application/prompt_architecture/user_input_section.py`) — `USER_INPUT`. User-provided input passed to the model.
- **`OutputFormatSection`** (`src/application/prompt_architecture/output_format_section.py`) — `OUTPUT_FORMAT`. Describes the expected output format.

### `PromptBuilder` (`src/application/prompt_architecture/prompt_builder.py`)

Composes `PromptSection` instances in order and renders the full prompt:

| Member | Kind | Responsibility |
|---|---|---|
| `sections` | property | Ordered list of composed sections |
| `add_section()` | method | Append a section |
| `render()` | method | Render all sections in order, joined by `\n\n` |

## Rendering Logic

1. Each `PromptSection.render()` joins its `pre_context`, `body()`, and `post_context` with `\n\n`, skipping empty parts.
2. `PromptBuilder.render()` renders every composed section and joins the results with `\n\n`.
3. The final result is a single assembled prompt string (not a multi-turn conversation).