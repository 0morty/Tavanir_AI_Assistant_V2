# High-Level Architecture (HLA)

## 1. Purpose of the Architecture

This document describes the **Tavanir AI Assistant V2** (internal codename **JadooChatRAG**) — a Python (FastAPI) microservice that acts as a Retrieval-Augmented Generation (RAG) engine for the **Tavanir Suggestion Committee** workflow. It follows a **Clean Architecture** (see `docs/architecture/clean_architecture.md`), single-module layout, exposing suggestion analysis and ingestion capabilities backed by an embedding/LLM pipeline and a vector index.

> **Status note:** This document separates current behavior from the target architecture. The analysis route invokes the injected final generator with usable evidence and returns its parsed answer; the no-evidence branch skips generation. Expansion invokes the shared chat pipeline and parses five fields, with a current working-tree prompt/marker mismatch documented in the [Generation guide](../documentation/llm_generation_api.md). A lower-level live ContextBuilder-to-vLLM test does not validate the API path. See the [Generation API test summary](../documentation/llm_generation_test_summary.md) and [remaining backlog](../planning/v2_unimplemented_features.md).

---

## 2. Main Components

### Upstream Tavanir System (Caller / Data Source)

The legacy Tavanir suggestion-committee system is the authoritative source of suggestion records. It stores historical suggestions in a legacy **MSSQL** database (`SuggestionInfo`, `Suggestion`, `CommitteeSessionResult`, `ComitteeScrutiny`, `SuggestContext`) with a numeric `StatusID` legacy status.

The V2 service ingests these records and exposes analysis APIs. No user/account domain exists in V2; the current API enforces service-level `X-API-Key` authentication through `src/presentation/security.py` (see `docs/contracts/06_Authentication_And_Caller_Identity.md`).

### FastAPI Service (API)

The implemented entry point is `src/main.py` (`create_app`) with dependency injection initialized in `src/presentation/lifespan.py`. Current routes include:

- `POST /api/v1/suggestions/analyze`: normalize, retrieve and rank suggestion evidence, hydrate records, pass prepared evidence to the injected generator, and return its validated answer in `analysis`, cited IDs, and uncertainty. With no usable evidence, generation is skipped.
- `POST /api/v1/suggestions/ingest` and suggestion update/delete routes: synchronous suggestion lifecycle operations.
- `GET /health`: service liveness.
- `POST /api/v1/suggestions/expand-suggestion`: validate one description (maximum 512 model tokens), process sections through ContextBuilder, invoke the shared LLM, and return five parsed fields.

Custom-template update routes remain target work; final generation is integrated into the analysis route. Per-request retrieval and real-time ingestion are currently synchronous; moving long-running batch ingestion to the Worker remains a target.

### Async Worker — Python **[planned]**

A standalone async worker process that consumes jobs from an async task queue (ARQ) and executes the heavy pipelines:

- Historical suggestion extraction from MSSQL (batched, streamed) → normalize → chunk → embed → index
- Statute ingestion from Excel files → normalize → chunk → embed → index
- Long-running batch jobs only; no business state lives in the worker process

### Embedding & LLM Providers **[adapters implemented; Generation HTTP integration implemented]**

Outbound model calls use **OpenAI-compatible** clients (`AsyncOpenAI`) against self-hosted endpoints:

- **TEI** (Text Embeddings Inference) — default embedding provider, `http://TEI_HOST:TEI_PORT/v1` (default `localhost:8080`, model `google/embedding-gemma-2b`, dimension 768)
- **vLLM** — generation provider, `http://VLLM_HOST:VLLM_PORT/v1` (default `localhost:8000`), OpenAI-compatible chat/completions
- Optional local in-process **SentenceTransformer** embedder [planned] for **ParsBERT V3 / Shafagh** models, run inside `asyncio.to_thread`

The container registers the shared request/client/context pipeline, both output parsers, `GenerateSuggestionUseCase`, and `StructureIdeaUseCase`. `AnalyzeSuggestionUseCase` receives `generator=generate_suggestion_use_case`; the expansion route injects `IStructureIdeaUseCase`. Provider clients are pooled through `LLMClientRegistry` and configured in `src/infrastructure/configs/settings.py`. The model defaults to `Qwen/Qwen2.5-7B-Instruct`; the successful local 0.5B test used temporary overrides.

### Vector Database — Qdrant **[suggestion retrieval implemented; statute retrieval pending]**

- `tavanir_suggestion_v1` collection — suggestion chunks searched across three tracks with status probes.
- Statute retrieval for the analysis response remains unimplemented; `applied_statute_ids` is currently empty.

Candidate hits are deduplicated by chunk ID across retrieval tracks, reranked, then pooled by parent suggestion before prompt preparation.

### Data Stores

| Store | Role |
|---|---|
| Legacy **MSSQL** database | Source of historical suggestions (read-only) |
| **Excel** statute files | Source of organizational laws/bylaws |
| **Qdrant** | Current suggestion vector index; statute index/retrieval is target work |
| **Local file** (`assets/custom_template.json`) | Target custom prompt persistence; not wired into the current analysis route |

---

## 3. Main System Flows

### Suggestion Analysis **[Generation handoff implemented]**

```text
Upstream System / API client
   │
   ▼
FastAPI (POST /api/v1/suggestions/analyze)
   │
   └── AnalyzeSuggestionUseCase
         ├── Normalize Persian text; generate dense/sparse query embeddings
         ├── Five Qdrant queries across three suggestion-retrieval tracks
         ├── Deduplicate, rerank, group by parent, hydrate from PostgreSQL
         └── GenerateSuggestionUseCase
                  ├── SuggestionPromptPreparer → PromptBuilder → ContextBuilder
                  ├── LLMRequestBuilder → OpenAILLMClient → vLLM
                  └── GenerationOutputParser → GenerationResult → response
```

On the normal path, `AnalyzeSuggestionResponse.analysis` contains the parsed model answer. The HTTP response also includes `citedSuggestionIds`, `uncertainty`, `isFallbackMode`, and `groundingRatio` (citation coverage, not calibrated confidence). Existing five candidate lists remain distinct from citations; `appliedStatuteIds` stays empty. With no usable evidence, the existing guard returns diagnostics without an LLM call.

### Idea Expansion **[pipeline implemented]**

```text
POST /api/v1/suggestions/expand-suggestion
   → StructureIdeaDTO → validate description ≤ 512 model tokens
   → StructureIdeaUseCase → PromptBuilder sections
   → ContextBuilder → processed sections → LLMRequestBuilder
   → shared OpenAILLMClient → LLM completion
   → StructuredIdeaOutputParser → five-field JSON success envelope
```

Static instructions are Persian; the parser's required labels remain English. The current prompt example translates those labels and therefore disagrees with the parser; this is an open Generation issue. See the [Generation guide](../documentation/llm_generation_api.md) for exact sections, budgets, errors, and limitations.

### Historical Ingestion Pipeline **[planned]**

```text
ARQ Worker
   ├── Authenticate to legacy MSSQL
   ├── Stream suggestion batches (CTE query, ROW_NUMBER per SuggestionCode, OFFSET/FETCH)
   ├── Map legacy StatusID → SuggestionStatus (from_id)
   ├── Normalize → chunk → embed (batched)
   └── Upsert into Qdrant (suggestions collection)
```

### Statute Ingestion Pipeline **[planned]**

```text
ARQ Worker
   ├── Parse .xlsx/.xls (Excel loader)
   ├── Map rows to text + metadata (statute_id, article_number, source_file)
   ├── Normalize → chunk → embed
   └── Upsert into Qdrant (statutes collection)
```

---

## 4. Responsibility Boundaries

| Layer / Component | Responsibility |
|---|---|
| `src/domain/` | Entities, value objects, enums, business-rule exceptions — pure stdlib, no framework imports |
| `src/application/` | Use cases (orchestration), DTOs, ports/interfaces (`IDenseEmbedder`) |
| `src/infrastructure/` | Settings, TEI/vLLM client factory + registry, adapters (embedder), DB/extractor/excel implementations **[partial]** |
| `src/presentation/` | FastAPI app, routers, schemas, API-key security, lifespan, and exception handlers **[implemented]** |
| `src/containers.py` | Composition root — DI wiring (**implemented**) |

---

## 5. Important Principles for the Team

### 5.1 Clean Architecture Dependency Rule
Dependencies point strictly inward toward `src/domain/`. The domain layer must never import FastAPI, SQLAlchemy, Pydantic, or external SDKs. Concrete adapters live in `src/infrastructure/` and satisfy ports declared in `src/domain/interfaces/` / `src/application/interfaces/`.

### 5.2 Batch Work Is a Worker Target
The standalone ARQ worker remains planned. The current ingestion route performs its work synchronously; the analysis route performs embedding, retrieval, reranking, prompt preparation, and final generation before responding when usable evidence exists.

### 5.3 Legacy Domain Is Translated at the Boundary
Legacy numeric `StatusID` values map to the Persian `SuggestionStatus` enum (`src/domain/enums.py`) via `from_id()`. Outside boundaries communicate stable domain concepts, not raw legacy integers.

### 5.4 FFmpeg of Normality: Persian-first Data
Suggestion and statute content, status titles (`اجرا شده`, `مصوب`, `در حال اجرا`, `رد`, `عدم پذیرش`), and context titles are Persian-language; normalization (Persian text normalization) happens before embedding.

---

## 6. Level 1 / Level 2 / Level 3

### Level 1 — Conceptual

```text
Upstream Tavanir System / API client
   ↓
FastAPI + Async Worker
   ├── Qdrant (vector index)
   ├── Legacy MSSQL (source of suggestions)
   └── Excel files (statutes source)
```

### Level 2 — Technology Mapping

- FastAPI (Python 3.12) — API
- ARQ — async worker **[planned]**
- Qdrant — suggestion vector retrieval **[implemented]**; statute retrieval **[planned]**
- MSSQL + pymssql — historical suggestion extractor **[implemented]**; worker scheduling **[planned]**
- openpyxl / pandas — Excel statute loading **[planned]**
- TEI / vLLM (OpenAI-compatible) — embedding and generation adapters **[implemented]**; generation connected to Analyze and Expand Suggestion
- SentenceTransformers (ParsBERT V3 / Shafagh) — optional local embeddings **[planned]**
- SQLAlchemy 2.0 + Alembic (async) — PostgreSQL repository and migrations implemented
- dependency-injector — composition root (**implemented**)

### Level 3 — Communication Detail

- HTTP(S) service calls — API client ↔ FastAPI
- OpenAI-compatible REST — FastAPI/Worker ↔ TEI / vLLM
- Qdrant HTTP/gRPC — Worker ↔ Qdrant **[planned]**
- MSSQL async driver — Worker ↔ legacy MSSQL **[planned]**
- File I/O — Worker ↔ Excel files, `assets/custom_template.json`

---

## 7. Architectural Decision

Reference flow:

```text
Upstream / API client
   │ HTTP (API Key)
   ▼
FastAPI
   ├── /api/v1/suggestions/analyze → AnalyzeSuggestionUseCase
   │                                  ├── Embed (TEI) + retrieve suggestions (Qdrant)
   │                                  ├── Rerank + hydrate (PostgreSQL)
   │                                  └── GenerateSuggestionUseCase → vLLM → parser → response
   ├── /api/v1/suggestions/expand-suggestion → sections → context → vLLM → parser
   └── /api/v1/suggestions/ingest → synchronous ingestion

Both Generation orchestration paths are registered and called through HTTP routes.
Current expansion marker agreement and live model/API verification remain open.
ARQ Worker and statute ingestion/retrieval remain target work.
```

Cross-reference: implementation-status details live in `docs/planning/v2_unimplemented_features.md`; layer-level architectural rules in `docs/architecture/clean_architecture.md`; the de-facto library set in `docs/technology-stacks.md`.