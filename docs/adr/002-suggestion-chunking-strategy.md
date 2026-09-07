# ADR-002: Field-Aware Parent-Child Chunking Strategy for Suggestions

- **Status:** Accepted
- **Date:** 2026-09-06
- **Decision Owners:** Tavanir AI Assistance Engineering Team
- **System:** سامانه مدیریت نظام پیشنهادات شرکت توانیر
- **Component:** RAG Ingestion & Retrieval Layer / Suggestion Chunking Strategy

---

## 1. Context

In the Tavanir AI Assistance system, the retrieval pipeline for historical suggestions (`tavanir_suggestion_v1`) serves two core business objectives:
1. **Semantic Similarity & Duplicate Detection:** Identifying previous proposals that address the same problem or propose the same engineering solution.
2. **Precedent & Evaluation Mining:** Surfacing historical committee evaluations to inform generation models of past institutional decisions (approvals, rejections, technical objections).

Unlike unstructured narrative documents (e.g., reports, books) or legal documents (e.g., statutes, articles), an employee proposal is a **structured domain entity** defined in `src/domain/entities.py`:

```python
@dataclass(frozen=True)
class SuggestionContent:
    title: str
    problem: str | None
    solution: str | None


@dataclass(frozen=True)
class CommitteeEvaluation:
    status: SuggestionStatus
    scrutiny: str | None
    description: str | None


@dataclass
class Suggestion:
    id: str
    content: SuggestionContent
    evaluation: CommitteeEvaluation
    date: ShamsiDate | None
    context_title: str | None
```

A chunking and indexing strategy must be chosen that preserves the semantic boundaries of these structured fields while delivering high precision during hybrid retrieval.

---

## 2. Decision

The system will use a **Field-Aware Parent-Child Chunking Strategy** for historical suggestions:

1. **Discrete Child Chunks in Qdrant:** Instead of combining all fields into a single text block, each suggestion is decomposed into at most **four discrete child chunks** based on semantic field boundaries (`TITLE`, `PROBLEM`, `SOLUTION`, `EVALUATION`).
2. **Master Entity in PostgreSQL (System of Record):** The complete suggestion entity is stored in normalized, discrete columns in PostgreSQL.
3. **Parent-Child Association:** Each child chunk in Qdrant stores `parent_id = suggestion.id`.
4. **On-Demand Hydration:** Retrieval and cross-encoder reranking operate on the child chunks. Once the winning proposals are determined via **Max-Passage Pooling (MaxP)**, the full parent representation is hydrated from PostgreSQL for LLM evidence assembly.

```text
                           Suggestion Entity (PostgreSQL)
                                         │
                 ┌───────────────────────┼───────────────────────┐
                 │                       │                       │
                 ▼                       ▼                       ▼
        Child Chunk: TITLE      Child Chunk: PROBLEM    Child Chunk: SOLUTION
         (tavanir_suggestion)    (tavanir_suggestion)    (tavanir_suggestion)
                 │                       │                       │
                 └───────────────────────┼───────────────────────┘
                                         │  (if evaluation exists)
                                         ▼
                                Child Chunk: EVALUATION
                                 (tavanir_suggestion)
```

---

## 3. The 4 Semantic Chunk Types

The domain enum `SuggestionChunkType` in `src/domain/enums.py` defines the four allowable child chunk representations:

```python
class SuggestionChunkType(str, Enum):
    TITLE = "title"
    PROBLEM = "problem"
    SOLUTION = "solution"
    EVALUATION = "evaluation"
```

### 3.1 `TITLE` (Topic & Domain Anchor)
* **Source:** `context_title` + `content.title`
* **Format:** `حوزه: {context_title} | عنوان: {title}` (or `{title}` if `context_title` is null)
* **Purpose:** Provides a high-level thematic summary and prevents ambiguity in short titles by anchoring them to their organizational department (e.g., *معاونت انتقال*, *امور دیسپاچینگ*).

### 3.2 `PROBLEM` (Defect & Need Representation)
* **Source:** `content.problem`
* **Purpose:** Captures the operational defect, bottleneck, or challenge. Allows the system to find suggestions that targeted the **same operational problem**, regardless of whether their proposed technical solutions differed.

### 3.3 `SOLUTION` (Technical Mechanism & Duplicate Detection)
* **Source:** `content.solution`
* **Purpose:** **The primary vector for duplicate proposal detection.** Encodes the specific engineering, operational, or software method proposed by the employee.

### 3.4 `EVALUATION` (Committee Precedent & Scrutiny)
* **Source:** `evaluation.scrutiny` + `evaluation.description`
* **Format:** 
  ```text
  بررسی کمیته: {evaluation.scrutiny}
  توضیحات مصوبه: {evaluation.description}
  ```
* **Purpose:** Enables the system to discover historical precedent (e.g., *"Has the committee previously rejected this approach, and for what technical/budgetary reason?"*).
* **Consolidation Rationale:** `scrutiny` and `description` are combined into a single chunk to prevent creating micro-fragments, as `description` often contains only brief administrative notes.

---

## 4. Why Flat Concatenation Was Rejected

A common baseline in naive RAG is merging all fields into a single structured Markdown text (e.g., `# Title
## Problem...
## Solution...`) and creating a single embedding vector. 

This approach was **explicitly rejected** due to four fundamental failure modes:

### 4.1 Semantic Vector Dilution (Vector Averaging)
A dense embedding model (such as `EmbeddingGemma-300m`, 768 dimensions) compresses text into a single point in high-dimensional space. Concatenating Problem, Solution, and Committee Scrutiny averages three disparate semantic domains into one vector:
* Problem = Symptom/Defect
* Solution = Engineering fix
* Scrutiny = Bureaucratic/Budgetary critique

When a new suggestion proposes the exact same solution for a slightly different substation or symptom, the cosine similarity between the merged documents drops significantly. This causes **false negatives in duplicate detection**.

### 4.2 Query-Corpus Asymmetry
* **Incoming Suggestion (Query):** Contains only `Title`, `Problem`, and `Solution`. It has **no committee review**.
* **Historical Suggestion (Corpus):** Contains `Title`, `Problem`, `Solution`, **plus 300–600 words of committee scrutiny**.

Merging all text causes a structural distribution mismatch between the query vector and historical vectors. The query lacks the large scrutiny block that historical vectors contain.

### 4.3 BM25 Keyword Pollution
Committee scrutiny heavily features administrative and legal terms (*"کمیته تخصصی", "عدم انطباق", "فاقد توجیه اقتصادی", "مصوبه شماره"*).
In a hybrid search system, merging these into a single document causes BM25 term frequency calculations to match proposals based on common administrative phrases rather than core technical terms.

### 4.4 Inability to Distinguish "Same Problem" vs. "Same Solution"
* **Case A:** Two employees describe the same problem, but Employee 1 proposes software and Employee 2 proposes hardware. **(Not duplicates)**
* **Case B:** Two employees describe slightly different symptoms, but propose the exact same technical mechanism. **(True duplicates)**

With field-aware chunking, the retrieval system can query specifically against `chunk_type == 'solution'` to isolate technical duplication from shared problem descriptions.

---

## 5. Storage Strategy & Data Redundancy Trade-Off

### 5.1 System of Record vs. Search Index
* **PostgreSQL (System of Record):** Holds the authoritative truth in discrete, normalized columns. Guarantees ACID compliance, foreign key integrity with users/departments, and audit trails.
* **Qdrant (Search Index):** Holds child vectors and search payloads. Can be deleted and re-indexed from PostgreSQL at any time.

### 5.2 Payload Redundancy vs. Latency Trade-Off
* **Child `content` in Qdrant Payload:** Stored directly in each Qdrant point ($pprox 500	ext{ bytes} - 1	ext{ KB}$). This eliminates the "SQL Hydration Hop" during candidate retrieval and reranking, allowing search and reranking to complete with zero SQL database round-trips.
* **Parent Content Excluded from Qdrant:** The full parent text is **not** duplicated across child vector payloads. Storing full parent documents across all child points would create significant payload bloat ($10	ext{ GB}+$ of duplicate text across 50,000 suggestions). Only `parent_id` is stored.

---

## 6. Retrieval, Scoring & Reranking Pipeline

```text
Incoming Suggestion (Query)
          │
          ▼
1. Qdrant Hybrid Search (Dense + Sparse + RRF)
   └─ Filters: chunk_status == 'active'
   └─ Retrieves: Top 30 Child Chunks
          │
          ▼
2. Cross-Encoder Reranker (Phase 2)
   └─ Query:     Title + Problem + Solution
   └─ Document:  [chunk_type]: content
   └─ Output:    Re-scored Candidate Chunks
          │
          ▼
3. Max-Passage Pooling (MaxP)
   └─ Score(Suggestion) = MAX(Score(Child_Chunks))
   └─ Yields: Top 5 Unique Winning Proposals
          │
          ▼
4. SQL Parent Hydration
   └─ Deduplicate parent_ids: ['SUG-101', 'SUG-205']
   └─ Single query: SELECT * FROM suggestions WHERE id IN (...)
          │
          ▼
5. Evidence Assembly & Generation
   └─ Full parent context passed to LLM
```

### 6.1 Max-Passage Pooling (MaxP)
If Qdrant returns both the `problem` (score: 0.72) and `solution` (score: 0.94) for proposal `SUG-101`:
$$	ext{Score}(	ext{SUG-101}) = \max(0.94, 0.72) = 0.94$$
The proposal is ranked by its strongest matching semantic section.

---

## 7. Handling Optional & Missing Fields

The `SuggestionContent` and `CommitteeEvaluation` classes define `problem`, `solution`, `scrutiny`, and `description` as `str | None`.

**Rule of Omission:** Child chunks are generated **only for non-empty fields**:
* If `problem` is `None` or blank, no `PROBLEM` chunk is created.
* If a new proposal has not yet undergone committee evaluation, no `EVALUATION` chunk is created.
* A suggestion will yield between **1 and 4 child chunks** depending on populated fields.

---

## 8. Alternatives Considered

### Alternative A: Single Concatenated Markdown Chunk
* Single vector representing the entire proposal.
* **Rejected:** Causes severe vector dilution, BM25 pollution, and query-corpus asymmetry (Section 4).

### Alternative B: Character-Count Sliding Window Chunking
* Blindly chunking every 500 characters with 50-character overlap.
* **Rejected:** Destroys structural field integrity, splits technical solutions in half, and divorces sentences from their semantic role.

### Alternative C: Five Separate Child Chunks
* Splitting `evaluation.scrutiny` and `evaluation.description` into distinct chunks.
* **Rejected:** Over-fragmentation. Committee description fields are frequently short administrative notes that lack standalone semantic value.

### Alternative D: Qdrant Native Named Vectors on a Single Point
* One point in Qdrant per suggestion, containing multiple named vectors (`vectors={'problem': [...], 'solution': [...]}`).
* **Evaluated as technically sound, but deferred:** While Qdrant supports named vectors, the Multi-Point Parent-Child architecture was chosen because:
  1. It provides uniform compatibility with standard hybrid search and fusion tooling.
  2. It cleanly accommodates suggestions with varying numbers of populated fields without sparse matrix gaps.
  3. It allows independent payload filtering on `chunk_type` during section-specific queries.

---

## 9. Consequences

### Positive Consequences
* **Extreme Duplicate Detection Accuracy:** The `solution` vector captures pure technical intent without dilution from problem or scrutiny text.
* **Explainable Matching:** Search results identify the exact field that triggered the match (*"Matched on Solution with 0.93 similarity"*).
* **Precedent Mining:** Evaluators can explicitly query past committee scrutiny for rejected ideas.
* **Storage Optimization:** Eliminates parent text duplication in Qdrant while keeping search latency sub-50ms.

### Negative Consequences
* **Point Proliferation:** Each suggestion produces 2 to 4 Qdrant points instead of 1. For 100,000 suggestions, Qdrant will store $pprox 300,000$ points.
* **Aggregation Overhead:** The retrieval service must perform MaxP pooling across child chunks to group candidates by `parent_id` before SQL hydration.

Both trade-offs are standard in enterprise Information Retrieval and are well within Qdrant's scaling capacity.

---

## 10. Decision Summary

* Historical suggestions will be indexed using **Field-Aware Parent-Child Chunking**.
* Up to **4 chunk types** (`TITLE`, `PROBLEM`, `SOLUTION`, `EVALUATION`) are generated per proposal.
* Qdrant stores child vectors for mathematical similarity matching.
* PostgreSQL stores normalized master entities and hydrates full context for the LLM upon retrieval.

**Decision: Accepted - implement Field-Aware Parent-Child chunking.**
