# Technology Stacks — Tavanir AI Assistant V2 (JadooChatRAG)

This document summarizes the technology stack of the **Tavanir AI Assistant V2** suggestion-committee RAG service.

**Legend:**
- **[declared]** — listed in `requirements.txt`; installation in a particular environment must be checked separately
- **[implemented]** — present in current production source code
- **[planned]** — target work not yet wired into the stated runtime path

## Core Language & Runtime
- **Language:** Python 3.12
- **Runtime:** ASGI (async-first), FastAPI; Uvicorn for the server [declared]
- **Containerized via:** `docker-compose.yaml` has service configuration, but the root `Dockerfile` is empty; a complete application image build is not documented here.

## Web Framework & API
- **Web Framework:** FastAPI (with Starlette under the hood) [declared, implemented]
- **Server:** Uvicorn [declared]
- **CLI:** Typer, FastAPI CLI [declared]
- **Validation / Settings:** Pydantic 2.x and pydantic-settings [declared, implemented]; other helpers are declared in requirements.
- **Logging / Observability:** structlog and asgi-correlation-id [declared, implemented]; Sentry SDK [declared].

## Architecture & Patterns
- **Architecture:** Clean Architecture (Domain / Application / Infrastructure / Presentation) — see `docs/architecture/clean_architecture.md`
- **Design Patterns:** Dependency Injection via `dependency-injector` [declared, implemented]; `src/application/use_cases/` contains the analysis and Generation use cases.
- **Async I/O:** async/await throughout; connection pooling via `LLMClientRegistry`

## LLM & Embedding Providers
- **SDK:** `openai` (`AsyncOpenAI`, OpenAI-compatible) [declared, implemented]
- **Embedding Provider:** TEI (Text Embeddings Inference), default `http://localhost:8080/v1`, model `google/embedding-gemma-2b`, dimension 768 `[configuration in code]`
- **Generation Provider:** vLLM, default `http://localhost:8000/v1` and model `Qwen/Qwen2.5-7B-Instruct` [configured]. The shared provider/request infrastructure is used by both implemented Generation use cases. Analyze invokes `GenerateSuggestionUseCase`; expansion invokes `StructureIdeaUseCase` and its plain-text parser. See the [current Generation guide](documentation/llm_generation_api.md), including the working-tree marker mismatch. The older Prompt Rendering statement in the retrieval section below is a historical snapshot; retrieval content is outside this Generation-only update.
- **Provider config:** `LLMProvider` enum (`tei` / `vllm`) in `src/infrastructure/configs/llm_provider_configs.py`
- **Local embeddings:** SentenceTransformers (ParsBERT V3 / Shafagh) [planned]
- **Persian text normalization:** Shekar normalizer [declared, implemented]

## Vector Store & Retrieval
- **Vector Database:** Qdrant suggestion repository and `tavanir_suggestion_v1` collection [implemented]; statute retrieval in analysis [planned].
- **Retrieval Strategy:** five Qdrant queries across three suggestion-retrieval tracks, chunk-ID deduplication, cross-encoder reranking, parent pooling, and PostgreSQL hydration [implemented].
- **Prompt Rendering:** `PromptBuilder`, `ContextBuilder`, and `SuggestionPromptPreparer` [implemented]. The analysis route returns their fitted prompt as `analysis`; it does not return a parsed LLM answer.

## Data Extraction (legacy sources)
- **Legacy MSSQL suggestion database:** `MssqlSuggestionExtractor` uses `pymssql` [declared, implemented]; the standalone worker process remains planned.
- **Excel statute files** (`.xlsx` / `.xls`): `openpyxl` / `pandas` [planned]

## Persistence & Migrations
- **ORM:** SQLAlchemy 2.0 [declared, implemented]
- **Migrations:** Alembic [declared]; repository migrations and PostgreSQL models are present. Verify migration state before deployment.

## Task Queue / Async Work
- **Worker:** ARQ (`arq`, `src.worker.WorkerSettings`) [planned] — `src/worker.py` is currently empty

## Testing
- **Framework:** pytest [declared]
- **Plugins:** pytest-asyncio, pytest-cov, pytest-mock, pytest-xdist, pytest-env [declared]
- **Fakes:** Faker [declared]
- **State:** unit and integration tests exist and `pytest.ini` is present. Generation unit and controlled HTTP/provider tests exist. Expansion HTTP tests run the real pipeline with a mocked provider; Analyze HTTP tests override its use case. The historical live ContextBuilder-to-vLLM runner covers a lower-level path, not a real endpoint completion; see the [Generation API test summary](documentation/llm_generation_test_summary.md).

## Supporting / Utility Libraries
- **HTTP client:** httpx [declared]
- **Config / data:** pydantic-settings, python-dotenv, PyYAML [declared]
- **CLI / terminal:** typer, rich [declared]
- **Timezone:** tzdata [declared]
- **Binary / misc:** greenlet, anyio, websockets [declared]

## Dev Infrastructure Status
| Item | Status |
|---|---|
| `.env.sample` | empty placeholder; settings load `.env` from the repo root |
| `Dockerfile` / `docker-compose.yaml` | root Dockerfile empty; Compose file contains service configuration |
| Lint / format (ruff) | `.ruff_cache/` in `.gitignore` but no config installed |
| Local model services | settings default to TEI at `localhost:8080` and vLLM at `localhost:8000`; actual availability and model identity are environment-specific |

## Notable Gaps
- Generation pipelines are connected, but the current expansion prompt example uses Persian markers while the parser requires English markers. Full chat-framing/completion-reserve accounting, supplied-regulation rendering/citations, expansion mock-mode support, and live endpoint-to-model validation remain gaps.
- Default 7B model and token settings must match the actual deployed vLLM server. The successful local 0.5B run used temporary overrides and is not proof of API readiness.