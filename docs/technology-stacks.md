# Technology Stacks — Tavanir AI Assistant V2 (JadooChatRAG)

This document summarizes the technology stack of the **Tavanir AI Assistant V2** suggestion-committee RAG service.

**Legend:**
- **[pinned]** — listed in `requirements.txt` (verified present)
- **[gap]** — imported by the source code but **missing** from `requirements.txt` (install before running)
- **[planned]** — target implementation from `docs/planning/v2_unimplemented_features.md`, not yet implemented/depended on

## Core Language & Runtime
- **Language:** Python 3.12
- **Runtime:** ASGI (async-first), FastAPI; Uvicorn for the server [pinned]
- **Containerized via:** Docker — `Dockerfile` and `docker-compose.yaml` exist but are **empty placeholders**

## Web Framework & API
- **Web Framework:** FastAPI (with Starlette under the hood) [pinned]
- **Server:** Uvicorn [pinned]
- **CLI:** Typer, FastAPI CLI [pinned]
- **Validation / Settings:** Pydantic 2.x, pydantic-settings, pydantic-extra-types, python-multipart, email-validator [pinned]
- **Logging / Observability:** Sentry SDK (sentry-sdk) [pinned]

## Architecture & Patterns
- **Architecture:** Clean Architecture (Domain / Application / Infrastructure / Presentation) — see `docs/architecture/clean_architecture.md`
- **Design Patterns:** Dependency Injection via `dependency-injector` [gap], CQRS planned (empty `src/application/use_cases/`)
- **Async I/O:** async/await throughout; connection pooling via `LLMClientRegistry`

## LLM & Embedding Providers
- **SDK:** `openai` (`AsyncOpenAI`, OpenAI-compatible) [gap]
- **Embedding Provider:** TEI (Text Embeddings Inference), default `http://localhost:8080/v1`, model `google/embedding-gemma-2b`, dimension 768 `[configuration in code]`
- **Generation Provider:** vLLM, default `http://localhost:8000/v1` `[configuration in code]`
- **Provider config:** `LLMProvider` enum (`tei` / `vllm`) in `src/infrastructure/configs/llm_provider_configs.py`
- **Local embeddings:** SentenceTransformers (ParsBERT V3 / Shafagh) [planned]
- **Persian text normalization:** Shekar normalizer [planned]

## Vector Store & Retrieval
- **Vector Database:** Qdrant — `suggestions` + `statutes` collections [planned]
- **Retrieval Strategy:** parallel per-status search over five `SuggestionStatus` partitions + statutes, chunk deduplication by parent suggestion [planned]
- **Prompt Rendering:** Jinja2 (templates `suggestion_analysis_system.jinja2` / `suggestion_analysis_user.jinja2`) [pinned for `jinja2`]

## Data Extraction (legacy sources)
- **Legacy MSSQL suggestion database:** extraction via `aioodbc` / `pyodbc` [planned]
- **Excel statute files** (`.xlsx` / `.xls`): `openpyxl` / `pandas` [planned]

## Persistence & Migrations
- **ORM:** SQLAlchemy 2.0 [pinned]
- **Migrations:** Alembic (async scaffolded; `migrations/env.py` has `target_metadata = None` — **not wired**) [pinned]

## Task Queue / Async Work
- **Worker:** ARQ (`arq`, `src.worker.WorkerSettings`) [planned] — `src/worker.py` is currently empty

## Testing
- **Framework:** pytest [pinned]
- **Plugins:** pytest-asyncio, pytest-cov, pytest-mock, pytest-xdist, pytest-env [pinned]
- **Fakes:** Faker [pinned]
- **State:** `tests/{unit,integration,e2e}` are empty scaffolds; no test/lint config (`pyproject.toml`, `pytest.ini`, `conftest.py`) exists

## Supporting / Utility Libraries
- **HTTP client:** httpx [pinned]
- **Config / data:** pydantic-settings, python-dotenv, PyYAML [pinned]
- **CLI / terminal:** typer, rich [pinned]
- **Timezone:** tzdata [pinned]
- **Binary / misc:** greenlet, anyio, websockets [pinned]

## Dev Infrastructure Status
| Item | Status |
|---|---|
| `.env.sample` | empty placeholder; settings load `.env` from the repo root |
| `Dockerfile` / `docker-compose.yaml` | empty placeholders |
| Lint / format (ruff) | `.ruff_cache/` in `.gitignore` but no config installed |
| Local model services | TEI on `localhost:8080`, vLLM on `localhost:8000` (external, not yet in compose) |

## Notable Gaps
- `openai` and `dependency-injector` are imported by `src/containers.py`, `src/infrastructure/configs/llm_provider_configs.py`, and `src/infrastructure/services/*` but are **absent from `requirements.txt`** — add them before running anything that imports `src.containers`.