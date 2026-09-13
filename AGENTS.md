# AGENTS.md

Early-stage FastAPI project (Tavanir AI Assistant V2) on a Clean Architecture scaffold. Most of the architecture is NOT implemented yet.

## Repo state (read this first)
- Docs (`docs/architecture/clean_architecture.md`, `docs/architecture/high_level_architecture.md`, `docs/index.md`) describe the **target** design and name the domain "JadooChatRAG". Do not assume they match the code — most referenced files are empty placeholders. `high_level_architecture.md` marks each part `[implemented]`/`[planned]`; `docs/planning/v2_unimplemented_features.md` is the authoritative backlog.
- API wire contracts live in `docs/contracts/` (JSON:API envelope, camelCase external / snake_case internal mapping, internal error-code dictionary, API-key auth). Follow them when building the HTTP layer; auth is a **target** contract only — `src/presentation/security.py` is empty. Error codes map to real exceptions in `src/application/exceptions.py` / `src/domain/exceptions.py`.
- `docs/technology-stacks.md` lists verified deps (`[pinned]`/`[gap]`/`[planned]` legend) and confirms the `requirements.txt` gaps below. Docs are English; Persian domain terms (suggestion statuses, context titles) appear inline where the code uses them.
- Implemented so far: domain entities/enums/exceptions (`src/domain/`), application DTOs/exceptions + `IDenseEmbedder` port + prompt-builder architecture (`src/application/context/` for the general `Section` concept, `src/application/prompt_architecture/` for `PromptBuilder`), and infrastructure: settings + TEI/vLLM OpenAI-compatible client config, `BaseOpenAIService`, `OpenAIDenseEmbedder`, `LLMClientRegistry`, and DI wiring in `src/containers.py`.
- Empty/unwired placeholders: `src/main.py`, `src/worker.py`, everything under `src/presentation/` (lifespan, security, routers, schemas), `src/infrastructure/db/`, repositories, use cases, all `tests/`. There is no runnable entrypoint yet — `uvicorn src.main:app` cannot work.
- `docs/planning/v2_unimplemented_features.md` is the authoritative backlog of what still needs building.

## Environment gotchas
- `requirements.txt` is out of sync with imports: `src/containers.py` and `src/infrastructure/configs/llm_provider_configs.py` import `openai` and `dependency-injector`, which are NOT in `requirements.txt`. Install/add them before running anything that imports `src.containers`.
- Settings (`src/infrastructure/configs/settings.py`) load `.env` from the repo root via `Path(__file__).resolve().parents[3]`. Defaults target local TEI (localhost:8080) and vLLM (localhost:8000) with an `EMPTY` API key; providers are configured through `TEI_HOST/TEI_PORT`/`VLLM_HOST/VLLM_PORT`.
- Always run commands from the repo root: internal imports are absolute (`from src....`), and `alembic.ini` sets `prepend_sys_path = .`.

## Tests / tooling
- No `pyproject.toml`, `setup.cfg`, `pytest.ini`, `conftest.py`, or lint/format config exists; `tests/{unit,integration,e2e}` are empty scaffolds. Test deps pinned in requirements: pytest, pytest-asyncio, pytest-cov, pytest-mock, pytest-xdist.

## Migrations
- Alembic (async) is scaffolded but not wired: `migrations/env.py` has `target_metadata = None` and `alembic.ini` still has the placeholder `sqlalchemy.url`. No models or version files exist.

## Conventions
- Clean Architecture dependency rule: `src/domain/` must stay pure stdlib (no FastAPI, SQLAlchemy, Pydantic); outer layers depend inward through ports under `src/domain/interfaces/` and `src/application/interfaces/`.
- Domain uses Persian suggestion statuses: `SuggestionStatus` in `src/domain/enums.py` converts legacy `status_id` ints and Persian titles via `from_id()`/`from_string()`.
- **Commit messages: always generate short and meaningful commits** (Conventional Commits, per `docs/contracts/02_Git_Commit_Convention.md`); add a body only when extra description is genuinely needed.

---

## LLM / Generation API — Developer Scope

This section defines the exclusive ownership boundary for the **LLM / Generation API** layer. It is a hard constraint that takes precedence over convenience, implementation speed, or architectural cleanup.

### 1. Responsibility

The LLM / Generation API is responsible for everything that happens **after** retrieval produces structured input and **before** the result is returned to the caller. Specifically:

- Preparing the input/context passed to the LLM
- Defining the input contract for the Generation API
- Representing the current suggestion provided to the LLM
- Representing similar suggestions provided to the LLM
- Representing relevant regulations/instructions provided to the LLM
- Building and formatting the LLM prompt
- Calling/invoking the LLM
- LLM provider abstraction and implementations
- Managing LLM generation configuration
- Managing token/context budgets related to generation
- Parsing and validating structured LLM output
- Defining the output contract of the Generation API
- Handling generation-specific errors, retries, timeouts, and fallbacks
- Generation-specific logging, metrics, tracing, and observability
- Generation-specific tests

### 2. In-Scope Components

#### 2.1 Already Implemented (owned, may be modified)

| File | What belongs to Generation |
|---|---|
| `src/application/dtos.py` | `AnalyzeSuggestionResponse` — the output contract |
| `src/application/exceptions.py` | LLM exception hierarchy only: `LLMBaseError`, `LLMConfigurationError`, `LLMConnectionError`, `LLMAPIError`, `LLMAuthenticationError` (lines 55-85). Do NOT touch `ApplicationError`, `ApplicationAPIError`, or any Embedder exception. |
| `src/application/context/` | `Section` base class (general-purpose, with `importance` weight) and the predefined sections (`RoleSection`, `HistorySection`, `ChunksSection`, `SystemInputSection`, `UserInputSection`, `OutputFormatSection`). New sections are developer-designed `Section` subclasses — there is no generic string section. |
| `src/application/prompt_architecture/` | `PromptBuilder` (prompt composition/rendering only) |
| `src/infrastructure/configs/settings.py` | `LLMSettings` class (lines 30-52) and `llm_settings` singleton. Do NOT touch `CoreSettings`, `EmbeddingSettings`, or `embedding_settings`. |
| `src/infrastructure/configs/llm_provider_configs.py` | Entire file — `LLMProvider`, `APIKeyProvider`, `AsyncOpenAIClientFactory` |
| `src/infrastructure/services/base_openai_service.py` | Entire file — shared base for OpenAI-compatible error handling |
| `src/infrastructure/services/llm/llm_client_registry.py` | Entire file — `LLMClientRegistry` connection pooling |

#### 2.2 Shared (read-only, do NOT modify)

| File | Why shared |
|---|---|
| `src/domain/entities.py` | `Suggestion`, `SuggestionContent`, `CommitteeEvaluation`, `StatuteDocument`, `ShamsiDate`, `Chunk`, `HistoryMessage` — consumed by Generation but owned by Domain |
| `src/domain/enums.py` | `SuggestionStatus`, `HistoryRole` — used across all layers |
| `src/domain/exceptions.py` | Base `DomainError` and subtypes |
| `src/containers.py` | DI composition root — may add Generation providers but must NOT remove or restructure existing embedder providers |

#### 2.3 To Be Created (within Generation scope)

| Planned File | Purpose |
|---|---|
| `src/application/interfaces/i_llm_client.py` | Application-layer port for LLM invocation |
| `src/application/interfaces/i_output_parser.py` | Application-layer port for parsing/validating LLM output |
| `src/application/dtos.py` (extend) | Generation input DTOs: `GenerationInput`, `CurrentSuggestionInput`, `SimilarSuggestionInput`, `RegulationInput` |
| `src/application/use_cases/analyze_suggestion_use_case.py` | Generation orchestration use case |
| `src/infrastructure/configs/settings.py` (extend) | `GenerationSettings` — temperature, max_tokens, model name, token budgets |
| `src/infrastructure/services/llm/openai_llm_client.py` | Concrete LLM client adapter implementing `ILLMClient` |
| `src/infrastructure/services/llm/output_parser.py` | Concrete output parser implementing `IOutputParser` |
| `src/infrastructure/services/llm/templates/suggestion_analysis_system.jinja2` | System prompt template |
| `src/infrastructure/services/llm/templates/suggestion_analysis_user.jinja2` | User prompt template |
| `tests/unit/` (Generation tests) | Unit tests for prompt building, output parsing, use case logic |
| `tests/integration/` (Generation tests) | Integration tests for LLM client against mock provider |

### 3. Out-of-Scope Components

Do NOT create, modify, refactor, rename, or delete any of the following:

- **Embedding generation**: `IDenseEmbedder`, `OpenAIDenseEmbedder`, `EmbeddingSettings`, all files under `src/infrastructure/services/embeddings/`
- **Vector databases**: Qdrant client, collections, indexing
- **Vector search / similarity search / retrieval**: Qdrant queries, per-status partition search, chunk deduplication
- **Reranking**: any reranking logic
- **Document retrieval**: statute or suggestion retrieval from vector store
- **Regulation retrieval**: fetching regulations from any source
- **Data ingestion / ETL**: MSSQL extraction, Excel parsing, chunking pipelines
- **Crawling / importing historical suggestions**: ARQ worker ingestion tasks
- **Database management unrelated to Generation**: SQLAlchemy models, repositories, Alembic migrations
- **The existing .NET Suggestion System**: legacy Tavanir system
- **Frontend / UI**: any browser-facing code
- **Business workflows outside the Generation API**: committee workflows, suggestion lifecycle management
- **Authentication / authorization infrastructure**: `src/presentation/security.py`, API key validation
- **Deployment / infrastructure unrelated to Generation**: Docker, docker-compose, CI/CD
- **Other services or modules owned by other teams**

### 4. Code Ownership Rules

1. **Only modify files listed in Section 2.1 or Section 2.3.** Everything else is off-limits.
2. **If a file has mixed responsibilities**, identify only the Generation-related parts. Do not touch non-Generation code in the same file.
3. **If completing a task appears to require changing out-of-scope code**, stop and report the dependency. Do not modify the out-of-scope code.
4. **Do not silently expand scope.** Do not refactor neighboring modules because you are already working nearby.
5. **Do not "clean up" unrelated code.** Even if it looks wrong, ugly, or inconsistent.
6. **Do not rename unrelated classes, methods, files, variables, APIs, database objects, or modules.**
7. **Do not modify unrelated tests.**
8. **Prefer the smallest possible change** that satisfies the requirement.
9. **Avoid broad refactoring, unrelated improvements, and speculative abstractions.**

### 5. Boundary: Generation vs Retrieval / RAG

The Generation API **consumes** already-prepared information. It does **not** decide how that information was retrieved.

```text
                 Retrieval / RAG
                       │
        ┌──────────────┴──────────────┐
        │                             │
 Similar Suggestions          Relevant Regulations
        │                             │
        └──────────────┬──────────────┘
                       │
                       ▼
               Generation API
                       │
              ┌────────┴────────┐
              │                 │
           Prompt              LLM
              │                 │
              └────────┬────────┘
                       ▼
              Structured Output
```

**Rules:**

- The interface between Retrieval and Generation (the `GenerationInput` DTO) belongs to the Generation API scope.
- Do NOT modify Retrieval/RAG implementation code to support the Generation interface.
- If the Retrieval interface needs to change, report it as a cross-scope dependency.
- Generation may define **ports** (application-layer interfaces) that Retrieval adapters will satisfy, but must NOT implement or modify the Retrieval adapters themselves.

### 6. Boundary: Generation vs Existing Suggestion System

- The legacy .NET Suggestion System is an external upstream system. Do NOT modify it.
- The V2 Generation API operates on domain entities (`Suggestion`, `StatuteDocument`) that represent data **after** it has been ingested and stored.
- Generation does NOT interact with the legacy MSSQL database directly.
- Generation does NOT manage suggestion lifecycle, committee workflows, or business state.

### 7. Generation Input Contract (Preliminary)

The Generation API is designed around structured input. The input DTO models represent information **already retrieved** by the RAG layer:

```text
GenerationInput
├── current_suggestion: CurrentSuggestionInput
│   ├── id: str
│   ├── title: str
│   ├── problem: str | None
│   ├── solution: str | None
│   ├── date: str | None          # Shamsi date string
│   ├── status: SuggestionStatus
│   └── context_title: str | None
├── similar_suggestions: list[SimilarSuggestionInput]
│   ├── id: str
│   ├── title: str
│   ├── problem: str | None
│   ├── solution: str | None
│   ├── status: SuggestionStatus
│   ├── similarity: float
│   └── context_title: str | None
├── regulations: list[RegulationInput]
│   ├── id: str
│   ├── title: str
│   ├── content: str
│   └── citation: str | None
└── custom_instructions: str | None
```

These are starting points. Refine them as implementation progresses. Do not add fields merely because they exist in the source database — include information only when it has a meaningful purpose for generation.

### 8. Generation Output Contract

The Generation API returns a structured result. The existing `AnalyzeSuggestionResponse` is the baseline; it must be extended to include:

- **AI-generated analysis** (markdown text — already present as `analysis`)
- **Evidence/context used** — which similar suggestions and regulations the model relied on (partially present as ID lists)
- **Confidence/uncertainty** — where the model is uncertain or data was insufficient
- **Citations/references** — statute references used in the analysis

The LLM output must **not** be treated as the final organizational decision. The Generation API provides **decision support**, not authoritative business decisions.

### 9. Change Discipline

Before modifying any file:

1. Check Section 2.1 — is this file in my scope?
2. Check Section 2.3 — is this a file I am authorized to create?
3. If the file is in Section 2.2 — do NOT modify it.
4. If the file is not listed anywhere — treat it as out of scope.
5. If ownership is ambiguous — treat it as out of scope.
6. If an out-of-scope change appears necessary — stop and report it.

### 10. Out-of-Scope Dependency Report Template

If a task requires modifying code outside this scope, report it in this format:

```text
OUT-OF-SCOPE DEPENDENCY

File:
Reason:
Why the change appears necessary:
Recommended change:
Owner:
```

### 11. Final Verification Checklist

Before finishing any task:

- [ ] Every changed file is listed in Section 2.1 or is a new file per Section 2.3.
- [ ] No out-of-scope code was modified.
- [ ] No unrelated refactoring was introduced.
- [ ] No Retrieval/RAG implementation was changed.
- [ ] No embedding code was changed.
- [ ] No frontend or external Suggestion System code was changed.
- [ ] No `src/domain/` files were modified (shared, read-only).
- [ ] The implementation respects the documented ownership boundaries.