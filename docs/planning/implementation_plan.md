# Implementation Plan: Suggestion Analysis Use Case (Hybrid Dual-Track Retrieval, Cross-Encoder Reranking & Hydration)

This plan details the implementation of the **Suggestion Analysis Workflow** in [tavanir-ai-assistant-v2](file:///d:/Jco_Projects/tavanir-ai-assistant-v2). It introduces the **Hybrid Dual-Track Retrieval Architecture** to combine high-recall semantic clustering with mathematical protection against majority-class precedent starvation.

The pipeline spans input invariant validation, Persian text normalization, field-isolated query embedding, dual-track hybrid vector retrieval in Qdrant, unified candidate registry formatting, cross-encoder reranking via TEI (`BAAI/bge-reranker-v2-m3`), Max-Passage (MaxP) pooling, and single-query PostgreSQL master entity hydration.

All prompt construction, prompt engineering, and LLM generation logic are strictly excluded from this scope and deferred to the LLM generation service developer, with clear placeholder handoff points left in place.

---

## Architectural Decisions & ADR Update Note

> [!IMPORTANT]
> **Action Item: Update `docs/adr/002-suggestion-chunking-strategy.md`**:
> A subsequent documentation task must be filed to update [ADR-002](file:///d:/Jco_Projects/tavanir-ai-assistant-v2/docs/adr/002-suggestion-chunking-strategy.md) to record the transition from naive 5-status partitioned queries to the **Hybrid Dual-Track Retrieval Strategy**. This formally documents why status filtering was removed from primary semantic retrieval (to allow natural clustering for statuses like `PENDING`) and replaced with a dedicated positive precedent probe (to prevent majority `REJECTED` suggestions from drowning out `EXECUTED` precedents).

> [!NOTE]
> **Summary of Finalized Decisions**:
> 1. **Hybrid Dual-Track Retrieval (Option B)**:
>    - **Track 1 (Global Semantic Recall)**: 3 unconstrained queries (`SOLUTION` limit=40, `PROBLEM` limit=25, `TITLE` limit=15) with **no status filter**. Allows natural semantic clusters (such as dense `PENDING` suggestions) to enter the candidate pool without artificial status truncation.
>    - **Track 2 (Protected Positive Precedent Probe)**: 1 targeted query (`SOLUTION` limit=15) strictly for `statuses=[EXECUTED, APPROVED]`. Guarantees that historical implemented solutions are never crowded out by the massive volume of rejected suggestions (80–90% of corpus).
>    - Reduces total Qdrant queries from **15 down to 4 concurrent queries**.
> 2. **Field-Isolated Query Embeddings**:
>    `solution`, `problem`, and `title` are embedded as independent queries to eliminate vector dilution and BM25 keyword pollution.
> 3. **Canonical HTTP Route**:
>    Officially set to `POST /api/v1/suggestions/analyze`, mounted on `master_router_v1` under `/api/v1/suggestions`.
> 4. **Reranker Negative Logit Thresholding**:
>    A configurable threshold `min_score_threshold: float | None = 0.0` is enforced during MaxP pooling to drop irrelevant candidates.

---

## Architectural Data Flow

```text
Incoming Request: AnalyzeSuggestionDTO (title, problem, solution, context_title)
                                  │
                                  ▼
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │ Step 1: Input Invariant Validation & Persian Text Normalization                  │
 │ - Validate SuggestionContent invariants (min_len=5, not in NOISE_PLACEHOLDERS)   │
 │ - Normalize Persian characters, ZWNJ, numbers via ShekarTextNormalizer           │
 └──────────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │ Step 2: Field-Aware Query Synthesis & Multi-Field Hybrid Embedding               │
 │ - Title Query:   "حوزه: {context} | عنوان: {title}" (or "عنوان: {title}")        │
 │ - Problem Query: "{norm_problem}" (pure defect text)                             │
 │ - Solution Query:"{norm_solution}" (pure engineering mechanism)                  │
 │ - Concurrently compute Dense (768d) + Sparse BM25 for each field via gather()    │
 │ - Yields: title_embedding, problem_embedding, solution_embedding                │
 └──────────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │ Step 3: Hybrid Dual-Track Qdrant Search (4 Concurrent Queries via gather)       │
 │                                                                                  │
 │ ── TRACK 1: Global Semantic Recall (Unconstrained by Status) ────────────────── │
 │    ├─ Solution Query ──> search_suggestions(chunk_types=[SOLUTION], limit=40)    │
 │    ├─ Problem Query  ──> search_suggestions(chunk_types=[PROBLEM],  limit=25)    │
 │    └─ Title Query    ──> search_suggestions(chunk_types=[TITLE],    limit=15)    │
 │                                                                                  │
 │ ── TRACK 2: Protected Positive Precedent Probe (Guaranteed Protection) ──────── │
 │    └─ Solution Query ──> search_suggestions(chunk_types=[SOLUTION],              │
 │                                             statuses=[EXECUTED, APPROVED],       │
 │                                             limit=15)                            │
 │                                                                                  │
 │ - Total 4 queries in parallel; drops network overhead by ~75%                   │
 │ - Unified In-Memory Registry: chunk_id -> SuggestionSearchResult (deduplicated)  │
 └──────────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │ Step 4: Chunk Preparation, Role-Prefix Formatting & Global Rank Normalization    │
 │ - Format: "[chunk_type]: content" (e.g., "راهکار پیشنهادی: {text}")               │
 │ - Sort all unique candidate chunks globally by initial RRF score descending      │
 │ - Assign monotonic global retrieval_rank (1..N) to prevent tie-break collisions │
 └──────────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │ Step 5: Cross-Encoder Reranking via TEI (BAAI/bge-reranker-v2-m3)                │
 │ - Query: Full suggestion context ("{title_query}\nمسئله: {problem}\nراهکار: {sol}")│
 │ - Candidates: Formatted candidate chunks (~70-90 unique chunks)                  │
 │ - Resilient fallback: transient network/5xx errors fallback to RRF ranks         │
 │ - Returns RerankedCandidate list sorted by raw cross-encoder logits descending   │
 └──────────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │ Step 6: Max-Passage Pooling (MaxP), Status Slicing & Threshold Guard             │
 │ - Group chunks by (status, parent_id) using payload status metadata              │
 │ - Suggestion_Score(S) = MAX_{c in Chunks(S)} RerankScore(c)                     │
 │ - Track winning_chunk_id, winning_chunk_type, winning_score                      │
 │ - Filter out suggestions where winning_score < min_score_threshold (default: 0.0)│
 │ - Slice Top N (default: 3) winning suggestions per status partition              │
 └──────────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │ Step 7: PostgreSQL Master Entity Hydration                                       │
 │ - Collect unique winning suggestion IDs across all partitions                    │
 │ - Single SQL batch query: SELECT * FROM suggestions WHERE id IN (...)            │
 │ - Drop soft-deleted or missing records; preserve ranking order                   │
 └──────────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │ Step 8: Structured Response Assembly & Deferred Section Placeholders             │
 │ - [PLACEHOLDER 1: Statutes Retrieval] -> empty applied_statute_ids = []          │
 │ - [PLACEHOLDER 2: Generation Handoff] -> diagnostic placeholder for LLM report   │
 │ - Assemble and return AnalyzeSuggestionResponse                                  │
 └──────────────────────────────────────────────────────────────────────────────────┘
```

---

## Proposed Changes

### Application Layer (`src/application`)

#### [MODIFY] [dtos.py](file:///d:/Jco_Projects/tavanir-ai-assistant-v2/src/application/dtos.py)
* Add `AnalyzeSuggestionDTO`:
  ```python
  @dataclass(frozen=True)
  class AnalyzeSuggestionDTO:
      title: str
      problem: str
      solution: str
      context_title: str | None = None
  ```
* Add `PooledSuggestionCandidate`:
  ```python
  @dataclass(frozen=True)
  class PooledSuggestionCandidate:
      suggestion_id: str
      status: SuggestionStatus
      winning_chunk_id: str
      winning_chunk_type: SuggestionChunkType
      winning_score: float
      winning_content: str
      all_matched_chunk_types: tuple[SuggestionChunkType, ...]
  ```
* Register both in `__all__`.

#### [NEW] [analyze_suggestion_use_case.py](file:///d:/Jco_Projects/tavanir-ai-assistant-v2/src/application/use_cases/analyze_suggestion_use_case.py)
* Implement `AnalyzeSuggestionUseCase`:
  * **Dependencies**: `ITextNormalizer`, `IHybridEmbeddingService`, `ISuggestionVectorRepository`, `IReranker`, `IUnitOfWork`.
  * **Config**:
    * `solution_global_limit: int = 40`
    * `problem_global_limit: int = 25`
    * `title_global_limit: int = 15`
    * `positive_probe_limit: int = 15`
    * `top_n_per_status: int = 3`
    * `min_score_threshold: float | None = 0.0`
  * **Logic**:
    1. **Validation**: Validate domain invariants via [SuggestionContent](file:///d:/Jco_Projects/tavanir-ai-assistant-v2/src/domain/entities.py#L65-L97).
    2. **Normalization**: Normalize Persian text for each field with [ShekarTextNormalizer](file:///d:/Jco_Projects/tavanir-ai-assistant-v2/src/infrastructure/services/text_processing/shekar_text_normalizer.py).
    3. **Field Query Synthesis**:
       * `title_query`: `f"حوزه: {norm_context} | عنوان: {norm_title}"` if `norm_context` else `f"عنوان: {norm_title}"`
       * `problem_query`: `norm_problem`
       * `solution_query`: `norm_solution`
    4. **Concurrent Multi-Field Hybrid Embedding**:
       ```python
       title_emb, problem_emb, solution_emb = await asyncio.gather(
           self._embedding_service.embed_query(title_query),
           self._embedding_service.embed_query(problem_query),
           self._embedding_service.embed_query(solution_query),
       )
       ```
    5. **Hybrid Dual-Track Qdrant Search**:
       Run exactly 4 queries in parallel:
       ```python
       track1_solution = self._vector_repo.search_suggestions(
           dense_vector=solution_emb.dense_vector,
           sparse_vector=solution_emb.sparse_vector,
           chunk_types=[SuggestionChunkType.SOLUTION],
           statuses=None,  # Global unconstrained
           limit=self._solution_global_limit,
       )
       track1_problem = self._vector_repo.search_suggestions(
           dense_vector=problem_emb.dense_vector,
           sparse_vector=problem_emb.sparse_vector,
           chunk_types=[SuggestionChunkType.PROBLEM],
           statuses=None,  # Global unconstrained
           limit=self._problem_global_limit,
       )
       track1_title = self._vector_repo.search_suggestions(
           dense_vector=title_emb.dense_vector,
           sparse_vector=title_emb.sparse_vector,
           chunk_types=[SuggestionChunkType.TITLE],
           statuses=None,  # Global unconstrained
           limit=self._title_global_limit,
       )
       track2_positive = self._vector_repo.search_suggestions(
           dense_vector=solution_emb.dense_vector,
           sparse_vector=solution_emb.sparse_vector,
           chunk_types=[SuggestionChunkType.SOLUTION],
           statuses=[SuggestionStatus.EXECUTED, SuggestionStatus.APPROVED],
           limit=self._positive_probe_limit,
       )

       hits_lists = await asyncio.gather(
           track1_solution, track1_problem, track1_title, track2_positive
       )
       ```
    6. **Candidate In-Memory Registry**:
       Deduplicate chunks by `chunk_id` into `chunk_registry: dict[str, SuggestionSearchResult]`.
    7. **Candidate Formatting & Global Monotonic Ranks**:
       Format role prefixes (`راهکار پیشنهادی: ...`, `مسئله و چالش: ...`), sort unique candidates globally by their initial Qdrant RRF retrieval score descending, and assign monotonic `retrieval_rank` $1 \dots N$.
    8. **Cross-Encoder Reranking**:
       * Cross-Encoder Query: Full suggestion context:
         `f"{title_query}\nمسئله: {norm_problem}\nراهکار: {norm_solution}"`
       * Call [TEIReranker](file:///d:/Jco_Projects/tavanir-ai-assistant-v2/src/infrastructure/services/reranker/tei_reranker.py) to rerank all unique candidate chunks.
       * Transient error fallback: On `(RerankerConnectionError, RerankerOverloadedError, RerankerAPIError)`, fall back to Qdrant RRF retrieval scores and log a warning. Fail fast on validation/configuration errors.
    9. **Max-Passage Pooling (MaxP)**:
       Group chunks by `(status, parent_id)` using `chunk.metadata.status`. Calculate `winning_score = max(rerank_scores)`, filter out candidates below `min_score_threshold`, and slice the top $N$ per status partition.
    10. **PostgreSQL Hydration**:
       Single batch query `uow.suggestions.get_by_ids(winning_ids, include_deleted=False)`. Discard any soft-deleted or missing records while preserving ranking order.
    11. **Placeholders**:
        * Statutes retrieval placeholder (`applied_statute_ids = []`).
        * Generation handoff placeholder documenting successful retrieval and reranking for the LLM service developer.
    12. **Return**: [AnalyzeSuggestionResponse](file:///d:/Jco_Projects/tavanir-ai-assistant-v2/src/application/dtos.py#L11-L24).

#### [MODIFY] [__init__.py](file:///d:/Jco_Projects/tavanir-ai-assistant-v2/src/application/use_cases/__init__.py)
* Export `AnalyzeSuggestionUseCase`.

---

### Infrastructure Layer (`src/infrastructure`)

#### [MODIFY] [settings.py](file:///d:/Jco_Projects/tavanir-ai-assistant-v2/src/infrastructure/configs/settings.py)
* Add configuration parameters:
  * `SUGGESTION_ANALYSIS_SOLUTION_LIMIT: int = 40`
  * `SUGGESTION_ANALYSIS_PROBLEM_LIMIT: int = 25`
  * `SUGGESTION_ANALYSIS_TITLE_LIMIT: int = 15`
  * `SUGGESTION_ANALYSIS_POSITIVE_PROBE_LIMIT: int = 15`
  * `SUGGESTION_ANALYSIS_TOP_N_PER_STATUS: int = 3`
  * `SUGGESTION_ANALYSIS_RERANK_MIN_SCORE: float | None = 0.0`

#### [MODIFY] [containers.py](file:///d:/Jco_Projects/tavanir-ai-assistant-v2/src/containers.py)
* Wire `analyze_suggestion_use_case` factory into DI:
  ```python
  analyze_suggestion_use_case: providers.Provider[AnalyzeSuggestionUseCase] = (
      providers.Factory(
          AnalyzeSuggestionUseCase,
          normalizer=text_normalizer,
          embedding_service=hybrid_embedding_service,
          vector_repo=suggestion_vector_repository,
          reranker=reranker,
          uow=unit_of_work,
          solution_global_limit=40,
          problem_global_limit=25,
          title_global_limit=15,
          positive_probe_limit=15,
          top_n_per_status=3,
          min_score_threshold=0.0,
      )
  )
  ```

---

### Presentation Layer (`src/presentation`)

#### [NEW] [analyze_suggestion_request.py](file:///d:/Jco_Projects/tavanir-ai-assistant-v2/src/presentation/schemas/v1/analyze_suggestion_request.py)
* Create Pydantic v2 request model inheriting from `BaseRequestModel`:
  * Fields: `title`, `currentProblem`, `solution`, `contextTitle`.
  * Method: `to_dto() -> AnalyzeSuggestionDTO`.

#### [NEW] [analyze_suggestion_response.py](file:///d:/Jco_Projects/tavanir-ai-assistant-v2/src/presentation/schemas/v1/analyze_suggestion_response.py)
* Create Pydantic v2 response data model inheriting from `BaseResponseModel`:
  * Fields: `analysis`, `similarExecutedIds`, `similarApprovedIds`, `similarPendingIds`, `similarRejectedIds`, `similarNotAcceptedIds`, `appliedStatuteIds`.

#### [NEW] [suggestion_analysis_router.py](file:///d:/Jco_Projects/tavanir-ai-assistant-v2/src/presentation/routers/v1/suggestion_analysis_router.py)
* Route: `POST /suggestions/analyze`
* Dependency-injects `Container.analyze_suggestion_use_case`.
* Returns `SuccessResponse[AnalyzeSuggestionResponseData]`.

#### [MODIFY] [router.py](file:///d:/Jco_Projects/tavanir-ai-assistant-v2/src/presentation/routers/router.py)
* Register `suggestion_analysis_router` on `master_router_v1`.

---

## Documentation Follow-Up

#### [MODIFY] [docs/adr/002-suggestion-chunking-strategy.md](file:///d:/Jco_Projects/tavanir-ai-assistant-v2/docs/adr/002-suggestion-chunking-strategy.md)
* Update Section 6 (Retrieval, Scoring & Reranking Pipeline) to document the **Hybrid Dual-Track Retrieval Strategy**:
  * Explain why status filtering was lifted from Track 1 (unconstrained semantic recall for natural cluster discovery like `PENDING`).
  * Document the Track 2 Positive Precedent Probe to mitigate majority-class starvation from the 80–90% rejected suggestion baseline.

---

## Verification Plan

### Automated Tests
Run pytest across all newly developed unit tests:
```powershell
pytest tests/unit/application/use_cases/test_analyze_suggestion_use_case.py -v
```

Test scenarios covered:
1. `test_execute_success_full_flow`: End-to-end execution with Dual-Track Qdrant retrieval and TEI reranking.
2. `test_dual_track_retrieval_queries`: Asserts exactly 4 queries are launched concurrently (Track 1: solution, problem, title with `statuses=None`; Track 2: solution with `statuses=[EXECUTED, APPROVED]`).
3. `test_pending_cluster_retrieval`: Verifies that a dense cluster of `PENDING` suggestions (e.g. 15 items) flows unhindered into the candidate pool without artificial status truncation.
4. `test_positive_precedent_protection`: Simulates a scenario where Track 1 is saturated with `REJECTED` suggestions, but Track 2 surfaces an `EXECUTED` suggestion that reaches the reranker and appears in `similar_executed_ids`.
5. `test_max_passage_pooling_multi_chunks`: Verifies parent suggestion takes max score across matched chunks and preserves winning chunk type and content.
6. `test_input_validation_empty_field`: Verifies [InvalidSuggestionContentError](file:///d:/Jco_Projects/tavanir-ai-assistant-v2/src/domain/exceptions.py) raised on empty fields.
7. `test_input_validation_noise_placeholder`: Verifies noise strings (e.g. `"ندارد"`) trigger validation error.
8. `test_reranker_transient_failure_fallback`: Simulates [RerankerConnectionError](file:///d:/Jco_Projects/tavanir-ai-assistant-v2/src/application/exceptions.py#L163-L167); asserts fallback to RRF retrieval scores and warning log.
9. `test_reranker_validation_error_propagates`: Simulates `RerankerValidationError`; asserts exception is NOT swallowed.
10. `test_threshold_filters_negative_logits`: Verifies candidate suggestions with rerank score below `0.0` are excluded.
11. `test_sql_hydration_drops_soft_deleted`: Verifies suggestions marked `is_deleted = True` in PostgreSQL are omitted from final results.
12. `test_statutes_and_generation_placeholders`: Asserts `applied_statute_ids == []` and `analysis` contains the generation handoff placeholder string.
