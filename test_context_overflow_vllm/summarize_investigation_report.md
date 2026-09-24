# Summarize Investigation Report

Investigation date: 2026-09-23.

Object of study: the real `SUMMARIZE` overflow strategy and its integration with
the `ContextBuilder` capacity-allocation algorithm in `src/application/context/`
and `src/infrastructure/services/summarizers/`.

Notation used throughout: **FACT = verified from source code**; **OBS =
observed by executing code (experiment/tests or the real-vLLM session)**;
**ASSUMED = reasonable interpretation not fully exercised**; **CONCL =
conclusion derived from the facts/observations above it**.

---

## 1. Executive Summary

- The allocated capacity **does** reach the `SUMMARIZE` operation as a function
  argument: `ContextBuilder._fit` passes it to the dispatcher, which passes it
  to `section.summarize(content, capacity_tokens)`.
- However, downstream the capacity is used **only as a gate** (run/abort the
  summarization call when `capacity_tokens <= 0`). It is **not** used to set the
  LLM `max_tokens`, and for the chunk path it is **not** embedded in the
  summarization prompt either.
- The **effective upper bound on generated summary length is the global
  `LLM_MAX_TOKENS`** setting, carried by `OpenAILLMClient._max_tokens` into every
  completion request (`openai_llm_client.py:98,144`).
- Post-generation validation **does exist**: `ContextBuilder._fit` checks the
  returned summary's token count against the allocated capacity and returns it
  only if it fits; otherwise it continues through the strategy stack and finally
  applies a `TRUNCATE` safety net (`context_builder.py:160-171`).
- Consequence (OBS, Experiment B): when a 256-token summary exceeds a
  181-token capacity, the summary is **discarded** and the section is filled
  with the **truncated original text**, not with the summary.
- The existing real-vLLM test proves `final_content_tokens <= capacity`
  (`256 <= 323`), which is guaranteed by the `_fit` safety net regardless of the
  summarizer. It does **not** prove the summary *generation* was sized to fit
  the capacity; the equality `summary = 256 = LLM_MAX_TOKENS` shows the summary
  length was driven by global configuration.

**CONCL.** The pipeline

```text
ContextBuilder allocated capacity
        ↓
Summarizer target length
        ↓
LLM max_tokens
        ↓
Generated summary length
```

is **not** intentionally connected as sizes: the capacity is forwarded but
ignored as a target. In practice the chain is:

```text
ContextBuilder allocated capacity  --(gate only)-->  summarizer call
LLM_MAX_TOKENS  --(request max_tokens)-->  generated summary length
capacity  --(post-hoc _fit validation)-->  accept | discard | truncate
```

---

## 2. Current Architecture

Components involved (all wired in `src/containers.py`):

| Component | Class | File |
|---|---|---|
| Allocation engine | `DemandAllocator` | `src/application/context/allocation/demand_allocator.py` |
| Allocation engine | `RedistributionAllocator` | `src/application/context/allocation/redistribution_allocator.py` |
| Allocation engine | `CapacityAllocator` | `src/application/context/allocation/capacity_allocator.py` |
| Orchestrator | `ContextBuilder` | `src/application/context/context_builder.py` |
| Strategy mapping | `OverflowStrategyDispatcher` | `src/application/context/overflow_strategy_dispatcher.py` |
| Section contract | `CompressibleSection` | `src/application/interfaces/i_compressible_section.py` |
| Collection sections | `ReferencedCollectionSection` / `ChunksSection` | `src/application/context/sections/{referenced_collection_section,chunks_section}.py` |
| Aggregated summarizer port | `ITextSummarizer` | `src/application/interfaces/i_text_summarizer.py` |
| LLM client port | `ILLMClient` | `src/application/interfaces/i_llm_client.py` |
| Chunk summarizer adapter | `LLMChunkSummarizer` | `src/infrastructure/services/summarizers/llm_chunk_summarizer.py` |
| Chunk prompt builder | `ChunkPromptBuilder` | `src/infrastructure/services/summarizers/chunk_prompt_builder.py` |
| LLM client adapter | `OpenAILLMClient` | `src/infrastructure/services/llm/openai_llm_client.py` |
| Settings | `GenerationSettings` | `src/infrastructure/configs/settings.py` |

The two summarization flavors:

1. **Single-text path** (`ReferencedSection.summarize`,
   `referenced_section.py:107-124`): forwards `capacity_tokens` as
   `max_tokens` into the injected `ITextSummarizer`. The aggregate
   `LLMSummarizer` surfaces that budget as an OUTPUT-FORMAT instruction
   ("خلاصه باید در حداکثر {max_tokens} توکن تهیه شود.",
   `llm_summarizer.py:21-23,85-90`) but never as the request `max_tokens`.
2. **Chunk path** (`ReferencedCollectionSection.summarize`,
   `referenced_collection_section.py:142-171`): forwards `capacity_tokens` into
   `LLMChunkSummarizer.summarize_chunks`. **FACT:** `ChunkPromptBuilder`
   (chunk_prompt_builder.py:3-58) renders `ROLE -> SYSTEM-INPUT -> chunk ->
   OUTPUT-FORMAT` with **no length/budget instruction at all**
   (OBS: the prompt contains no `حداکثر` max-tokens phrase; the only occurrences
   of words like "token"/"capacity" in the rendered prompt come from the
   English chunk *content* itself).

The real-vLLM test uses the **chunk path** (`test_pipeline.py:160`,
`summarizers = {"chunk-2": chunk_summarizer}`, and
`chunk_summarizer` resolves to `LLMChunkSummarizer` in `containers.py:293-296`).

---

## 3. ContextBuilder Capacity Calculation

### Where `323` comes from (chunk-2, budget 400)

**FACT/DERIVATION (reproduced by executing the real allocators with the real
Qwen tokenizer in `test_context_overflow_vllm/summarize_experiment.py`):**

1. `ContextBuilder.build` computes the **separator reservation**
   (`context_builder.py:64-68`): 6 sections -> 5 separators x 1 token (`"\n\n"`)
   = **5**; usable budget = 400 - 5 = **395**.
2. `DemandAllocator.allocate` (largest-remainder/Hamilton over **demand**,
   `demand_allocator.py:23-63`) yields these initial shares:

   | Section | demand | initial share |
   |---|---|---|
   | ROLE | 0.3 | 51 |
   | HISTORY | 0.4 | 69 |
   | CHUNKS | 0.5 | 86 |
   | SYSTEM-INPUT | 0.5 | 86 |
   | USER-INPUT | 0.4 | 69 |
   | OUTPUT-FORMAT | 0.2 | 34 |

3. `CapacityAllocator.allocate` (`capacity_allocator.py:62-86`): sections whose
   **needed_tokens < share** return the difference to a free pool; sections that
   need more submit an `ExpansionRequest` weighted by **importance**.

   | Section | needed | vs share | effect |
   |---|---|---|---|
   | ROLE | 20 | 20 < 51 | returns 31 |
   | HISTORY | 0 | 0 < 69 | returns 69 |
   | CHUNKS | 456 | 456 >= 86 | expansion request: weight **0.4**, need 370 |
   | SYSTEM-INPUT | 19 | 19 < 86 | returns 67 |
   | USER-INPUT | 19 | 19 < 69 | returns 50 |
   | OUTPUT-FORMAT | 14 | 14 < 34 | returns 20 |

   Free pool = 31+69+67+50+20 = **237**.

4. `RedistributionAllocator.redistribute` (`redistribution_allocator.py:29-70`):
   only CHUNKS has a pending expansion, so it receives the whole pool capped at
   its remaining need:
   `award = min(int(237 * 0.4 / 0.4), 370) = 237`.
   **CHUNKS capacity = 86 + 237 = 323.**

### Roles of `demand` and `importance`

- **FACT `demand`** (`i_prompt_section`, `prompt_section.py:122-133`): relative
  capacity appetite of a section in `[0.0,1.0]`; used **only** for the initial
  proportional split (step 2). CHUNKS demand `0.5`.
- **FACT `importance`** (`prompt_section.py:111-120`): semantic weight in
  `[0.0,1.0]`, used **only** as the weight of expansion requests during
  redistribution (step 4). CHUNKS importance `0.4`.

### Is `323` a hard maximum for the final section content?

**FACT: Yes.** `ContextBuilder.build` builds every section's `SectionOutput`
with `capacity_tokens=share` (`context_builder.py:96,106`) and the final prompt
is assembled from the *fitted* content. `_fit` guarantees the returned content
never exceeds the share (its own TRUNCATE safety net, lines 162-171), and the
`total_tokens` check confirms the assembled prompt stays within budget
(`context_builder.py:116-120`). The real-vLLM report and the experiments both
show `fitted <= capacity`.

### Does ContextBuilder explicitly pass this capacity to the summarization logic?

**FACT: Yes, it is passed as an argument** along the chain
`_fit -> dispatcher.apply -> section.summarize(content, capacity_tokens)`
(`context_builder.py:150-156`, `overflow_strategy_dispatcher.py:40-41`,
`referenced_collection_section.py:160-161`). Whether the recipient *uses* it as
a size constraint is a separate question (Section 4/5).

---

## 4. SUMMARIZE Execution Flow (Chunk 2: 447 tokens -> capacity 323)

Complete traced path (all **FACT**s):

1. **Overflow detection**: `ContextBuilder.build` renders each section and
   compares `needed_tokens` (456 for the rendered CHUNKS, which includes the
   `Chunk 1:` numbering prefix) against its share: `overflowed = needed > share`
   (`context_builder.py:76,97`). 456 > 323 -> overflow.
2. **Dispatch**: `_fit(section, content, 323)` iterates the section's
   `OverflowStrategyStack` (`[SUMMARIZE, TRUNCATE]`,
   `test_pipeline.py:153-155`) and calls
   `OverflowStrategyDispatcher.apply(section, SUMMARIZE, content, 323, tokenizer)`
   (`context_builder.py:149-156`, `overflow_strategy_dispatcher.py:40-41`).
3. **Invoke the LLM**: the dispatcher calls `ChunksSection.summarize(content,
   323)`, which is `ReferencedCollectionSection.summarize`
   (`referenced_collection_section.py:142-163`). Because a `chunk_summarizer`
   (`LLMChunkSummarizer`) is injected, it calls
   `summarize_chunks([enriched_text], capacity_tokens=323)`
   (`llm_chunk_summarizer.py:74-84`).
4. **Arguments passed to the summarization operation**: the **content** and the
   **capacity** (323). `capacity_tokens` is applied at
   `llm_chunk_summarizer.py:78` (`if not chunks or capacity_tokens <= 0: return
   []`) — the only use.
5. **How the summarizer determines its target output size**: in the chunk path,
   it does **not**. `LLMChunkSummarizer._summarize_group` builds prompts with
   `ChunkPromptBuilder` (no size instruction) and simply calls
   `complete_many(prompts)` (`llm_chunk_summarizer.py:88,99`). The model decides
   how long to write.
6. **How `max_tokens` is selected for the LLM request**: fixed per client:
   `OpenAILLMClient._max_tokens`, set once from `generation_settings.LLM_MAX_TOKENS`
   in the composition root (`containers.py:278-284`,
   `openai_llm_client.py:58-71`), and written into both the single and batch
   request bodies (`openai_llm_client.py:98,144`).
7. **Did `max_tokens=256` come from the capacity?** **NO.** It came from
   `LLM_MAX_TOKENS=256` (environment). 323 was never translated into a request
   parameter (OBS + FACT: batch body at `openai_llm_client.py:138-145` contains
   only `model`, `messages`, `temperature`, `max_tokens=self._max_tokens`).
8. **Generated summary**: OBS (real-vLLM session) the model returned **exactly
   256 tokens**, i.e. it filled the `max_tokens` cap (content was cut mid-word,
   consistent with hitting the cap).
9. **Post-generation check**: `_fit` token-counts the result and returns it only
   if `<= capacity` (`context_builder.py:160`). 256 <= 323 -> the summary is kept
   as the section content.
10. **When the summary is still larger than capacity**: the loop continues to
    the next strategy (TRUNCATE applied to the **original** content, not the
    summary), and a final TRUNCATE safety net guarantees fit
    (`context_builder.py:160-171`). The oversize summary is discarded (OBS,
    Experiment B — see Section 7).

---

## 5. Relationship Between Capacity and `max_tokens`

**FACT (source):**
- `summarize_chunks` receives `capacity_tokens`, uses it only as a `<=0` gate:
  `llm_chunk_summarizer.py:78`.
- `ChunkPromptBuilder` emits no length instruction: `chunk_prompt_builder.py:50-58`.
- Every completion request carries `max_tokens = LLM_MAX_TOKENS`:
  `openai_llm_client.py:98,144`; settings default 4096 `settings.py:76`.
- `_fit` accepts a summary only if `count_tokens(summary) <= capacity`:
  `context_builder.py:160`.

**OBS (real-vLLM session + standalone probe):** summary == `LLM_MAX_TOKENS`
(256) exactly — generation length is capped by `max_tokens`, not by capacity.

**Answering the three hypothetical questions from the task, derived from the
implementation (and demonstrated in Section 7):**

> If `LLM_MAX_TOKENS` is changed from 256 to 128 (allocation unchanged):
> CHUNKS 2 capacity stays 323; the LLM would return ~128 tokens (its new cap);
> `_fit` would accept it (128 <= 323) and the section would contain a 128-token
> summary. Capacity 323 is untouched — the capacity does **not** "grow" or
> "shrink" to match `max_tokens`, and the summary would make no use of the upper
> 323-128=195 tokens. (This is exactly Experiment C, inverted.)

> If ContextBuilder allocates 180 for Chunk 2 while `LLM_MAX_TOKENS=256`:
> nothing prevents generation of a 256-token summary. `_fit` rejects it
> (256 > 180), moves to TRUNCATE on the original content and returns a
> 180-token prefix of the **original** text; the 256-token summary is discarded
> (Experiment B).

> If ContextBuilder allocates 400 while `LLM_MAX_TOKENS=256`: the summarizer
> can never use the full 400-token capacity; output is capped at ~256 by the
> request `max_tokens`, so at most 256 of the 400 slots can be consumed
> (Experiment A/C reasoning).

**CONCL.** The numbers `capacity=323`, `LLM_MAX_TOKENS=256`, `summary=256` in
the shipped test are **coincidentally compatible**, not intentionally
connected: 256 <= 323 purely because the global cap happened to be below the
allocated capacity. The equality `summary == LLM_MAX_TOKENS` is not about the
capacity.

---

## 6. Post-Summarization Validation

**FACT: validation exists** in `ContextBuilder._fit`:

```python
# context_builder.py:149-171
for strategy in stack.strategies:
    result = self._dispatcher.apply(section, strategy, content, capacity, tokenizer=...)
    if result is None: continue
    best = result
    if self._tokenizer.count_tokens(result) <= capacity:   # <- validation
        return result
...
if best and self._tokenizer.count_tokens(best) > capacity: # final safety net
    truncated = self._dispatcher.apply(section, TRUNCATE, best, capacity, ...)
```

- The check is a **token count** performed with the real tokenizer
  (`count_tokens`) against the allocated capacity. Yes to
  `token_count <= allocated_capacity?`.
- When the summary is too large:
  - it is **not** truncated (as a summary);
  - summarization is **not** retried with a smaller target (there is no
    retry-toward-capacity loop);
  - the loop **moves on to the next strategy** in the stack (here TRUNCATE of
    the original content);
  - the **section is not rejected** — the safety net guarantees *some* content
    that fits.

**CONCL.** Validation governs **content selection** (which text is used), not
**generation length**. The docstrings are explicit that this is the design:
`LLMChunkSummarizer` "capacity_tokens only gates the whole call (<=0 produces no
summaries); final fitting against the section budget is handled downstream by
the ContextBuilder truncation safety net" (`llm_chunk_summarizer.py:35-37`), and
`ContextBuilder._fit` "final TRUNCATE safety net guarantees the fitted content
never exceeds the capacity" (`context_builder.py:139-144`).

---

## 7. Experimental Results

Method: real `ContextBuilder` + real Qwen2.5 tokenizer (via the lightweight
`tokenizers` crate over `tokenizer.json`; same BPE, counts identical to the HF
fast tokenizer — verified: chunk-2 = 447 tokens, separator = 1 token) + real
allocators + real `ChunksSection` + real `LLMChunkSummarizer`, with a
deterministic fake `ILLMClient` returning an exact-token-count summary (the DI
seam the architecture itself uses in unit tests). Script:
`test_context_overflow_vllm/summarize_experiment.py`.

Allocation preconditions confirmed identical to the production run:

| Scenario | budget | CHUNKS capacity | CHUNKS needed | overflowing |
|---|---|---|---|---|
| A | 400 | 323 | 456 | yes |
| B | 258 | 181 | 456 | yes |
| C | 480 | 403 | 456 | yes |

Results (all OBS):

| Scenario | LLM summary returned | `summary <= capacity`? | final content is the summary? | final tokens |
|---|---|---|---|---|
| A | 256 | 256 <= 323 TRUE | TRUE | 256 |
| B | 256 | 256 <= 181 FALSE | **FALSE** (truncated original) | 181 |
| C | 128 | 128 <= 403 TRUE | TRUE | 128 |

Interpretation:

- A and C prove the summary length is **chosen by the (fake) LLM / by the
  request `max_tokens`** — the capacity did not size the summary (in C the LLM
  "could have written" up to 403 but produced 128 and the section happily used
  128).
- B proves that when a summary overshoots the capacity, `_fit`'s validation
  discards it and fills the section with a **truncated prefix of the original
  content** (181 tokens), i.e. `final_content <= capacity` holds **without** any
  capacity-aware summary generation.

Prompt inspection (OBS): the chunk summarization prompt
(`ChunkPromptBuilder().build(chunk)`) contains **no** `حداکثر` (max-tokens)
instruction, and the only "token"/"capacity" words come from the English chunk
text itself. `LLMSummarizer` (single-text flavor) *does* emit a Persian
"at most {n} tokens" instruction with `n = capacity_tokens`, but that path is
not used by the real-vLLM chunk test, and even there the HTTP `max_tokens` stays
`LLM_MAX_TOKENS`.

Real-vLLM corroboration (OBS, prior session, `test_report.md`): chunk-2 summary
= exactly 256 tokens = `LLM_MAX_TOKENS`, mid-word cut at the cap; 447 -> 256
tokens; `256 <= 323` accepted.

Caveat: physical vLLM inference was not re-run for this investigation (the local
CPU-only instance is very slow to start and serve). The only behavior not
exercised end-to-end here is the model literally generating a 256-token string
under a 181 capacity; that combination is equivalent to Experiment B's
deterministic 256-token return and yields the same fallback (the fake and the
real LLM both produce a fixed-length text the `_fit` gate must judge).

---

## 8. What the Current Test Actually Proves

The shipped real-vLLM test (`test_pipeline.py` + `test_report.md`) proves:

1. The `SUMMARIZE` overflow strategy **runs** against a real vLLM
   (OBS: a genuine model completion was produced).
2. The generated summary is **real LLM output** (not a static stub).
3. **`final_summary_tokens <= capacity` holds** for chunk 2 (256 <= 323) — but
   this is guaranteed by the `_fit` fit-gate + TRUNCATE safety net for **any**
   content, whatever its provenance.
4. The final section content used by the batch request is the summary.

The assertion effectively verified is therefore:
`final_content_tokens <= context_allocated_capacity` (guaranteed by `_fit`).

---

## 9. What the Current Test Does Not Prove

It does **not** prove:

1. `summarizer_target <= capacity` — no target is derived from capacity.
2. `generated_summary <= capacity` as a *consequence of generation* — the bound
   came from `LLM_MAX_TOKENS = 256 < 323`; the test is silent on whether the
   summary would have been sized differently (or accepted at all) under a
   smaller capacity.
3. Capacity-aware prompt guidance for the chunk path — the prompt contains no
   length instruction (FACT + OBS).
4. The robustness story that matters: had chunk 2's capacity been 180
   (Experiment B), the same test configuration would produce a **truncated
   original** in the section while the 256-token summary was thrown away — the
   report's infer_strategy would still label it "SUMMARIZE"
   (`test_pipeline.py:353-354`) even though the summary never made it into the
   prompt.

Formally: the current test proves
`final_summary_tokens <= context_allocated_capacity`
(and even that only for the summary-was-accepted case) **only via the post-hoc
`_fit` gate**, i.e. it proves
`final_summary_tokens <= min(LLM_MAX_TOKENS, capacity)` trivially, while
`sized-to-capacity generation` is untested and, per Section 5, not implemented.

---

## 10. Execution Trace

Actual trace for chunk 2, every `?` filled from the implementation and the
observed run:

```text
Original chunk
    447 tokens
        ↓  PromptBuilder(seed_defaults=True).set_section("CHUNKS", ChunksSection(...))
        ↓  ContextBuilder.build(builder, max_tokens=400)
        ↓  separator reservation = 5 tokens; usable budget = 395
        ↓  CapacityAllocator: DemandAllocator(197? -> share 86) + redistribution (+237)
        ↓
Allocated capacity
    323 tokens                      (SectionOutput.capacity_tokens = 323)
        ↓  overflowed = 456 > 323
        ↓  _fit(section, content, 323)
        ↓  OverflowStrategyDispatcher.apply(section, SUMMARIZE, content, 323)
        ↓  ChunksSection.summarize(content, 323)
        ↓  ReferencedCollectionSection.summarize -> summarize_chunks(texts, capacity_tokens=323)
        ↓  capacity_tokens used ONLY as gate (<=0 -> [])   [llm_chunk_summarizer.py:78]
        ↓  ChunkPromptBuilder.build(chunk)  (NO length instruction)   [chunk_prompt_builder.py:50-58]
        ↓  complete_many([prompt])
        ↓
LLM request parameters
    model = /models/LLM
    max_tokens = 256   (LLM_MAX_TOKENS, not 323)   [openai_llm_client.py:144]
    temperature = 0.2
        ↓
Real vLLM
        ↓
Generated summary
    256 tokens   (== max_tokens cap; OBS)
        ↓
Post-processing / validation
    count_tokens(summary) = 256 <= 323 -> ACCEPTED   [_fit, context_builder.py:160]
        ↓
Final section content
    256 tokens   (the summary)
        ↓
Batch to vLLM (final answer)
    prompt contains the 256-token summary
```

Counterfactual trace for `capacity = 181` (Experiment B):

```text
Generated summary
    256 tokens
        ↓
count_tokens(summary) = 256 <= 181? NO
        ↓  next strategy: TRUNCATE applied to ORIGINAL content (_fit passes original content)
Truncated original
    181 tokens
        ↓
Final section content
    181 tokens  (a prefix of the ORIGINAL text; summary discarded)
```

---

## 11. Findings

1. **FACT** — Capacity reaches `SUMMARIZE` as an argument
   (`context_builder.py:150`, `overflow_strategy_dispatcher.py:41`,
   `referenced_collection_section.py:160`).
2. **FACT** — In the chunk path, `capacity_tokens` is consumed only as a
   run/abort gate (`llm_chunk_summarizer.py:78`); the summarization prompt
   carries no size instruction (`chunk_prompt_builder.py:50-58`, OBS).
3. **FACT** — The request-level output cap is `LLM_MAX_TOKENS`, set once at
   client construction (`containers.py:283`, `openai_llm_client.py:98,144`,
   `settings.py:76`).
4. **OBS** — The real model filled `max_tokens` exactly (256 tokens), so the
   observed summary length was a `max_tokens` artifact, not a capacity artifact.
5. **FACT** — Post-generation validation exists in `_fit`
   (`context_builder.py:160`), which we verified by experiment: oversize
   summaries are discarded and replaced by a TRUNCATE of the original.
6. **CONCL** — The intended-looking pipeline
   `capacity -> summarizer target -> LLM max_tokens -> summary length`
   is **not connected**. The actual connection is
   `LLM_MAX_TOKENS -> summary length`,
   `capacity -> accept/discard decision` (post-hoc), and
   `capacity -> TRUNCATE fallback size`.
7. **FACT** — This is documented intended design, not an accident
   (`llm_chunk_summarizer.py:35-37`, `context_builder.py:139-144`);
   nevertheless it produces the surprising behavior that an oversize summary is
   silently replaced by a truncated original (no re-summarization, no summary
   truncation), and the report labels such a section "SUMMARIZE"
   (`test_pipeline.py:353-354`).

---

## 12. Open Questions

1. Should an overshoot summary be **truncated as a summary** (kept semantics)
   instead of being replaced by a prefix of the original? That would require the
   safety net to TRUNCATE the summary (`best`) rather than re-running TRUNCATE on
   the original content — currently `_fit` always passes the *original* content
   to the next strategy (only the final safety net at line 163 passes `best`).
2. Should the summarizer actually **size its output to the capacity** (e.g. pass
   capacity-derived `max_tokens` per call, or instruct the model with the budget
   in the chunk prompt as `LLMSummarizer` already does)? Any such change touches
   `LLMChunkSummarizer`/`ChunkPromptBuilder`/client call sites and is out of
   scope for this investigation.
3. `infer_strategy` in the test (`test_pipeline.py:344-357`) would mislabel an
   Experiment-B fallback as "SUMMARIZE"; the test cannot currently distinguish
   "summary used" from "summary generated but discarded" without inspecting the
   raw summary, which `ContextBuilder` does not expose.
4. Whether `LLMSummarizer`'s "at most {n} tokens" prompt instruction being
   ignored in favor of `LLM_MAX_TOKENS` is intended for the single-text path too
   (the model may be asked for "at most 323 tokens" while the request caps at
   256).

---

## Appendix: Files touched by the investigation (none of them production code)

- `test_context_overflow_vllm/summarize_experiment.py` — the deterministic
  experiment (real components + fake `ILLMClient` + real-tokenizer adapter over
  the `tokenizers` crate).
- `test_context_overflow_vllm/investigate_capacity_probe.py` — allocation
  sweep used to pick budgets reproducing capacity 181/323/403 (kept for
  reproducibility).
- This report.