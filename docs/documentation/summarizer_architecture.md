# Summarizer Architecture

This document explains **how summarization works** in the Generation API — from
the application-layer port a Section injects, through the two concrete
LLM-backed adapters, down to prompt assembly, token budgeting, batching, and
strong output-mapping guarantees.

Summarization is one of the three **overflow strategies** (`SUMMARIZE`) that a
prompt Section applies when its rendered content exceeds its allocated token
budget. Read [Overflow Strategies](overflow_strategies.md) first for the
strategy *vocabulary*; this document describes the summarizer **implementation**
in depth.

## 1. What "the summarizer" is

There is **one abstraction** — the aggregate port `ITextSummarizer`
(`src/application/interfaces/i_text_summarizer.py`) — and **two concrete
adapters**, each producing summaries through an injected LLM:

| Adapter | File | Primary capability |
|---|---|---|
| `LLMSummarizer` | `src/infrastructure/services/summarizers/llm_summarizer.py` | Compress a **single text** into one summary |
| `LLMChunkSummarizer` | `src/infrastructure/services/summarizers/llm_chunk_summarizer.py` | Compress a **collection of chunks** into exactly one summary per chunk (batched) |

Both implement the same port, so a Section never knows which summarizer is
behind the seam. The port covers both summarization flavors the prompt Sections
consume:

```text
ITextSummarizer (src/application/interfaces/i_text_summarizer.py)
│
├── summarize(text, *, max_tokens=None) -> str
│       single-text compression (used by ReferencedSection)
│
└── summarize_chunks(chunks, *, capacity_tokens) -> list[str]
        per-chunk 1:1 compression (used by collection Sections)
```

A concrete adapter **must** implement both methods. Doing so is meaningful for
each adapter (see below), because a summarizer is equally valid for both modes:

- `LLMSummarizer.summarize_chunks(...)` answers with one `ILLMClient` call per
  chunk, so the mapping is 1:1 **by construction** (no batching).
- `LLMChunkSummarizer.summarize(...)` routes a single text through the **batched
  path as a batch of one**, reusing the exact same strict validation.

## 2. Design goals and invariants

Summarization exists to reduce a Section's **token footprint** while preserving
the meaning relevant to the prompt. The design adds a set of hard guarantees on
top of that:

1. **Strict 1:1 mapping** — for chunk summarization, every input chunk yields
   exactly one summary, in the same order. No chunk is lost, **merged,
   reordered, or omitted**.
2. **Batching under a budget** — as many chunks as possible share a single LLM
   call, so latency is reduced without ever letting one call's prompt exceed its
   token capacity.
3. **Progress is guaranteed** — even when a single chunk alone would overflow
   the capacity, the batch still takes that chunk, so a large chunk can never
   produce an infinite loop. The outer `ContextBuilder` truncation safety net
   absorbs the excess.
4. **No silent data loss** — if the model output cannot be mapped strictly 1:1
   after retries, the summarizer **raises** instead of returning a corrupted,
   partially-mapped result.
5. **Composition over assembly** — all collaborators (LLM client, tokenizer,
   prompt builder) are injected; the summarizer never constructs its own
   dependencies.
6. **Same prompt architecture** — summarization prompts are built with the same
   `PromptBuilder`/`PromptSection` machinery as the rest of the Generation API.

## 3. The port: `ITextSummarizer`

```python
class ITextSummarizer(ABC):
    @abstractmethod
    def summarize(self, text: str, *, max_tokens: int | None = None) -> str: ...

    @abstractmethod
    def summarize_chunks(
        self, chunks: list[str], *, capacity_tokens: int
    ) -> list[str]: ...
```

- `max_tokens` on `summarize` is the target upper bound for the summary, when
  known. It is surfaced to the model as an `OUTPUT-FORMAT` instruction (see
  §5) and independently enforced by the `ContextBuilder` truncation safety net.
- `capacity_tokens` on `summarize_chunks` bounds the token budget of **one
  batched LLM call**. The adapter decides how many chunks fit; it never exceeds
  the budget except by the documented single-chunk progress rule.
- `summarize_chunks` raises when the 1:1 mapping cannot be established after the
  adapter's retries (`ChunkSummarizationError`).

The port lives in the Application layer and references only the LLM-boundary
abstractions (`ILLMClient`, `Tokenizer`) under `TYPE_CHECKING`-free, required
constructor injection. It never mentions a concrete provider.

## 4. High-level flow

### 4.1 Single-text summarization (`LLMSummarizer.summarize`)

```text
           text, max_tokens?
                │
                ▼
┌───────────────────────────────────────────────┐
│ LLMSummarizer.summarize                       │
│  1. empty input?          ──►  return ""      │
│  2. build prompt with PromptBuilder:          │
│        ROLE                                    │
│        SYSTEM-INPUT                            │
│        USER-INPUT  = text                      │
│        OUTPUT-FORMAT = budget(if given) + fmt  │
│  3. render()  (single assembled string)        │
│  4. ILLMClient.complete(prompt)                │
│  5. strip()  ──►  summary                      │
└───────────────────────────────────────────────┘
                │
                ▼
             summary
```

### 4.2 Batched chunk summarization (`LLMChunkSummarizer.summarize_chunks`)

```text
        chunks, capacity_tokens
                │
                ▼
┌──────────────────────────────────────────────────────────┐
│ while remaining chunks exist:                            │
│                                                          │
│  STEP 1  choose batch = greedy prefix of remaining       │
│          chunks whose prompt fits capacity_tokens        │
│          (min 1 chunk — progress guarantee)              │
│  STEP 2  build one prompt:                               │
│            ROLE                                          │
│            SYSTEM-INPUT                                  │
│            CHUNKS    (joined with "---")                 │
│            OUTPUT-FORMAT                                 │
│  STEP 3  call ILLMClient.complete(prompt) once           │
│  STEP 4  split response on "---"                         │
│  STEP 5  validate:  #parts == #chunks  AND  no empty     │
│            │ yes ──► accept                              │
│            │ no  ──► retry (≤ max_attempts)              │
│            │        exhausted ──► raise                  │
│                     ChunkSummarizationError              │
│  STEP 6  append accepted summaries (order preserved)     │
│  STEP 7  remove batch from remaining                     │
│  STEP 8  continue until remaining is empty               │
└──────────────────────────────────────────────────────────┘
                │
                ▼
   exactly one summary per chunk, in order
```

## 5. `LLMSummarizer` — single-text compression

### 5.1 Construction

```python
LLMSummarizer(llm_client: ILLMClient, *, prompts: SummarizationPrompts | None = None)
```

- `llm_client` is **required** and typed against `ILLMClient`
  (`src/application/interfaces/i_llm_client.py`). It is never instantiated here.
- `prompts` is free-form configuration (a frozen dataclass), overridable so
  tests and operators can tune wording without touching logic.

### 5.2 The prompt

Built with the shared `PromptBuilder` (`src/application/prompt/prompt_builder.py`, a
name-keyed ordered registry of `PromptSection`s). The summarizer seeds no
defaults (`seed_defaults=False`) and registers exactly four slots in order:

| Slot | Content |
|---|---|
| `ROLE` | `SummarizationPrompts.role` |
| `SYSTEM-INPUT` | `SummarizationPrompts.system_input` |
| `USER-INPUT` | the text to summarize |
| `OUTPUT-FORMAT` | `max_tokens_instruction.format(max_tokens=...)` **+** `output_format` when a budget is given, else `output_format` alone |

Default prompt texts (Persian, matching the project convention):

- **role**: *"تو یک متخصص خلاصه‌سازی متن هستی که فقط بر اساس متنی که به او داده
  می‌شود، خلاصه‌ای فشرده و وفادار به متن تولید می‌کند."*
- **system_input**: *"متن زیر را خلاصه کن. معنای اصلی، اعداد، نام‌ها و ارجاع‌ها
  باید حفظ شوند. زبان خروجی باید همان زبان متن ورودی باشد."*
- **output_format**: *"فقط متن خلاصه را برگردان؛ بدون مقدمه، توضیح اضافه، یا
  قالب‌بندی. خلاصه نباید از ظرفیت توکن تعیین‌شده تجاوز کند."*
- **max_tokens_instruction**: *"خلاصه باید در حداکثر {max_tokens} توکن تهیه شود."*

The budget instruction is surfaced as an `OUTPUT-FORMAT` hint; the *actual*
enforcement is the `ContextBuilder` truncation safety net, which fits any
overflowing summary to the exact capacity regardless of what the model returns.

### 5.3 `summarize_chunks` on `LLMSummarizer`

```python
def summarize_chunks(self, chunks, *, capacity_tokens):
    return [self.summarize(chunk, max_tokens=capacity_tokens) for chunk in chunks]
```

Each chunk is compressed through the single-text path with the capacity as its
budget. The 1:1 mapping is therefore **guaranteed by construction** — one call
per chunk, results appended in input order. This flavor deliberately does **not**
batch (use `LLMChunkSummarizer` for shared-call batching).

## 6. `ChunkPromptBuilder` — the dedicated chunk prompt builder

`src/infrastructure/services/summarizers/chunk_prompt_builder.py` owns the
**chunk-summarization prompt format** and its **parsing**, keeping the
summarizer logic free of prose.

### 6.1 Fixed structure

```text
Role → System Input → Chunks → Output Format
```

The chunks slot is the **`USER-INPUT`** slot of the shared `PromptBuilder`
(rendered after `SYSTEM-INPUT`, before `OUTPUT-FORMAT`), so the final order
matches the required `Role → System Input → Chunks → Output Format` structure.

### 6.2 Constants

| Constant | Value | Meaning |
|---|---|---|
| `CHUNK_DELIMITER` | `"---"` | Structural boundary that separates the chunk summaries **and** the input chunks |
| `CHUNK_SEPARATOR` | `"\n---\n"` | Joins input chunks inside the prompt |

The delimiter is **structural**: the system prompt instructs the model that it
must never appear *inside* a summary, and `split()` relies on it to parse the
response back into one block per summary.

### 6.3 Members

| Member | Responsibility |
|---|---|
| `format_chunks(chunks)` | Join the chunks with `CHUNK_SEPARATOR` |
| `build(chunks)` | Render the full prompt in the fixed four-slot order, with the chunks in the `USER-INPUT` slot |
| `split(response)` | `[part.strip() for part in response.split("---")]` — one parsed summary block per delimiter |

The chunk prompt (Persian default basics): the system input pins the rules
(never merge/omit/reorder between chunks, preserve order, keep numbers/names,
output in the input language, never use `---` inside a summary), and the output
format mandates exactly as many summaries as input chunks in the layout
`[خلاصهٔ ۱]\n---\n[خلاصهٔ ۲]\n---\n...`.

## 7. `LLMChunkSummarizer` — batched, strict 1:1 chunk compression

`src/infrastructure/services/summarizers/llm_chunk_summarizer.py`.

### 7.1 Construction

```python
LLMChunkSummarizer(
    llm_client: ILLMClient,
    tokenizer: Tokenizer,
    *,
    builder: ChunkPromptBuilder | None = None,   # default: ChunkPromptBuilder()
    max_attempts: int = 3,                        # ≥ 1
    capacity_reserve: int = 0,                    # ≥ 0
)
```

- **`llm_client` and `tokenizer` are required** (type-checked in the
  constructor, rejected with `TypeError`). No `= None` + lazy instantiation.
- `builder` defaults to the standard `ChunkPromptBuilder` (an immutable-strategy
  default behind an explicit seam); a custom builder can be injected for tests
  or tuning.
- `max_attempts` bounds the retry loop per batch (validated `≥ 1`).
- `capacity_reserve` shrinks the usable budget, e.g. to keep head-room for model
  padding (validated `≥ 0`).

### 7.2 Batch selection (`_choose_batch`) — the token-budget fitting

For each batch, the account is:

```text
available       = max(0, capacity_tokens - capacity_reserve)
overhead        = tokenizer.count_tokens(builder.build([]))
separator_cost  = tokenizer.count_tokens("\n---\n")

scan chunks in order, appending chunk C to the batch while
    overhead + used + (separator_cost if batch non-empty else 0)
                + tokenizer.count_tokens(C)  ≤  available

if nothing fit  →  batch = [chunks[0]]        (progress guarantee)
```

- `overhead` is the once-per-call fixed cost of the `ROLE` + `SYSTEM-INPUT` +
  `OUTPUT-FORMAT` slots (measured by building the prompt with **zero** chunks —
  the empty `USER-INPUT` slot renders as `""` and is skipped by `assemble`).
- The separator cost is paid **between** chunks, so the first chunk in a batch
  adds none.
- Token accounting goes exclusively through the injected domain `Tokenizer`
  (`src/domain/context/tokenizer.py`) — never character guesses — exactly like
  `TRUNCATE`.
- The **min-batch-of-one** rule guarantees forward progress: no chunk size can
  stall the loop. The resulting over-capacity prompt is acceptable because the
  `ContextBuilder` final truncation safety net enforces the section budget
  downstream.

### 7.3 Response validation and retry (`_summarize_batch`)

```python
expected = len(batch)
for attempt in range(max_attempts):
    response = llm_client.complete(prompt).strip()
    parts    = builder.split(response)            # split on "---", stripped
    if len(parts) == expected and all(parts):     # strict 1:1 + non-empty
        return parts
    last_detail = f"expected {expected} summaries, got {len(parts)}"
raise ChunkSummarizationError(...)
```

Validation is deliberately strict on **two** axes:

- **Count**: `len(parts) == expected` — one summary per chunk. A response with
  fewer parts means the model merged or omitted chunks; more parts means it
  invented extra summaries.
- **Emptiness**: `all(parts)` — every part must be non-empty after stripping. An
  empty block is treated as a lost/missing summary, not accepted.

A mismatch re-requests the whole batch (same prompt) up to `max_attempts`. After
the last attempt the batch **raises `ChunkSummarizationError`** — the collection
is never partially summarized and never silently resumed with a corrupted
mapping.

### 7.4 The outer loop (`summarize_chunks`)

```python
results   = []
remaining = list(chunks)
while remaining:
    batch     = _choose_batch(remaining, capacity_tokens)
    prompt    = builder.build(batch)
    results  += _summarize_batch(batch, prompt)
    remaining = remaining[len(batch):]
return results
```

Edge cases:

- **Empty input** or `capacity_tokens <= 0` → returns `[]` immediately (no LLM
  call).
- **Single text** (`summarize`) → `summarize_chunks([text], capacity_tokens)`.
  A missing/zero `max_tokens` uses the documented default `_DEFAULT_SUMMARIZE_BUDGET
  = 2048`.

### 7.5 Worked example (char-based tokenizer, 1 char = 1 token)

Assume `overhead = len(builder.build([])) = 80`, `separator_cost = 5`
(`"\n---\n"`), chunks of `4` tokens each, three chunks total.

| capacity_tokens | batch₁ | batch₂ | LLM calls |
|---|---|---|---|
| `80 + 2*(5 + 4) = 98` | `[a, b]` (uses 80+9+9=98) | `[c]` | 2 |
| `80 + 3*(5 + 4) = 107` | `[a, b, c]` (uses 107) | — | 1 |
| `5` (tiny) | `[a]` (progress rule) | `[b]` | 2 |

The second row shows the batching goal met — the whole collection in a single
LLM call. The third row shows the progress guarantee: even a capacity that
cannot hold the fixed overhead never stalls the loop.

## 8. How the summarizer is used by Sections

The summarizer is injected into prompt Sections as the `SUMMARIZE` overflow
capability. The seam lives on the base classes; concrete Sections forward it
through their constructors.

### 8.1 `ReferencedSection` (single text)

`src/application/context/sections/referenced_section.py` — base of `RoleSection`,
`SystemInputSection`, `UserInputSection`, `OutputFormatSection`:

```python
def __init__(self, ..., llm_summarizer: ITextSummarizer | None = None, ...)

def summarize(self, content, capacity_tokens):
    if self._llm_summarizer is None:
        return super().summarize(content, capacity_tokens)   # plain Summarizer default
    if not content or capacity_tokens <= 0:
        return ""
    return self._llm_summarizer.summarize(content, max_tokens=capacity_tokens)
```

Resolution order: **LLM summarizer (`ITextSummarizer.summarize`) → plain
`Summarizer` default**. `None` when nothing is configured, so the strategy walker
falls through to the next overflow strategy.

### 8.2 `ReferencedCollectionSection` (chunks / collection)

`src/application/context/sections/referenced_collection_section.py` — base of
`ChunksSection` and `HistorySection`:

```python
def __init__(self, ..., chunk_summarizer: ITextSummarizer | None = None, ...)

def summarize(self, content, capacity_tokens):
    if self._chunk_summarizer is not None:
        if not self._items or capacity_tokens <= 0:
            return ""
        texts = self._enriched_item_texts()          # per-item Reference-enriched text
        if not texts:
            return ""
        summaries = self._chunk_summarizer.summarize_chunks(
            texts, capacity_tokens=capacity_tokens)
        return self.item_separator.join(summaries)   # 🔁 back to one section string
    if self._summarizer is None:
        return None
    ... # plain SummarizeStrategy(joined text) fallback
```

Key points:

- The collection's summarization is **item-driven**: it summarizes the
  Reference-enriched per-item texts obtained from `_enriched_item_texts()`
  (skipping empty items), then re-joins the 1:1 summaries with the section's
  `item_separator`. The legacy `content` parameter is ignored when items exist.
- `ChunksSection` renders items as `Chunk N: <content>` before enrichment;
  `HistorySection` renders `role: content`. Both forward `chunk_summarizer` to
  the base.
- An injected `char_summarizer` takes precedence over the plain `Summarizer`.

### 8.3 Reachability via the overflow pipeline

`ContextBuilder._fit` (`src/application/context/context_builder.py`) walks a
section's `OverflowStrategyStack` in priority order, dispatching each strategy
to the matching Section operation through `OverflowStrategyDispatcher`
(`src/application/context/overflow_strategy_dispatcher.py`) — `SUMMARIZE →
section.summarize(content, capacity)`. A final `TRUNCATE` safety net guarantees
the fitted content never exceeds the section's allocated capacity, even when
the summarizer returned a longer result than requested.

## 9. Composition root wiring

In `src/containers.py` (`Container`, the single composition root), the
single-text summarizer is fully wired:

```python
generation_client  = providers.Resource(init_generation_client, ...)   # pooled AsyncOpenAI
llm_client         = providers.Singleton(OpenAILLMClient, client=generation_client,
                                         model=generation_settings.LLM_MODEL, ...)
llm_summarizer     = providers.Singleton(LLMSummarizer, llm_client=llm_client)
```

- `generation_settings` (`LLM_PROVIDER`, `LLM_MODEL`, `LLM_TIMEOUT`,
  `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`) drives the Generation LLM client.
- `OpenAILLMClient` (`src/infrastructure/services/llm/openai_llm_client.py`)
  drives chat completions through the pooled `AsyncOpenAI` client from
  `LLMClientRegistry` (`src/infrastructure/services/llm/llm_client_registry.py`),
  mapping provider failures onto the LLM exception hierarchy. Its `complete()` is
  **synchronous by contract** (the whole Generation pipeline is synchronous); it
  bridges the async client with `asyncio.run` and must run in a thread without a
  running event loop.

**Known wiring gap (chunk summarizer):** `LLMChunkSummarizer` additionally needs
a runnable domain `Tokenizer`. The only adapter — `GemmaTokenizer`
(`src/infrastructure/services/tokenizers/gemma_tokenizer.py`) — requires the
`transformers` dependency, which is **not installed** (out-of-sync
`requirements.txt`). This mirrors the already-documented `context_builder`
tokenizer gap: the seam (`chunk_summarizer` on the collection sections) and its
test coverage exist; the DI wiring lives entirely inside the composition root and
is completed once a runnable tokenizer adapter exists. It is **not** added
outside `containers.py`.

## 10. Error model

| Exception | Base | Raised when |
|---|---|---|
| `ChunkSummarizationError` | `LLMBaseError` (`src/application/exceptions.py`) | A batch response still mismatches the 1:1 mapping after `max_attempts` — the collection is never sold as partially summarized |

`OpenAILLMClient` upstream errors flow through the existing LLM hierarchy
(`LLMConnectionError` / `LLMAPIError` / `LLMAuthenticationError`); a summarizer
never swallows them. Note: `ChunkSummarizationError` (like the pre-existing
`TokenizerError`) currently lacks an explicit entry in the presentation
`ERROR_REGISTRY` (`src/presentation/exception_handlers.py`) — a cross-scope
presentation-layer addition that keeps the registry-mapping CI test red, exactly
as before this feature.

## 11. Design notes and trade-offs

- **Batching vs. one-call-per-chunk.** `LLMChunkSummarizer` trades per-batch
  latency for a strict structural protocol (`---` + count validation); the model
  can fail that protocol, which is what the retry/raise path absorbs.
  `LLMSummarizer.summarize_chunks` avoids the risk entirely (1:1 by
  construction) at the cost of one call per chunk.
- **A delimiter is a correctness boundary.** The `---` marker is both
  an input joiner and an output parser; because the prompt forbids it inside a
  summary, a count mismatch is a reliable signal of corruption rather than of
  content.
- **Strictness over resilience.** A merged/reordered/omitted summary is never
  accepted. The price is a possible `ChunkSummarizationError`; the guarantee is
  that downstream code never sees a silently wrong chunk-to-summary mapping.
- **Budgets are hints + verified in two places.** Fixed overhead is pre-measured
  via `build([])`, input is greedily capped, and the `ContextBuilder` truncation
  safety net enforces the section budget as a hard boundary.

## 12. Tests

| File | Coverage |
|---|---|
| `tests/unit/infrastructure/test_llm_summarizer.py` | Port conformance, required-collaborator rejection, prompt assembly, budget surfacing, `summarize_chunks` 1:1 |
| `tests/unit/infrastructure/test_chunk_prompt_builder.py` | Fixed `Role → System Input → Chunks → Output Format` order, `---` joins/splits, custom prompts |
| `tests/unit/infrastructure/test_llm_chunk_summarizer.py` | Batch splitting across calls, retry-then-succeed, raise after exhausted attempts, single-chunk progress on tiny capacity, injected builder, single-text mode |
| `tests/unit/context/test_referenced_section_llm_summarize.py` | `llm_summarizer` seam, fallback to plain `Summarizer`, dispatcher flow |
| `tests/unit/context/test_referenced_collection_chunk_summarize.py` | `chunk_summarizer` seam on `ChunksSection`/`HistorySection`, item-driven semantics, empty/capsule cases, injection-not-instantiation |

Tests use a char-based `FakeTokenizer` (1 char = 1 token) and recording LLM
doubles, so batch-fitting math is deterministic and no model is needed.

## 13. File map

| Layer | File | Role |
|---|---|---|
| Interface | `src/application/interfaces/i_text_summarizer.py` | Aggregate port (`summarize` + `summarize_chunks`) |
| Interface | `src/application/interfaces/i_llm_client.py` | LLM invocation contract consumed by both adapters |
| Infrastructure | `src/infrastructure/services/summarizers/llm_summarizer.py` | Single-text adapter + `SummarizationPrompts` |
| Infrastructure | `src/infrastructure/services/summarizers/chunk_prompt_builder.py` | Chunk prompt format/parse (`ChunkPromptBuilder`, `ChunkSummarizationPrompts`) |
| Infrastructure | `src/infrastructure/services/summarizers/llm_chunk_summarizer.py` | Batched strict-1:1 adapter |
| Infrastructure | `src/infrastructure/services/llm/openai_llm_client.py` | OpenAI-compatible `ILLMClient` adapter |
| Application | `src/application/context/sections/referenced_section.py` | `llm_summarizer` seam (single text) |
| Application | `src/application/context/sections/referenced_collection_section.py` | `chunk_summarizer` seam (collections) |
| Application | `src/application/context/sections/chunks_section.py`, `history_section.py` | Forward `chunk_summarizer` |
| Application | `src/application/context/sections/{role,system_input,user_input,output_format}_section.py` | Forward `llm_summarizer` |
| Application | `src/application/exceptions.py` | `ChunkSummarizationError` (LLM hierarchy) |
| Composition | `src/containers.py` | `llm_client` + `llm_summarizer` providers; chunk summarizer wiring deferred (tokenizer gap) |

## Related documents

- [Overflow Strategies](overflow_strategies.md) — `SUMMARIZE` semantics and the strategy model.
- [Prompt-Builder Architecture](prompt_builder_entities.md) — `PromptBuilder`, canonical sections, rendering.
- [Section Mechanism](section_mechanism.md) — the `IPromptSection` port and `PromptSection` skeleton.
- [Reference Architecture](reference_architecture.md) — reference enrichment that feeds `_enriched_item_texts()`.
- [Gemma Tokenizer Usage](gemma_tokenizer_usage.md) — the runnable tokenizer adapter and its install gap.