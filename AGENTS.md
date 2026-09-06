# AGENTS.md

Early-stage FastAPI project (Tavanir AI Assistant V2) on a Clean Architecture scaffold. Most of the architecture is NOT implemented yet.

## Repo state (read this first)
- Docs (`docs/architecture/clean_architecture.md`, `docs/architecture/high_level_architecture.md`, `docs/index.md`) describe the **target** design and name the domain "JadooChatRAG". Do not assume they match the code — most referenced files are empty placeholders. `high_level_architecture.md` marks each part `[implemented]`/`[planned]`; `docs/planning/v2_unimplemented_features.md` is the authoritative backlog.
- API wire contracts live in `docs/contracts/` (JSON:API envelope, camelCase external / snake_case internal mapping, internal error-code dictionary, API-key auth). Follow them when building the HTTP layer; auth is a **target** contract only — `src/presentation/security.py` is empty. Error codes map to real exceptions in `src/application/exceptions.py` / `src/domain/exceptions.py`.
- `docs/technology-stacks.md` lists verified deps (`[pinned]`/`[gap]`/`[planned]` legend) and confirms the `requirements.txt` gaps below. Docs are English; Persian domain terms (suggestion statuses, context titles) appear inline where the code uses them.
- Implemented so far: domain entities/enums/exceptions (`src/domain/`), application DTOs/exceptions + `IDenseEmbedder` port (`src/application/`), and infrastructure: settings + TEI/vLLM OpenAI-compatible client config, `BaseOpenAIService`, `OpenAIDenseEmbedder`, `LLMClientRegistry`, and DI wiring in `src/containers.py`.
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
- Commit messages: always short and meaningful (Conventional Commits, per `docs/contracts/02_Git_Commit_Convention.md`); add a body only when extra description is genuinely needed.