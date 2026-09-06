# High-Level Architecture (HLA)

## 1. Purpose of the Architecture

This document describes the **Tavanir AI Assistant V2** (internal codename **JadooChatRAG**) — a Python (FastAPI) microservice that acts as a Retrieval-Augmented Generation (RAG) engine for the **Tavanir Suggestion Committee** workflow. It follows a **Clean Architecture** (see `docs/architecture/clean_architecture.md`), single-module layout, exposing suggestion analysis and ingestion capabilities backed by an embedding/LLM pipeline and a vector index.

> **Status note:** This is a target architecture. Features marked **[planned]** are not yet implemented; `docs/planning/v2_unimplemented_features.md` is the authoritative backlog. Sections that describe only the implemented subset are marked **[implemented]**.

---

## 2. Main Components

### Upstream Tavanir System (Caller / Data Source)

The legacy Tavanir suggestion-committee system is the authoritative source of suggestion records. It stores historical suggestions in a legacy **MSSQL** database (`SuggestionInfo`, `Suggestion`, `CommitteeSessionResult`, `ComitteeScrutiny`, `SuggestContext`) with a numeric `StatusID` legacy status.

The V2 service ingests these records and exposes analysis APIs. No user/account domain exists in V2 — the caller is trusted and V2 does **not** implement its own authentication/user layer (see `docs/contracts/06_Authentication_And_Caller_Identity.md` for the service-level auth contract).

### FastAPI Service (API)

The primary entry point of the subsystem. Responsibilities **[planned unless marked]**:

- Request validation and orchestration
- Suggestion analysis (`POST /analyze-suggestion/analyze`) and custom-template updates (`POST /analyze-suggestion/set-template`)
- Real-time suggestion ingestion (`POST /ingest-suggestion/ingest`) and deletion (`POST /ingest-suggestion/delete`)
- Persisting the custom prompt template (`assets/custom_template.json`)

> Core principle: heavy processing (embedding, chunking, indexing) is **not** done synchronously in the API. The API validates and delegates; batch/historical work runs in the Worker.

### Async Worker — Python **[planned]**

A standalone async worker process that consumes jobs from an async task queue (ARQ) and executes the heavy pipelines:

- Historical suggestion extraction from MSSQL (batched, streamed) → normalize → chunk → embed → index
- Statute ingestion from Excel files → normalize → chunk → embed → index
- Long-running batch jobs only; no business state lives in the worker process

### Embedding & LLM Providers **[implemented for embeddings]**

Outbound model calls use **OpenAI-compatible** clients (`AsyncOpenAI`) against self-hosted endpoints:

- **TEI** (Text Embeddings Inference) — default embedding provider, `http://TEI_HOST:TEI_PORT/v1` (default `localhost:8080`, model `google/embedding-gemma-2b`, dimension 768)
- **vLLM** — generation provider, `http://VLLM_HOST:VLLM_PORT/v1` (default `localhost:8000`), OpenAI-compatible chat/completions
- Optional local in-process **SentenceTransformer** embedder [planned] for **ParsBERT V3 / Shafagh** models, run inside `asyncio.to_thread`

Provider clients are cached and connection-pooled through `LLMClientRegistry` (`src/infrastructure/services/llm/llm_client_registry.py`) and configured via `src/infrastructure/configs/settings.py`.

### Vector Database — Qdrant **[planned]**

Used for semantic retrieval with payload metadata for filtering:

- `suggestions` collection — suggestion chunks filtered by status category and `context_title`
- `statutes` collection — organizational laws/bylaws

Candidate hits are deduplicated per parent suggestion (keep lowest-distance chunk) before prompt assembly.

### Data Stores

| Store | Role |
|---|---|
| Legacy **MSSQL** database | Source of historical suggestions (read-only) |
| **Excel** statute files | Source of organizational laws/bylaws |
| **Qdrant** | Vector index for suggestions and statutes |
| **Local file** (`assets/custom_template.json`) | Persisted custom prompt template |

---

## 3. Main System Flows

### Suggestion Analysis **[target flow]**

```text
Upstream System / API client
   │
   ▼
FastAPI (POST /analyze-suggestion/analyze)
   │
   └── AnalyzeSuggestionUseCase
         ├── Synthesize input (title + current problem + solution)
         ├── Normalize Persian text
         ├── Generate query embedding (IDenseEmbedder → TEI/vLLM)
         ├── Parallel vector search across 5 status partitions + statutes (Qdrant)
         ├── Deduplicate & group candidate precedents
         ├── Assemble Chain-of-Thought prompt (with token budget)
         └── Invoke LLM (temperature 0.1) → structured decision analysis
```

Result shape follows `AnalyzeSuggestionResponse` (`src/application/dtos.py`): the markdown `analysis` plus provenance lists — `similar_executed_ids`, `similar_approved_ids`, `similar_pending_ids`, `similar_rejected_ids`, `similar_not_accepted_ids`, `applied_statute_ids`.

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
| `src/presentation/` | FastAPI routers, schemas, security, lifespan **[planned; empty today]** |
| `src/containers.py` | Composition root — DI wiring (**implemented**) |

---

## 5. Important Principles for the Team

### 5.1 Clean Architecture Dependency Rule
Dependencies point strictly inward toward `src/domain/`. The domain layer must never import FastAPI, SQLAlchemy, Pydantic, or external SDKs. Concrete adapters live in `src/infrastructure/` and satisfy ports declared in `src/domain/interfaces/` / `src/application/interfaces/`.

### 5.2 Heavy Work Lives Outside the Request Path
Embedding, chunking, and indexing of large batches run in the worker, never synchronously inside the FastAPI request handler. Only lightweight per-request analysis runs synchronously.

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
- Qdrant — vector database **[planned]**
- MSSQL + aioodbc/pyodbc — legacy extraction **[planned]**
- openpyxl / pandas — Excel statute loading **[planned]**
- TEI / vLLM (OpenAI-compatible) — embeddings + generation (**implemented** for embedding client)
- SentenceTransformers (ParsBERT V3 / Shafagh) — optional local embeddings **[planned]**
- SQLAlchemy 2.0 + Alembic (async) — scaffolded, not wired
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
   │
   │ HTTP (API Key)
   ▼
FastAPI
   ├── /analyze-suggestion/*  → AnalyzeSuggestionUseCase
   │                              ├── Embed (TEI) + LLM (vLLM)
   │                              └── Retrieve (Qdrant: suggestions + statutes)
   └── /ingest-suggestion/*   → deletes / queues real-time ingestion
                                 │
                                 ▼
                             ARQ Worker [planned]
                                 ├── Extract (MSSQL / Excel)
                                 ├── Normalize → Chunk → Embed
                                 └── Index → Qdrant
```

Cross-reference: implementation-status details live in `docs/planning/v2_unimplemented_features.md`; layer-level architectural rules in `docs/architecture/clean_architecture.md`; the de-facto library set in `docs/technology-stacks.md`.