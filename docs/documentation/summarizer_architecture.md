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
2. **Batch inference, prompts never mixed** — each chunk is rendered as its own
   independent prompt and the prompts are handed to the LLM as a batch
   (`complete_many`), so the provider can submit them in a single HTTP request
   while every chunk keeps a strict `chunk -> prompt -> summary` line. Remaining
   chunks roll into subsequent batches.
3. **Progress is guaranteed** — `capacity_tokens` only *gates* the whole call
   (`<= 0` returns no summaries). A chunk that would overflow is still
   summarized; the outer `ContextBuilder` truncation safety net absorbs the
   excess. Empty responses never stall the loop forever: per-item retries are
   bounded by `max_attempts` and then raise.
4. **No silent data loss** — if a chunk still has no summary after retries, the
   summarizer **raises** instead of returning a corrupted, partially-mapped
   result.
5. **Composition over assembly** — all collaborators (LLM client, prompt
   builder) are injected; the summarizer never constructs its own dependencies
   and never decides *how* a provider batches (that lives in the adapter).
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
- `capacity_tokens` on `summarize_chunks` *gates* the call: `<= 0` produces no
  summaries. It does **not** shrink prompt contents; final fitting against the
  section budget is the `ContextBuilder` truncation safety net's job.
- `summarize_chunks` raises when a chunk still has no summary after the
  adapter's retries (`ChunkSummarizationError`).

The port lives in the Application layer and references only the LLM-boundary
abstraction (`ILLMClient`) under required constructor injection. It never
mentions a concrete provider.

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
│ for each round of up to batch_size remaining chunks:     │
│                                                          │
│  STEP 1  build one prompt PER chunk:                     │
│            ROLE                                          │
│            SYSTEM-INPUT                                  │
│            USER-INPUT  = that chunk only                 │
│            OUTPUT-FORMAT                                 │
│          (chunks are never joined into one prompt)       │
│  STEP 2  ILLMClient.complete_many(prompts) once          │
│            → one result per prompt, in order             │
│            (provider batches them in one HTTP request,   │
│             e.g. vLLM /chat/completions/batch)           │
│  STEP 3  assign each non-empty result to its chunk       │
│            empty ──► add chunk to the retry list         │
│  STEP 4  retry only the unresolved chunks (a new batch)  │
│            until none remain  OR  max_attempts exhausted │
│            ──► raise ChunkSummarizationError             │
│  STEP 5  append this round's summaries (order preserved) │
│  STEP 6  continue with the next round of chunks          │
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
**chunk-summarization prompt format**. Because each chunk gets its own
independent prompt, there is no separator protocol and no response parsing here
any more — the builder's only job is to render one prompt around one chunk.

### 6.1 Fixed structure

```text
Role → System Input → chunk (User Input) → Output Format
```

The chunk is placed in the **`USER-INPUT`** slot of the shared `PromptBuilder`
(rendered after `SYSTEM-INPUT`, before `OUTPUT-FORMAT`), so the final order
matches the required `Role → System Input → User Input → Output Format`
structure.

### 6.2 Semantics

The prompt texts (Persian defaults) pin **isolation**: the model is told to
summarize *only* the text given — never merge, compare, or combine it with
anything else — and to keep numbers, names, and language. A completed summary
is therefore attributable to exactly one chunk and never influenced by another
chunk.

### 6.3 Member

| Member | Responsibility |
|---|---|
| `build(chunk)` | Render the full single-chunk prompt in the fixed four-slot order, with the chunk in the `USER-INPUT` slot |

There is **no** `format_chunks` / `split` / delimiter API: those belonged to the
old join-then-split design and are gone.

## 7. `LLMChunkSummarizer` — batched, strict 1:1 chunk compression

`src/infrastructure/services/summarizers/llm_chunk_summarizer.py`.

### 7.1 Construction

```python
LLMChunkSummarizer(
    llm_client: ILLMClient,
    *,
    builder: ChunkPromptBuilder | None = None,   # default: ChunkPromptBuilder()
    max_attempts: int = 3,                        # ≥ 1
    batch_size: int = 32,                         # ≥ 1
)
```

- **`llm_client` is required** (type-checked in the constructor, rejected with
  `TypeError`). No `= None` + lazy instantiation. The summarizer never decides
  *how* batching happens — it hands a list of prompts to
  `ILLMClient.complete_many`, and each adapter batches as its provider allows.
- `builder` defaults to the standard `ChunkPromptBuilder` (an immutable-strategy
  default behind an explicit seam); a custom builder can be injected for tests
  or tuning.
- `max_attempts` bounds the per-item retry rounds (validated `≥ 1`).
- `batch_size` caps how many chunks share one `complete_many` call (validated
  `≥ 1`). Remaining chunks are processed in subsequent rounds.

### 7.2 Batching (`summarize_chunks`) — rounds and the `complete_many` seam

```python
for start in range(0, len(chunks), batch_size):
    group = chunks[start:start + batch_size]
    results += _summarize_group(group)
```

- Chunks are consumed **in order**, `batch_size` at a time; each round produces
  its own `complete_many` call, so a collection is never supposed to fit a
  single call.
- `complete_many` is **the port seam** (`ILLMClient.complete_many`, with a
  default that degrades to one `complete` per prompt) — the adapter owns
  batching. In this codebase `OpenAILLMClient` submits all prompts in **one**
  HTTP request via the vLLM batch endpoint and falls back to bounded concurrency
  when the provider has no batch endpoint (see §9).

### 7.3 Per-item validation and retry (`_summarize_group`)

```python
prompts = [builder.build(chunk) for chunk in chunks]
summaries = [""] * len(chunks)
pending   = range(len(chunks))
attempt   = 0
while pending:
    if attempt >= max_attempts: raise ChunkSummarizationError(...)
    responses = llm_client.complete_many([prompts[i] for i in pending])
    unresolved = []
    for position, chunk_index in enumerate(pending):
        stripped = (responses[position] or "").strip()
        if stripped:   summaries[chunk_index] = stripped
        else:          unresolved.append(chunk_index)
    pending = unresolved
    attempt += 1
return summaries
```

Validation is deliberately strict on **one** axis:

- **Emptiness**: a result that is empty (or missing) after stripping means the
  model produced no summary for that chunk. That chunk alone is re-requested in
  the next round; chunks that already resolved are never re-sent.

There is no **count** axis to validate: because each chunk has its own prompt
and `complete_many` returns exactly one result per prompt, the 1:1 mapping is
guaranteed **by construction** (the adapter raises `LLMAPIError` if the batch
response cannot be indexed back onto the prompts). After the last attempt any
still-empty chunk raises `ChunkSummarizationError` — the collection is never
partially summarized and never silently resumed with a corrupted mapping.

### 7.4 Edge cases

- **Empty input** or `capacity_tokens <= 0` → returns `[]` immediately (no LLM
  call).
- **Single text** (`summarize`) → `summarize_chunks([text], capacity_tokens)`.
  A missing/zero `max_tokens` uses the documented default
  `_DEFAULT_SUMMARIZE_BUDGET = 2048`, which only *gates* whether the call runs.
- **Tiny capacity** — any positive capacity still summarizes, because capacity
  never limits prompt contents (final fitting is the `ContextBuilder` truncation
  safety net's job downstream).

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

In `src/containers.py` (`Container`, the single composition root), both
summarizers are fully wired:

```python
generation_client  = providers.Resource(init_generation_client, ...)   # pooled AsyncOpenAI
llm_client         = providers.Singleton(OpenAILLMClient, client=generation_client,
                                         model=generation_settings.LLM_MODEL, ...)
llm_summarizer     = providers.Singleton(LLMSummarizer, llm_client=llm_client)
chunk_summarizer   = providers.Singleton(LLMChunkSummarizer, llm_client=llm_client)
```

- `generation_settings` (`LLM_PROVIDER`, `LLM_MODEL`, `LLM_TIMEOUT`,
  `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`) drives the Generation LLM client.
- `OpenAILLMClient` (`src/infrastructure/services/llm/openai_llm_client.py`)
  drives chat completions through the pooled `AsyncOpenAI` client from
  `LLMClientRegistry` (`src/infrastructure/services/llm/llm_client_registry.py`),
  mapping provider failures onto the LLM exception hierarchy. Its `complete()` /
  `complete_many()` are **synchronous by contract** (the whole Generation
  pipeline is synchronous); they bridge the async client with `asyncio.run` and
  must run in a thread without a running event loop.
- **Batching strategy:** `complete_many` first tries vLLM's OpenAI-compatible
  batch endpoint `POST /v1/chat/completions/batch` (all prompts in one HTTP
  request, one conversation per prompt, response carries one choice per
  conversation indexed `0..N-1`). Providers without a batch endpoint answer with
  a 404, and the client falls back to issuing the prompts concurrently
  (continuous batching) bounded by `max_concurrency` (default 32). There is no
  tokenizer dependency any more — the chunk summarizer no longer budget-fits,
  which also closes the former tokenizer wiring gap.

**Known wiring seam:** the `chunk_summarizer` and `llm_summarizer` providers
exist in the composition root, but the prompt Sections that *consume* them
(`ReferencedCollectionSection`, `ReferencedSection`) are not yet wired to these
providers — that wiring belongs to the `context_builder` provider, which is
still gated on the `GemmaTokenizer` install gap (`transformers` not installed).
The summarizers themselves are fully runnable.

## 10. Error model

| Exception | Base | Raised when |
|---|---|---|
| `ChunkSummarizationError` | `LLMBaseError` (`src/application/exceptions.py`) | One or more chunks still have no non-empty summary after `max_attempts` — the collection is never sold as partially summarized |

`OpenAILLMClient` upstream errors flow through the existing LLM hierarchy
(`LLMConnectionError` / `LLMAPIError` / `LLMAuthenticationError`); a summarizer
never swallows them. Note: `ChunkSummarizationError` (like the pre-existing
`TokenizerError`) currently lacks an explicit entry in the presentation
`ERROR_REGISTRY` (`src/presentation/exception_handlers.py`) — a cross-scope
presentation-layer addition that keeps the registry-mapping CI test red, exactly
as before this feature.

## 11. Design notes and trade-offs

- **Batching vs. one-call-per-chunk.** `LLMChunkSummarizer` moves batching to
  the provider seam (`ILLMClient.complete_many`): one HTTP request (vLLM batch
  endpoint) or bounded concurrency can serve a round of chunks with zero
  merging. Isolation is *by construction* — each chunk has its own prompt, so
  no response protocol (separators, counts) can be violated. `LLMSummarizer`
  still makes one `complete` call per chunk, which is simpler but never batched.
- **No delimiter, no controlled-merge hazard.** The old join-then-split design
  relied on `---` both as an input joiner and an output parser, giving the model
  a chance to merge/reorder summaries. Independent prompts make chunk-to-summary
  attribution structural, and retries re-send only the unresolved chunk.
- **Strictness over resilience.** An empty (lost) summary is never silently
  accepted. The price is a possible `ChunkSummarizationError`; the guarantee is
  that downstream code never sees a silently wrong chunk-to-summary mapping.
- **Budgets are gates; the section budget is enforced downstream.** Capacity no
  longer shapes prompt contents — `capacity_tokens <= 0` means "no call", and the
  `ContextBuilder` truncation safety net enforces the section budget as a hard
  boundary after summarization.
- **Indexed batch responses.** The OpenAI-compatible batch contract returns one
  choice per conversation indexed `0..N-1`; the client maps choices back by
  `index` and validates the count, so a wrong-count/out-of-range response raises
  `LLMAPIError` rather than misaligning summaries to chunks.

## 12. Tests

| File | Coverage |
|---|---|
| `tests/unit/infrastructure/test_llm_summarizer.py` | Port conformance, required-collaborator rejection, prompt assembly, budget surfacing, `summarize_chunks` 1:1 |
| `tests/unit/infrastructure/test_chunk_prompt_builder.py` | Fixed `Role → System Input → User Input → Output Format` order, one-chunk isolation, no `---`, custom prompts |
| `tests/unit/infrastructure/test_llm_chunk_summarizer.py` | `complete_many` used (never `complete`), whole-collection round, `batch_size` rounding into follow-up rounds, per-item retry of only unresolved chunks, raise after exhausted attempts, tiny-capacity progress, injected builder, single-text mode |
| `tests/unit/infrastructure/test_openai_llm_client.py` | Single batch request with one conversation per prompt, choice-index mapping, 404 fallback to concurrent completions, batch error translation, count/index contract violations, missing content |
| `tests/unit/context/test_referenced_section_llm_summarize.py` | `llm_summarizer` seam, fallback to plain `Summarizer`, dispatcher flow |
| `tests/unit/context/test_referenced_collection_chunk_summarize.py` | `chunk_summarizer` seam on `ChunksSection`/`HistorySection`, item-driven semantics, empty/capsule cases, injection-not-instantiation |

Tests use recording LLM doubles that capture the batch of prompts, so
rounding/ordering/retry logic is deterministic and no model or network is
needed.

## 13. File map

| Layer | File | Role |
|---|---|---|
| Interface | `src/application/interfaces/i_text_summarizer.py` | Aggregate port (`summarize` + `summarize_chunks`) |
| Interface | `src/application/interfaces/i_llm_client.py` | LLM invocation contract (`complete` + `complete_many`) consumed by both adapters |
| Infrastructure | `src/infrastructure/services/summarizers/llm_summarizer.py` | Single-text adapter + `SummarizationPrompts` |
| Infrastructure | `src/infrastructure/services/summarizers/chunk_prompt_builder.py` | Single-chunk prompt format (`ChunkPromptBuilder`, `ChunkSummarizationPrompts`) |
| Infrastructure | `src/infrastructure/services/summarizers/llm_chunk_summarizer.py` | Batched strict-1:1 adapter (rounds + per-item retry) |
| Infrastructure | `src/infrastructure/services/llm/openai_llm_client.py` | OpenAI-compatible `ILLMClient` adapter — batch endpoint + concurrency fallback |
| Application | `src/application/context/sections/referenced_section.py` | `llm_summarizer` seam (single text) |
| Application | `src/application/context/sections/referenced_collection_section.py` | `chunk_summarizer` seam (collections) |
| Application | `src/application/context/sections/chunks_section.py`, `history_section.py` | Forward `chunk_summarizer` |
| Application | `src/application/context/sections/{role,system_input,user_input,output_format}_section.py` | Forward `llm_summarizer` |
| Application | `src/application/exceptions.py` | `ChunkSummarizationError` (LLM hierarchy) |
| Composition | `src/containers.py` | `llm_client` + `llm_summarizer` + `chunk_summarizer` providers (all wired) |

## Related documents

- [Overflow Strategies](overflow_strategies.md) — `SUMMARIZE` semantics and the strategy model.
- [Prompt-Builder Architecture](prompt_builder_entities.md) — `PromptBuilder`, canonical sections, rendering.
- [Section Mechanism](section_mechanism.md) — the `IPromptSection` port and `PromptSection` skeleton.
- [Reference Architecture](reference_architecture.md) — reference enrichment that feeds `_enriched_item_texts()`.
- [Gemma Tokenizer Usage](gemma_tokenizer_usage.md) — the runnable tokenizer adapter and its install gap.