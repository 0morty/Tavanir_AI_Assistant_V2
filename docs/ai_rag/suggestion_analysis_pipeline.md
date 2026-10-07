# Suggestion Analysis Pipeline: Tri-Track Hybrid Retrieval, Cross-Encoder Reranking & Hydration

- **Document Version:** 2.0.0
- **Status:** Existing retrieval reference; Generation handoff now invokes the injected generator with usable prepared evidence. Retrieval sections are unchanged in this Generation-only update.
- **Component:** Core Retrieval-Augmented Generation (RAG) Subsystem / Suggestion Analysis
- **Service:** Tavanir AI Assistant V2 (`tavanir-ai-assistant-v2`)
- **System of Record:** PostgreSQL (`suggestions` table)
- **Vector Search Index:** Qdrant (`tavanir_suggestion_v1`)
- **Cross-Encoder Model:** `BAAI/bge-reranker-v2-m3` via Hugging Face Text Embeddings Inference (TEI)
- **Dense Embedding Model:** `google/embedding-gemma-2b` (768-dimensional) via TEI
- **Sparse Embedding Model:** Persian BM25 Token Weighting Engine

---

## 1. Executive Summary & Problem Space

The **Suggestion Analysis Workflow** is the current information retrieval, precedent evaluation, and prompt-preparation pipeline in the Tavanir AI Assistant. After prepared evidence exists, the production route delegates to final Generation and returns its parsed answer; its existing no-evidence branch returns diagnostics. See the [Generation API test summary](../documentation/llm_generation_test_summary.md) for the separate lower-level vLLM validation. When an employee or committee submits a technical suggestion, this subsystem searches the historical corporate database to satisfy two vital business objectives:

1. **Semantic Similarity & Duplicate Suggestion Detection:** Identifying prior suggestions that addressed the same operational problem or proposed the exact same engineering, software, or organizational fix to prevent double-spending and redundant committee deliberations.
2. **Precedent & Evaluation Mining:** Surfacing historical committee reviews, rejections, legal obstacles, and budget objections for similar suggestions to supply decision-support context to evaluators and downstream generation models.

### 1.1 The Corpus Distribution Challenge (Precedent Starvation)

The historical organizational corpus possesses a severe class imbalance:

- **80% to 90%** of all historical suggestions are **`REJECTED`** ("رد") or **`NOT_ACCEPTED`** ("عدم پذیرش").
- Only **~10%** are **`APPROVED`** ("مصوب") or **`EXECUTED`** ("اجرا شده") (successful initiatives).
- Only **~2% to 5%** are **`PENDING`** ("در حال اجرا") (initiatives currently underway in the company).

In naive single-query semantic search, popular recurring complaints (e.g., HVAC or billing complaints submitted and rejected 40 times over a decade) flood the unconstrained top-$K$ vector hits. As a direct consequence, the rare positive precedents (`EXECUTED`, `APPROVED`) and ongoing projects (`PENDING`) are crowded out of the candidate pool before cross-encoder reranking can ever evaluate them. This failure mode is termed **Precedent Starvation**.

### 1.2 The Field-Dilution Challenge

An employee suggestion is a structured domain entity comprising discrete semantic sections:

- **Title (`TITLE`):** Thematic summary and organizational anchoring.
- **Problem (`PROBLEM`):** Symptom, operational bottleneck, or defect description.
- **Solution (`SOLUTION`):** Engineering fix, methodology, or software mechanism.
- **Evaluation (`EVALUATION`):** Historical committee commentary, technical critique, and resolution.

Concatenating these sections into a single flat document averages disparate semantic spaces into a single vector, causing **Semantic Vector Dilution** and false negatives during duplicate detection. To preserve strict field boundaries, the system indexes suggestions using a **Parent-Child Chunking Architecture** (ADR-002), generating discrete child chunks in Qdrant while maintaining the master entity in PostgreSQL.

---

## 2. End-to-End Pipeline Architecture

The pipeline spans eight sequential stages, transitioning from raw user input to a fully hydrated, deduplicated, and ranked candidate set:

```text
Incoming Request: POST /api/v1/suggestions/analyze
(AnalyzeSuggestionRequest: title, currentProblem, solution, contextTitle)
                                  │
                                  ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │ Stage 1: Domain Invariant Validation & Asynchronous Persian Text Normalization          │
 │ - SuggestionContent invariant checks (min_len >= 5, noise string rejection)             │
 │ - Offload CPU-bound character cleaning, ZWNJ, and digit normalization to worker thread  │
 └─────────────────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │ Stage 2: Field-Isolated Query Synthesis & Multi-Field Hybrid Embedding                  │
 │ - Title Query:    "حوزه: {norm_context} | عنوان: {norm_title}"                          │
 │ - Problem Query:  "{norm_problem}"                                                      │
 │ - Solution Query: "{norm_solution}"                                                     │
 │ - Concurrently compute Dense (768d) + Sparse BM25 via IHybridEmbeddingService           │
 └─────────────────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │ Stage 3: Tri-Track Hybrid Qdrant Retrieval (5 Concurrent Queries via asyncio.gather)    │
 │                                                                                         │
 │ ── TRACK 1: Global Semantic Recall (Unconstrained by Status) ────────────────────────── │
 │    ├─ Solution Query ──> search_suggestions(chunk_types=[SOLUTION], limit=40)           │
 │    ├─ Problem Query  ──> search_suggestions(chunk_types=[PROBLEM],  limit=25)           │
 │    └─ Title Query    ──> search_suggestions(chunk_types=[TITLE],    limit=15)           │
 │                                                                                         │
 │ ── TRACK 2: Protected Positive Precedent Probe (Mathematical Guarantee) ────────────── │
 │    └─ Solution Query ──> search_suggestions(chunk_types=[SOLUTION],                     │
 │                                             statuses=[EXECUTED, APPROVED],              │
 │                                             limit=15)                                   │
 │                                                                                         │
 │ ── TRACK 3: Protected Pending Precedent Probe (Ongoing Work Protection) ─────────────── │
 │    └─ Solution Query ──> search_suggestions(chunk_types=[SOLUTION],                     │
 │                                             statuses=[PENDING],                         │
 │                                             limit=10)                                   │
 └─────────────────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │ Stage 4: Candidate In-Memory Registry & Monotonic Ranking                               │
 │ - Deduplicate chunks across tracks by chunk_id into in-memory dictionary                │
 │ - Preserve maximum initial RRF retrieval score on collision: max(existing, new)         │
 │ - Format candidates with semantic role prefixes ("راهکار پیشنهادی: {content}", etc.)    │
 │ - Sort unique candidates by retrieval score descending; assign monotonic rank 1..N      │
 └─────────────────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │ Stage 5: Cross-Encoder Reranking via IReranker (BAAI/bge-reranker-v2-m3)                │
 │ - Query: Full suggestion context ("{title}\nمسئله: {problem}\nراهکار: {solution}")       │
 │ - Documents: Formatted child chunks (~60 to 85 unique passages)                         │
 │ - Execute sub-batches (size 32) under concurrency semaphore (max 4) with 3s timeout     │
 │ - Fault-Tolerant Fallback: Transient 5xx/network errors switch to RRF scores gracefully │
 └─────────────────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │ Stage 6: Max-Passage (MaxP) Pooling & Status Partitioning                               │
 │ - Group chunks by parent suggestion ID (suggestion_id = chunk.parent_id)                │
 │ - Suggestion_Score(S) = MAX_{c in Chunks(S)} Score(c)                                   │
 │ - Threshold Gate: Filter candidates where score < min_score_threshold (default: 0.0)    │
 │   (AUTOMATICALLY BYPASS threshold when operating in degraded RRF fallback mode)         │
 │ - Partition candidates into 5 discrete status buckets; slice Top N (default: 3) each    │
 └─────────────────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │ Stage 7: PostgreSQL Master Entity Hydration & Order Reconstruction                      │
 │ - Collect up to 15 winning suggestion IDs across all 5 partitions                       │
 │ - Single SQL batch query: SELECT * FROM suggestions WHERE id IN (...) AND is_deleted=F  │
 │ - Build valid_active_ids lookup set; eliminate soft-deleted and purged suggestions      │
 │ - Reconstruct and preserve descending score order for each partition                    │
 └─────────────────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │ Stage 8: Generation & Response Assembly                                                 │
 │ - Injected generator → sections/context → chat LLM → retained-citation parser            │
 │ - analysis = generation_result.answer; applied_statute_ids = []                          │
 │ - Return parsed answer, cited IDs, uncertainty, and coverage metadata                   │
 └─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Detailed Stage-by-Stage Specification

### Stage 1: Domain Invariant Validation & Text Normalization

Before any vector math or database calls occur, the incoming payload is subjected to strict domain boundary enforcement:

1. **Domain Validation (`SuggestionContent`):**
   The application instantiates `SuggestionContent(title=dto.title, problem=dto.problem, solution=dto.solution)` from `src.domain.entities`. This enforces:
   - Field non-emptiness.
   - Minimum substantive length ($\ge 5$ characters per field).
   - Rejection of organizational placeholder noise strings defined in `NOISE_PLACEHOLDERS`:
     `{"-", "--", "---", ".", "..", "...", "ندارد", "بدون شرح", "هیچ", "ثبت نشده", "موردی ندارد", "عدم وجود"}`.
     Violations immediately halt execution with a domain `InvalidSuggestionContentError`, returned as an HTTP 422 Unprocessable Content response.

2. **Asynchronous Text Normalization (`ITextNormalizer`):**
   Persian text processing is CPU-bound. To prevent blocking the main FastAPI asynchronous event loop, normalization calls `normalizer.normalize_batch_async()` (or `normalize_async()`), offloading execution to `asyncio.to_thread`.
   - Standardizes Arabic characters to Persian equivalents (`ي` $\rightarrow$ `ی`, `ك` $\rightarrow$ `ک`).
   - Normalizes Zero-Width Non-Joiners (ZWNJ / نیم‌فاصله) around prefixes and suffixes (`می‌شود`, `پیشنهاد‌ها`).
   - Standardizes Persian and Eastern Arabic numerals to standard Arabic-Indic or ASCII forms.
   - Strips redundant whitespaces and non-printable control characters.

---

### Stage 2: Field-Aware Query Synthesis & Hybrid Embedding

To eliminate vector averaging, the system constructs three isolated search queries:

```text
1. Title Query:    "حوزه: {norm_context} | عنوان: {norm_title}"  (or "عنوان: {norm_title}")
2. Problem Query:  "{norm_problem}"
3. Solution Query: "{norm_solution}"
```

#### Why Field Isolation is Necessary

- A suggestion's defect description (`PROBLEM`) operates in the vocabulary of operational failure, machine breakdown, or bureaucratic delays.
- A suggestion's mechanism (`SOLUTION`) operates in the vocabulary of electrical engineering, chemical compounds, SCADA configuration, or software algorithms.
- Mixing them produces an averaged point in 768-dimensional space that fails to match historical documents that shared the identical technical solution under a slightly different symptom.

#### Concurrent Hybrid Embeddings

The usecase invokes `IHybridEmbeddingService.embed_query()` across all three queries concurrently via `asyncio.gather()`:

```python
title_emb, problem_emb, solution_emb = await asyncio.gather(
    self._embedding_service.embed_query(title_query),
    self._embedding_service.embed_query(problem_query),
    self._embedding_service.embed_query(solution_query),
)
```

Each call generates:

- **Dense Vector:** 768-dimensional float embedding using `google/embedding-gemma-2b` prepended with the task-specific instruction prefix.
- **Sparse Vector:** Lexical term-weight mapping generated by the Persian BM25 engine (`indices: list[int]`, `values: list[float]`).

---

### Stage 3: Tri-Track Hybrid Vector Retrieval in Qdrant

Rather than executing a naive query across the entire collection or launching 15 separate queries for every possible status-field permutation, the pipeline launches **exactly five concurrent queries** organized into three strategic tracks:

```text
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │ TRACK 1: Global Semantic Recall (3 Queries, statuses=None)                             │
 │  - Solution Query ──> Qdrant (chunk_types=[SOLUTION], limit=40)                        │
 │  - Problem Query  ──> Qdrant (chunk_types=[PROBLEM],  limit=25)                        │
 │  - Title Query    ──> Qdrant (chunk_types=[TITLE],    limit=15)                        │
 ├────────────────────────────────────────────────────────────────────────────────────────┤
 │ TRACK 2: Protected Positive Precedent Probe (1 Query, statuses=[EXECUTED, APPROVED])   │
 │  - Solution Query ──> Qdrant (chunk_types=[SOLUTION], limit=15)                        │
 ├────────────────────────────────────────────────────────────────────────────────────────┤
 │ TRACK 3: Protected Pending Precedent Probe (1 Query, statuses=[PENDING])               │
 │  - Solution Query ──> Qdrant (chunk_types=[SOLUTION], limit=10)                        │
 └────────────────────────────────────────────────────────────────────────────────────────┘
```

#### Detailed Track Objectives

1. **Track 1 (Global Semantic Recall):**
   Operates without any status filters (`statuses=None`). It allows the true semantic neighborhood to surface naturally. Because 85% of the database is rejected suggestions, Track 1 naturally captures historical rejections, recurring failures, and dense unconstrained clusters.
2. **Track 2 (Protected Positive Precedent Probe):**
   Restricts Qdrant retrieval strictly to `statuses=[SuggestionStatus.EXECUTED, SuggestionStatus.APPROVED]` against child chunks of type `SOLUTION` (`limit=15`). This guarantees that regardless of how many hundreds of rejected suggestions flood Track 1, the top 15 most similar _implemented solutions_ in company history are guaranteed a seat in the candidate registry.
3. **Track 3 (Protected Pending Precedent Probe):**
   Restricts retrieval strictly to `statuses=[SuggestionStatus.PENDING]` against `SOLUTION` chunks (`limit=10`). Suggestions in "در حال اجرا" status represent active corporate projects. Finding these is critical to prevent duplicate departmental initiatives and redundant resource allocation.

All five queries execute in parallel over Qdrant using Reciprocal Rank Fusion (RRF) combining dense and sparse vectors:

```python
t1_sol, t1_prob, t1_title, t2_pos, t3_pend = await asyncio.gather(
    track1_solution_query,
    track1_problem_query,
    track1_title_query,
    track2_positive_query,
    track3_pending_query,
)
```

---

### Stage 4: Candidate In-Memory Registry & Monotonic Ranking

When five parallel queries finish, the raw result sets total between **80 and 105 child chunks**. Duplicates will naturally exist across tracks (e.g., an `EXECUTED` solution returned by both Track 1 and Track 2).

#### Deduplication Logic

The usecase maintains an in-memory dictionary keyed by `chunk_id`:

```python
chunk_registry: dict[str, SuggestionSearchResult] = {}

for hit_list in (t1_sol, t1_prob, t1_title, t2_pos, t3_pend):
    for hit in hit_list:
        cid = hit.chunk.chunk_id
        if cid not in chunk_registry:
            chunk_registry[cid] = hit
        else:
            # Preserve the stronger retrieval signal
            if hit.score > chunk_registry[cid].score:
                chunk_registry[cid] = hit
```

If a chunk appears in multiple tracks, the system retains the hit with the **maximum initial RRF retrieval score**, ensuring that a high-ranking probe result is not overwritten by a lower-ranking unconstrained result.

#### Semantic Role Prefixing

Cross-encoders benefit from explicit semantic anchoring. Before scoring, candidate passage text is formatted with canonical Persian role markers:

```python
_ROLE_PREFIX_MAP: Final[dict[SuggestionChunkType, str]] = {
    SuggestionChunkType.SOLUTION: "راهکار پیشنهادی: ",
    SuggestionChunkType.PROBLEM: "مسئله و چالش: ",
    SuggestionChunkType.TITLE: "عنوان: ",
    SuggestionChunkType.EVALUATION: "بررسی کمیته: ",
}

formatted_text = f"{_ROLE_PREFIX_MAP[chunk.metadata.chunk_type]}{chunk.content}"
```

#### Global Monotonic Ranking

The deduplicated candidates (~60 to 85 unique chunks) are sorted descending by their initial Qdrant RRF retrieval scores. Monotonic integer ranks ($1 \dots N$) are assigned to every candidate. These monotonic ranks act as deterministic tie-breakers during cross-encoder scoring.

---

### Stage 5: Cross-Encoder Reranking (`BAAI/bge-reranker-v2-m3`)

While bi-encoders compress text into isolated vectors, a cross-encoder performs full cross-attention over all token pairs between the query and candidate passage:

$$\text{Logit} = \text{CrossEncoder}(Q, P)$$

#### Context Formulation

- **Reranker Query ($Q$):** Full suggestion specification:
  ```text
  {title_query}
  مسئله: {norm_problem}
  راهکار: {norm_solution}
  ```
- **Candidate Passage ($P$):** Role-prefixed child chunk text:
  ```text
  راهکار پیشنهادی: نصب حسگرهای حرارتی مادون قرمز روی اتصالات ترانسفورماتور
  ```

#### Infrastructure & Execution Parameters

- **Client & Sub-Batching:** `TEIReranker` partitions candidates into client sub-batches of 32 (`RERANKER_CLIENT_BATCH_SIZE`) to prevent HTTP timeout issues on long context pairs.
- **Concurrency Limiter:** Invocations pass through a shared `asyncio.Semaphore(value=4)` to protect the GPU from out-of-memory errors under high concurrent API load.
- **SLA Timeouts:** 1.0 second connect timeout, 3.0 second read timeout.

#### Resilient Degraded Fallback Mode

If TEI experiences transient outages, GPU saturation, 5xx server errors, or transport timeouts (`RerankerConnectionError`, `RerankerOverloadedError`, `RerankerAPIError`), **the pipeline does not crash**.

Instead, it logs a structured warning and activates **Graceful Fallback Mode**:

- `is_fallback_mode = True`
- Reranking scores fall back to the initial Qdrant RRF scores ($0.01 - 0.05$).
- Execution continues smoothly to Max-Passage pooling.
- _Precondition validation errors (`RerankerValidationError`) are never swallowed and fail fast._

---

### Stage 6: Max-Passage (MaxP) Pooling & Status Slicing

After reranking, candidates exist at the **child chunk level**. However, the organizational user and committee require evaluations at the **parent suggestion level**.

This translation is handled by the pure application function `pool_and_partition_candidates()` in `src.application.services.max_passage_pooler`.

```text
Child Chunks for Parent 'SUG-101':
  ├─ PROBLEM Chunk   ──> Rerank Score: -1.20
  ├─ TITLE Chunk     ──> Rerank Score:  0.45
  └─ SOLUTION Chunk  ──> Rerank Score:  3.80 (Winning Chunk!)
                                  │
                                  ▼
      Max-Passage Pooling: Score(SUG-101) = max(-1.20, 0.45, 3.80) = 3.80
```

#### The Pooling Algorithm

1. **Parent Grouping:** Group all scored chunks by `parent_id = chunk.parent_id`.
2. **Winning Passage Selection:** For each parent suggestion $S$:
   $$\text{winning\_score}(S) = \max_{c \in \text{Chunks}(S)} \text{Score}(c)$$
   The function identifies the `winning_chunk_id`, `winning_chunk_type`, and `winning_content`, while aggregating all distinct matched chunk types into `all_matched_chunk_types`.
3. **Fallback-Aware Threshold Gating:**
   - **Normal Mode (`is_fallback_mode = False`):** Cross-encoder outputs are raw logits (typically $-10.0$ to $+10.0$). A candidate is discarded if:
     $$\text{winning\_score} < \text{min\_score\_threshold} \quad (\text{default: } 0.0)$$
   - **Degraded Fallback Mode (`is_fallback_mode = True`):** RRF scores are small fractions ($0.01 - 0.05$). Enforcing a $0.0$ or positive logit threshold against RRF scores would drop all candidates. Therefore, **the threshold is automatically bypassed** during fallback mode, ensuring that the best retrieved candidates are preserved.
4. **Status Partition Slicing:**
   The pooled candidates are bucketed by their domain status (`SuggestionStatus`). Within each bucket, candidates are sorted strictly descending by `winning_score`.
   The system slices the **Top $N$** (default: 3) winning candidates per bucket:
   - `EXECUTED`: Top 3
   - `APPROVED`: Top 3
   - `PENDING`: Top 3
   - `REJECTED`: Top 3
   - `NOT_ACCEPTED`: Top 3

**Output Boundaries:**

- **Maximum Output:** 15 suggestions ($5 \text{ partitions} \times 3$).
- **Minimum Output:** 0 suggestions (if zero vector matches or all candidates score below threshold).

---

### Stage 7: PostgreSQL Master Entity Hydration & Order Reconstruction

At this stage, the pipeline holds up to 15 winning suggestion candidates. However, Qdrant child points only store partial text payloads. To verify transactional consistency and prepare complete context, the master entities must be hydrated from PostgreSQL.

#### The Problem: SQL Order Scrambling

When executing an SQL batch query:

```sql
SELECT * FROM suggestions
WHERE id IN ('sug-10', 'sug-42', 'sug-05')
  AND is_deleted = false;
```

Relational databases treat tables as unordered sets. PostgreSQL returns rows in disk-heap or index-scan order (e.g. `'sug-05'`, `'sug-10'`, `'sug-42'`), completely scrambling the reranked score order.

#### The Solution: In-Memory Order Reconstruction

PostgreSQL is treated strictly as an **existence and liveness verification gate**:

```python
# 1. Collect all winning IDs across all partitions
all_winning_ids = [c.suggestion_id for c in all_winning_candidates]

# 2. Query PostgreSQL (single round-trip batch lookup)
async with self._uow as uow:
    hydrated_suggestions = await uow.suggestions.get_by_ids(
        all_winning_ids, include_deleted=False
    )

# 3. Build fast lookup set (O(1) lookups)
valid_active_ids = {s.id for s in hydrated_suggestions}

# 4. Reconstruct descending score order for each partition
for status, candidate_list in partition_map.items():
    ordered_survivors = [
        cand.suggestion_id for cand in candidate_list
        if cand.suggestion_id in valid_active_ids
    ]
    # Assign to corresponding response list

```

#### What This Solves:

1. **Soft-Deleted & Purged Records:** Any suggestion marked `is_deleted = true` in PostgreSQL is omitted from `valid_active_ids` and dropped instantly.
2. **Order Preservation:** The original descending score order established by the cross-encoder is strictly preserved.
3. **Database Performance:** PostgreSQL executes only a single indexed query looking up $\le 15$ primary keys ($< 5\text{ms}$ database execution time).

---

### Stage 8: Generation & Response Assembly

After already-prepared evidence is available, `AnalyzeSuggestionUseCase` builds `GenerationInput` and awaits its injected `IGenerateSuggestionUseCase`. The container supplies `GenerateSuggestionUseCase`, which runs `SuggestionPromptPreparer.prepare_with_citations → PromptBuilder/ContextBuilder → LLMRequestBuilder → ILLMClient.complete_chat → GenerationOutputParser` under the configured prompt budget.

The parser resolves model-selected short IDs only against the retained fitted citation map, returning the original cited objects. The use case maps the answer and uncertainty into the response, deduplicates cited original suggestion IDs in first-seen order, and restricts them to the active pool. Existing candidate lists remain separate from model-selected citations.

```python
return AnalyzeSuggestionResponse(
    analysis=generation_result.answer,
    similar_executed_ids=similar_executed_ids,
    similar_approved_ids=similar_approved_ids,
    similar_pending_ids=similar_pending_ids,
    similar_rejected_ids=similar_rejected_ids,
    similar_not_accepted_ids=similar_not_accepted_ids,
    applied_statute_ids=[],
    uncertainty=generation_result.uncertainty,
    cited_suggestion_ids=cited_ids,
    is_fallback_mode=is_fallback_mode,
    grounding_ratio=grounding_ratio,
)
```

`grounding_ratio` is unique cited active suggestions divided by all active suggestions, rounded to two decimals and bounded to [0, 1]; it is a coverage proxy, not calibrated model confidence. The existing no-hits/no-active-evidence guard still returns diagnostic analysis and uncertainty, empty lists, and grounding zero without Generation. Regulation rendering/citations remain missing. See the [Generation guide](../documentation/llm_generation_api.md) for the implemented downstream contract; retrieval behavior above is unchanged.

## 4. Failure Modes & Resilience Matrix

| Failure Mode                     | Trigger / Cause                                                                  | System Behavior & Mitigation                                                                                                                 |
| :------------------------------- | :------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------- |
| **Invalid Input Data**           | Title, problem, or solution $< 5$ chars or contains noise strings (`"ندارد"`).   | Halts at Stage 1. Raises `InvalidSuggestionContentError`; returns HTTP 422 with pointer `/data/{field}`.                                     |
| **Zero Qdrant Hits**             | Novel vocabulary or cold database.                                               | All 5 queries return `[]`. Pipeline short-circuits: skips reranker, SQL hydration, prompt preparation, and LLM invocation; returns an empty result in HTTP 200.             |
| **Qdrant Outage / Network Drop** | Qdrant gRPC/HTTP unreachable.                                                    | Fails fast. Raises `VectorSearchError`; caught by presentation exception handler; returns HTTP 503 Service Unavailable.                      |
| **Reranker Overload (HTTP 429)** | High concurrent evaluation volume.                                               | Caught by `TEIReranker` retry policy with exponential jitter. If exhausted, activates degraded fallback mode.                                |
| **Reranker 5xx / Timeout**       | TEI container crash, CUDA OOM, or $>3$s read timeout.                            | Activates Degraded Fallback Mode: falls back to Qdrant RRF scores (`is_fallback_mode = True`), logs warning, and completes pipeline.         |
| **Scale Mismatch in Fallback**   | Fallback RRF scores ($0.02$) evaluated against positive logit threshold ($0.0$). | `pool_and_partition_candidates` detects `is_fallback_mode = True` and automatically bypasses threshold gating to avoid candidate starvation. |
| **PostgreSQL Record Deleted**    | Suggestion soft-deleted in SQL, but lingering in vector cache.                   | Stage 7 query returns `is_deleted = false` only. ID is absent from `valid_active_ids` and dropped silently from output.                      |
| **SQL Result Scrambling**        | PostgreSQL `WHERE id IN (...)` returns rows in arbitrary disk order.             | Stage 7 in-memory set reconstruction re-sorts IDs strictly matching cross-encoder descending score order.                                    |

---

## 5. Clean Architecture & SOLID Compliance

```text
 ┌────────────────────────────────────────────────────────────────────────┐
 │ Presentation Layer                                                     │
 │ - AnalyzeSuggestionRequest (camelCase wire contract, currentProblem)   │
 │ - suggestion.py router (POST /api/v1/suggestions/analyze)              │
 └───────────────────────────────────┬────────────────────────────────────┘
                                     │ DTO mapping
                                     ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │ Application Layer                                                      │
 │ - AnalyzeSuggestionUseCase (Orchestrator)                              │
 │ - pool_and_partition_candidates (Pure Function: MaxP, Threshold, Slice)│
 │ - Ports: ITextNormalizer, IHybridEmbeddingService, IReranker, UoW      │
 └───────────────────────────────────┬────────────────────────────────────┘
                                     │ Port satisfaction
                                     ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │ Domain Layer                                                           │
 │ - SuggestionContent (Invariant rules, NOISE_PLACEHOLDERS)              │
 │ - Entities: Suggestion, Chunk, QueryEmbedding, SuggestionStatus        │
 │ - Port: ISuggestionVectorRepository                                    │
 └───────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │ Infrastructure Layer                                                   │
 │ - QdrantSuggestionRepository, TEIReranker, ShekarTextNormalizer        │
 │ - SqlUnitOfWork, SqlSuggestionRepository                               │
 │ - SuggestionAnalysisSettings (Centralized configuration in settings.py)│
 └────────────────────────────────────────────────────────────────────────┘
```

1. **Single Responsibility Principle (SRP):**
   `AnalyzeSuggestionUseCase` orchestrates the workflow. All mathematical Max-Passage pooling and partition slicing are delegated to the pure, isolated function `pool_and_partition_candidates`.
2. **Dependency Inversion Principle (DIP):**
   The application use case depends strictly on abstract interfaces (`ITextNormalizer`, `IHybridEmbeddingService`, `ISuggestionVectorRepository`, `IReranker`, `IUnitOfWork`). No concrete infrastructure classes are imported into application logic.
3. **Clean Code & Immutability:**
   `PooledSuggestionCandidate` is defined with `@dataclass(frozen=True)` and uses immutable `tuple[SuggestionChunkType, ...]` for matched chunks. All magic numbers are eliminated and managed via `SuggestionAnalysisSettings`.

---

## 6. Configuration Reference (`SuggestionAnalysisSettings`)

All runtime limits and thresholds are defined in `src.infrastructure.configs.settings`:

| Setting Key                                | Default | Description                                                                        |
| :----------------------------------------- | :-----: | :--------------------------------------------------------------------------------- |
| `SUGGESTION_ANALYSIS_SOLUTION_LIMIT`       |  `40`   | Track 1 unconstrained `SOLUTION` chunk limit in Qdrant.                            |
| `SUGGESTION_ANALYSIS_PROBLEM_LIMIT`        |  `25`   | Track 1 unconstrained `PROBLEM` chunk limit in Qdrant.                             |
| `SUGGESTION_ANALYSIS_TITLE_LIMIT`          |  `15`   | Track 1 unconstrained `TITLE` chunk limit in Qdrant.                               |
| `SUGGESTION_ANALYSIS_POSITIVE_PROBE_LIMIT` |  `15`   | Track 2 protected `SOLUTION` probe limit for `[EXECUTED, APPROVED]`.               |
| `SUGGESTION_ANALYSIS_PENDING_PROBE_LIMIT`  |  `10`   | Track 3 protected `SOLUTION` probe limit for `[PENDING]`.                          |
| `SUGGESTION_ANALYSIS_TOP_N_PER_STATUS`     |   `3`   | Maximum winning suggestions sliced per status partition after MaxP pooling.        |
| `SUGGESTION_ANALYSIS_MIN_SCORE_THRESHOLD`  |  `0.0`  | Minimum cross-encoder logit score required to qualify (bypassed in fallback mode). |

---

## 7. Verification Boundary

The source tests under `tests/unit/application/services/test_max_passage_pooler.py` and `tests/unit/application/use_cases/test_analyze_suggestion_use_case.py` cover pooling and use-case orchestration with test doubles. `tests/integration/presentation/test_suggestion_analysis_api.py` checks the HTTP contract with the use case overridden. These tests do not prove an API-originated vLLM request.

`tests/integration/context_builder_vllm/` exercises the lower-level prompt/context/request/client chain, including a real local vLLM completion, but bypasses the production analysis route and output parser. The [Generation API test summary](../documentation/llm_generation_test_summary.md) records what passed, failed, or remains blocked. The expansion HTTP tests separately exercise `API → real Generation use case/context → mocked provider → parser → response`, without production lifespan. Analyze unit tests verify its generator handoff; its presentation tests still override the use case. Live endpoint-to-provider validation remains open for both routes; see the current working-tree expansion marker caveat in the Generation guide.
