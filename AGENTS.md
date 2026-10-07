# AGENTS.md

FastAPI project (Tavanir AI Assistant V2) on a Clean Architecture scaffold. The LLM / Generation API has implemented orchestration, adapters, HTTP integration, and tests; source remains authoritative for other subsystem status.

## Repo state (read this first)
- Architecture docs include target design and the domain name "JadooChatRAG". Verify implementation from code. Generation's current reference is `docs/documentation/llm_generation_api.md`; remaining Generation work is in `docs/next_steps.md` and `docs/planning/v2_unimplemented_features.md`.
- API wire contracts are in `docs/contracts/`: JSON response envelopes, camelCase external / snake_case internal mapping, error codes, and `X-API-Key`. The existing security implementation is shared and outside Generation ownership.
- Implemented Generation: input/output DTOs and ports; section/context allocation and overflow; reference/citation enrichment; prompt preparers/configuration; role-bearing request builder; pooled OpenAI-compatible client; output parsers; `GenerateSuggestionUseCase`; `StructureIdeaUseCase`; and composition-root providers.
- `POST /api/v1/suggestions/analyze` calls the injected generator when usable prepared evidence exists and returns its parsed answer/citations/uncertainty. No-evidence requests deliberately short-circuit without Generation.
- `POST /api/v1/suggestions/expand-suggestion` accepts `description`, validates at most 512 model tokens, executes the full section/context/chat/parser pipeline, and returns five fields. Internal `StructureIdea*` names remain.
- `src/main.py` exposes `create_app` and `app`; presentation lifespan initializes and wires resources. Do not describe all presentation code, use cases, or tests as empty scaffolds.
- Current working-tree caveat: the expansion prompt example has Persian markers, but the parser's `IDEA_OUTPUT_MARKERS` are English. Preserve the original exact marker contract in Generation work; the discrepancy is tracked in the Generation guide/backlog. Documentation-only tasks must not silently fix source edits.
- Documentation descriptions are English. Persian prompt instructions and domain terms can appear where code requires them. Keep unrelated existing working-tree changes intact.

## Environment gotchas
- `openai`, `dependency-injector`, and `transformers` are declared in `requirements.txt`; install the declared environment before importing the container. Declaration does not prove installation.
- Settings (`src/infrastructure/configs/settings.py`) load `.env` from the repo root via `Path(__file__).resolve().parents[3]`. Defaults target local TEI (localhost:8080) and vLLM (localhost:8000) with an `EMPTY` API key; providers are configured through `TEI_HOST/TEI_PORT`/`VLLM_HOST/VLLM_PORT`. Generation defaults to `Qwen/Qwen2.5-7B-Instruct`; environment overrides must match the actual served model.
- Production Generation uses `QwenTokenizer` over an injected fast tokenizer loaded from `assets/tokenizers/Qwen2.5-7B-Instruct` with `local_files_only=True`. Keep idea validation and ContextBuilder on the same tokenizer.
- Always run commands from the repository root because internal imports are absolute (`from src....`).

## Tests / tooling
- `pytest.ini` and `tests/conftest.py` exist; asyncio mode is strict. Generation unit/integration tests are implemented. Use injected fakes in unit tests and mock provider transport in controlled integration tests.
- Expansion HTTP tests exercise the actual Generation pipeline with a local Qwen tokenizer and mocked provider, without production lifespan. Analyze presentation tests override its use case; unit tests cover the real generator handoff.
- Database tests require their explicit configured opt-in. Do not run uncontrolled external-service checks or claim live model/API verification from mocks. Record fresh results and distinguish historical live evidence in `docs/documentation/llm_generation_test_summary.md`.

## Migrations
- Alembic (async) is scaffolded but not wired: `migrations/env.py` has `target_metadata = None` and `alembic.ini` still has the placeholder `sqlalchemy.url`. No models or version files exist.

## Conventions
- Clean Architecture dependency rule: `src/domain/` must stay pure stdlib (no FastAPI, SQLAlchemy, Pydantic); outer layers depend inward through ports under `src/domain/interfaces/` and `src/application/interfaces/`.
- The project must use Dependency Injection (DI) as a core architectural principle. **Follow the Dependency Injection policy below for every component you add or touch.**
- Domain uses Persian suggestion statuses: `SuggestionStatus` in `src/domain/enums.py` converts legacy `status_id` ints and Persian titles via `from_id()`/`from_string()`.
- **Git commits**: Never create git commits automatically. Only commit when explicitly instructed by the user. When asked to commit, generate short and meaningful commit messages (Conventional Commits, per `docs/contracts/02_Git_Commit_Convention.md`).

### Dependency Injection policy

The project follows a .NET-style DI procedure: components are **composed**, never assembled by themselves. Every component receives its collaborators through its constructor, depends on an abstraction where a seam is warranted, and is registered in the single composition root (`src/containers.py`). There are four mandatory steps for any dependency, in order: **define → inject → compose → test**.

#### 1. Define — where dependencies are declared as abstractions
- Application-layer ports live in `src/application/interfaces/` as `I<Capability>` ABCs. Generation ports include `ICapacityAllocator`, `IDemandAllocator`, `IRedistributionAllocator`, `IOverflowStrategyDispatcher`, `IContextBuilder`, `ITemplateValidator`, `IReferenceGenerator`, `ILLMClient`, `ILLMRequestBuilder`, `IPromptSection`, `ISuggestionPromptPreparer`, `IOutputParser`, `IGenerateSuggestionUseCase`, `IStructureIdeaUseCase`, and `IStructuredIdeaOutputParser`; `CompressibleSection` is the overflow capability marker. Import from the defining module when a port is not exported by `__all__` (notably `IOutputParser`). Other subsystem ports retain their existing ownership.
- Domain-boundary ports live in `src/domain/interfaces/` (`IUnitOfWork`, `ISuggestionVectorRepository`, `IRegulatoryVectorRepository`, `IVectorRepository`, `ISuggestionRepository`). Domain-owned capabilities that Generation consumes are abstractions under `src/domain/context/` (`Tokenizer`, `Summarizer`).
- A concrete class implements its interface explicitly — `class CapacityAllocator(ICapacityAllocator)`, `class TemplateValidator(ITemplateValidator)` — and lives in the layer it belongs to (application implementation or infrastructure adapter).
- Interfaces must stay dependency-light: import only what is needed at runtime; reference heavier sibling types under `TYPE_CHECKING` with `from __future__ import annotations` (see `src/application/interfaces/i_context_builder.py`).
- Do **not** invent an interface for pure data (DTOs in `src/application/dtos.py`), configuration dataclasses (`ReferenceGenerationPrompts`, settings), or third-party libraries. Interfaces are for swappable/injected collaborators at architectural boundaries.

#### 2. Inject — how collaborators enter a component
- **Constructor injection only.** No service locators, no hidden global singletons, no module-level mutable instances (settings singletons are the allowed exception).
- Swappable collaborators are constructor parameters typed against the interface and **required** — never `= None` followed by an internal `else Concrete()` fallback. Examples already in the codebase:
  - `ContextBuilder(*, tokenizer: Tokenizer, capacity_allocator: ICapacityAllocator, dispatcher: IOverflowStrategyDispatcher)`
  - `CapacityAllocator(demand_allocator: IDemandAllocator, redistribution_allocator: IRedistributionAllocator)`
  - `LLMBaseReferenceGenerator(llm_client, *, validator: ITemplateValidator, context_builder: IContextBuilder, cache: ReferenceCache, max_attempts=3, max_tokens=2048)`
  - `LLMClientRegistry(client_factory: Callable[[str, float], AsyncOpenAI])`
- Store the injected reference on `self._<name>` and never re-instantiate or default it later.
- Permitted internal construction covers immutable configuration data, per-call DTO/prompt/section data (`PromptBuilder`, sections, strategy stacks), and existing documented default strategies behind an explicit seam (`ReferencedSection.reference_generator`, default `PromptSection` stacks). Per-call data construction is not permission to construct runtime service collaborators. **If you add a new collaborator, add it as a required constructor parameter — do not add another fallback default.**
- A component must never import or instantiate a concrete implementation from an outer layer (`src/application` must never import `src.infrastructure`).

#### 3. Compose — how the graph is assembled
- `src/containers.py` (`class Container(containers.DeclarativeContainer)`) is the **single composition root**. Every runtime dependency is resolvable from here.
- Register each dependency by name with the interface as the provider type, passing the concrete class and its wired dependencies to the provider: `provider_name: providers.Provider[IInterface] = providers.Singleton(Concrete, dep=other_provider, ...)` (example: `capacity_allocator: providers.Provider[ICapacityAllocator] = providers.Singleton(CapacityAllocator, demand_allocator=..., redistribution_allocator=...)`).
- Wire providers reference other providers by attribute name; pass static values/factories with `providers.Object`/`providers.Callable`; manage lifecycle with `providers.Resource` (`client_registry`, `embedding_client`); use `providers.Factory` for per-call construction (`unit_of_work`).
- The container is booted exactly once, in `src/presentation/lifespan.py`: `container = Container()`, `await container.init_resources()`, `container.wire(packages=["src.presentation.routers"])`, stored on `app.state.container`. `Container()` must never be constructed inside a service, router, or use case, and `app.state.container` is never used to manually resolve dependencies in application code.
- Generation tokenizer, `context_builder`, shared `llm_client`, request builder, parsers, and both Generation use cases are wired in the composition root. Resource teardown closes pooled clients and their event-loop thread. Remaining gaps include full chat-framing/completion-reserve accounting and expansion mock-mode parity; do not treat these as missing core DI wiring.

#### 4. Test DI behavior
- Unit tests construct components with test doubles that implement the relevant interface — recording subclasses (`RecordingCapacityAllocator(CapacityAllocator)`, `RecordingDispatcher(OverflowStrategyDispatcher)`, `StrictValidator(TemplateValidator)`) or fakes (`FakeTokenizer(Tokenizer)`, `CallingContextBuilder`). Do not build the real container in unit tests.
- Changing a constructor signature requires updating every call site, including tests. Add a guard test so a required collaborator rejects its absence (expect `TypeError`), and prefer injection tests that prove the injected fake (not a default) is used.

#### 5. Anti-patterns (must not appear)
- `def __init__(self, dep: X | None = None)` followed by `self._dep = dep if dep is not None else X()`.
- Instantiating collaborators inline in methods (service-locator style).
- Importing a concrete infrastructure/implementation class into an application piece just to construct it.
- Resolving dependencies manually from `app.state.container` inside a service/router/use case.
- Module-level mutable singletons other than settings.
- Heavy runtime imports used only for type annotations (use `TYPE_CHECKING`).

---

## LLM / Generation API — Developer Scope

This section defines the exclusive ownership boundary for the **LLM / Generation API** layer. It is a hard constraint that takes precedence over convenience, implementation speed, or architectural cleanup.

### 1. Responsibility

The LLM / Generation API accepts either a raw idea or structured information already prepared upstream. It owns prompt/context preparation, LLM invocation, parsing, and Generation result mapping. It does not own retrieval or decide how evidence was obtained. Specifically:

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

#### 2.1 Already Implemented (Generation-owned portions may be modified)

| File / directory | Generation ownership |
|---|---|
| `src/application/dtos.py` | Generation input/result DTOs, `PreparedGeneration`, `StructureIdeaDTO`, `StructuredIdeaResult`, and Generation fields of `AnalyzeSuggestionResponse`; unrelated DTOs remain out of scope. |
| `src/application/exceptions.py` | LLM hierarchy, output/citation errors, prompt/evidence budget errors, duplicate evidence, idea validation/length errors, and Generation summarization errors. Do not modify application base or embedder exceptions. |
| `src/application/interfaces/` | Generation ports named in the DI policy; unrelated retrieval, embedding, storage, and queue ports remain out of scope. |
| `src/application/context/` | Prompt sections, reference-aware collections, allocation, ContextBuilder, overflow capabilities/dispatcher, and fitted-section results. New Generation sections belong here. |
| `src/application/prompt/` | PromptBuilder ordering/concatenation, SuggestionPromptPreparer, SuggestionAnalysisPromptConfig, StructureIdeaPromptConfig, and exact expansion marker constants. Budget processing belongs to ContextBuilder. |
| `src/application/reference/` | Generation reference entities, generators, validator, template cache, and supporting formatting. |
| `src/application/llm/` | LLMRequestBuilder and role mapping from processed ContextBuilder output. |
| `src/application/use_cases/generate_suggestion_use_case.py` | Final evidence-based Generation orchestration. |
| `src/application/use_cases/structure_idea_use_case.py` | Idea validation and full section/context/chat/strict-parser orchestration. |
| `src/infrastructure/configs/settings.py` | `LLMSettings`, `GenerationSettings`, their singletons, and the Generation prompt-budget field of `SuggestionAnalysisSettings`. Do not change core, embedding, or retrieval settings. |
| `src/infrastructure/configs/llm_provider_configs.py` | LLMProvider, APIKeyProvider, AsyncOpenAIClientFactory; preserve existing embedding consumers. |
| `src/infrastructure/services/base_openai_service.py` | Shared compatible-provider error handling; preserve embedding behavior. |
| `src/infrastructure/services/llm/` | Shared Generation client/registry, JSON output parser, strict idea output parser, and Generation helpers. |
| `src/infrastructure/services/tokenizers/qwen_tokenizer.py` | Generation model-token counting/encoding adapter; domain tokenizer abstraction remains read-only. |
| `src/infrastructure/services/summarizers/` | Generation context summarization adapters only. |
| `tests/unit/`, `tests/integration/` | Generation tests only; do not modify unrelated test cases or shared test configuration without explicit authorization. |

#### 2.2 Shared components (precise exceptions to read-only ownership)

| File | Allowed Generation change |
|---|---|
| `src/domain/entities.py`, `src/domain/enums.py`, `src/domain/exceptions.py`, `src/domain/context/` | Read-only. Consume existing domain entities and abstractions; do not modify them. |
| `src/containers.py` | Add or adjust Generation providers only. Never remove/restructure embedder, retrieval, database, queue, or other teams' providers. |
| `src/application/use_cases/analyze_suggestion_use_case.py` | Generator injection, prepared GenerationInput handoff, and mapping parsed Generation results only. Normalization, retrieval, reranking, pooling, hydration, and their existing policies remain out of scope. |
| `src/presentation/routers/v1/suggestion.py` | Expansion route and Generation-related response mapping only. Existing retrieval orchestration and mutation routes remain out of scope. |
| `src/presentation/schemas/v1/analyze_suggestion_response.py` | Generation answer, uncertainty, and cited-evidence response fields only. |
| `src/presentation/schemas/v1/structure_idea_request.py`, `src/presentation/schemas/v1/structure_idea_response.py` | Expansion request/response contract. |
| `src/presentation/exception_handlers.py` | Generation exception mappings only; preserve security, domain, retrieval, and embedding mappings. |
| Documentation and `AGENTS.md` | Generation-specific documents/instructions and Generation paragraphs of shared docs when requested. Do not revise retrieval sections or unrelated working-tree documentation. |

These exceptions identify existing mixed Generation integration points; they do not authorize changes to the rest of a shared file. `src/presentation/security.py`, lifespan/mock infrastructure, and application startup remain outside Generation source ownership unless separately authorized.

#### 2.3 Planned work (not implemented; not required for the existing endpoints)

- Optional Jinja prompt files under `src/infrastructure/services/llm/templates/` are a target alternative. Current prompts are Python configuration dataclasses; do not claim the Jinja files exist or are required.
- Future supplied-regulation rendering/citation support belongs to Generation sections, DTOs, preparers, parsers, and their tests. Fetching regulations remains upstream ownership.
- Full model-context accounting, final-output retry policy, and Generation observability must reuse existing injected boundaries; do not create duplicate clients/context pipelines.

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

1. **Only modify Generation-owned files/portions in Section 2.1, the explicit Generation exceptions in Section 2.2, or authorized planned work in Section 2.3.** Everything else is off-limits.
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

### 7. Implemented Generation Input Contracts

Evidence-based Generation consumes `GenerationInput`:

```text
GenerationInput
├── current_suggestion: CurrentSuggestionInput
│   ├── title, problem, solution: str          # required, substantive
│   ├── id: str | None                        # optional; no date field
│   ├── status: SuggestionStatus = PENDING
│   └── context_title: str | None
├── similar_suggestions: list[SimilarSuggestionInput]
│   ├── id, title, problem, solution: str
│   ├── status: SuggestionStatus
│   ├── similarity: float                     # finite; raw scores may exceed [0, 1]
│   ├── context_title: str | None
│   └── reference: Reference | None
└── regulations: list[RegulationInput] = []
    ├── id, title, content: str
    └── citation: str | None
```

Regulations are accepted as DTO data but are not currently rendered/cited by SuggestionPromptPreparer. `PreparedGeneration` carries fitted context and a direct retained `citation_id → original item` map; do not replace that map with intermediate source IDs.

Idea expansion independently consumes `StructureIdeaDTO(description: str)`. Trim and validate its maximum 512 model tokens using the injected Generation tokenizer before sending it to USER-INPUT. Both flows must use PromptBuilder sections, ContextBuilder processing, the existing request builder, and the shared provider abstraction.

### 8. Implemented Generation Output Contracts

- Analyze's model completion is JSON: nonblank `answer`, `citations` list, optional `uncertainty`. Parse and resolve citations against the **retained** map. HTTP `analysis` contains the validated answer on the normal path; no usable evidence yields diagnostic text without a model call.
- `citedSuggestionIds` identifies actually cited original suggestions. Existing status-grouped candidate lists are separate. `groundingRatio` is citation coverage, not calibrated model confidence; `isFallbackMode` reflects upstream fallback. Regulation citations are not connected and `appliedStatuteIds` is empty.
- Expansion's model completion is plain text, in the exact order `{title}`, `{current problem}`, `{solutions}`, `{advantage}`, `{disadvantage}`, separated by exactly `\n***\n`. Preserve these English machine-readable labels even with Persian instructions/content. The HTTP envelope exposes `title`, `currentProblem`, `solution`, `advantage`, `disadvantage`, not the raw completion. The current working-tree prompt/marker disagreement must be resolved before claiming this contract succeeds against a real model.
- Malformed output/citations map to HTTP 500 `GENERATION_FAILED`; no unvalidated completion is returned as success. Final Generation currently has no semantic-output retry loop.

The output provides decision support, never an authoritative organizational decision. See `docs/documentation/llm_generation_api.md` for exact contracts, errors, budgets, and observed gaps.

### 9. Change Discipline

Before modifying any file:

1. Check Section 2.1 — is this file in my scope?
2. Check Section 2.3 — is this a file I am authorized to create?
3. If the file is in Section 2.2 — change only an explicitly allowed Generation portion; all other portions are read-only.
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

- [ ] Every changed file/portion falls under Section 2.1, an explicit Generation exception in Section 2.2, or authorized Section 2.3 work.
- [ ] No out-of-scope code was modified.
- [ ] No unrelated refactoring was introduced.
- [ ] No Retrieval/RAG implementation was changed.
- [ ] No embedding code was changed.
- [ ] No frontend or external Suggestion System code was changed.
- [ ] No `src/domain/` files were modified (shared, read-only).
- [ ] The implementation respects the documented ownership boundaries.
