# Project Documentation Hub

This directory is the central documentation repository for the **Tavanir AI Assistant V2** project.

Documentation follows the **Docs-as-Code** philosophy and the **Diátaxis Framework** (Tutorials, How-To Guides, Technical Reference, and Architectural Explanations).

---

## 📁 Scaffolding & Section Roadmap

Below is the directory structure for project documentation along with the purpose and intended contents of each section:

```
docs/
├── index.md                      # Central documentation hub (this file)
│
├── architecture/                 # 🏛️ System Design & Architectural Concepts
├── contracts/                    # 🤝 Team & API Conventions (Git Flow, Commits, JSON:API, Error Codes, ...)
├── adr/                          # 📜 Architecture Decision Records (ADRs)
├── ai_rag/                       # 🧠 AI, NLP & RAG Engine Specifications
├── database/                     # 💾 Relational Schemas, ORM Models & Migrations
├── guides/                       # 🛠️ Developer How-To Guides & Recipes
├── deployment/                   # 🚀 DevOps, Containerization & Infrastructure
├── documentation/                # 📚 Feature-Specific Technical Documentation (e.g. prompt_builder_entities.md)
│
├── planning/                     # 📌 Project-level Tracking, Roadmaps & Migration Backlogs
├── technology-stacks.md          # 🔬 Current & Target Technology Stack
└── notes/                        # 📝 Collaborative Notes, Spikes & Temporary Scratchpads
```

---

## 📖 Section Descriptions & Usage

### 1. `docs/architecture/` (System Design & Theoretical Blueprint)
* **Purpose**: High-level architectural explanations, component topologies, and Clean Architecture layer rules.
* **What will be stored here during development**:
  * **System Overview (`overview.md`)**: High-level data flow, C4 context diagrams, and component interactions between FastAPI, the Async Worker, Qdrant, and MSSQL.
  * **Clean Architecture Guide (`clean_architecture.md`)**: Strict inward dependency rules, layer boundaries (Domain, Application, Infrastructure, Presentation), and data mapping protocols across boundaries.

---

### 2. `docs/adr/` (Architecture Decision Records)
* **Purpose**: Captures significant architectural and technical decisions along with their context, rationale, and consequences.
* **What will be stored here during development**:
  * Individual decision files numbered sequentially (`0001_initial_architecture_and_stack.md`, `0002_use_qdrant_for_vector_search.md`, etc.).
  * Explanations of *why* specific technologies were chosen over alternatives (e.g., Qdrant vs. Chroma, LiteLLM vs. LangChain, async SQLAlchemy vs. sync).

---

### 3. `docs/contracts/` (Team & API Conventions)
* **Purpose**: Shared team conventions and API contracts with the upstream Tavanir system.
* **What is stored here**:
  * **Git Flow Guide (`01_Git_Flow_Guide.md`)**: Branch model (`master`/`develop`/`feature`/`release`/`hotfix`) for the single-module repo.
  * **Git Commit Convention (`02_Git_Commit_Convention.md`)**: Conventional Commits template with Clean Architecture scopes.
  * **Naming & Data Exchange (`03_Naming_And_Data_Exchange.md`)**: External `camelCase` / header `Title-Case` wire contract, mapped to the domain DTOs.
  * **JSON API Conventions (`04_JSON_API_Conventions.md`)**: Uniform JSON:API response envelope for success/failure.
  * **Internal Error Codes (`05_Internal_Error_Codes.md`)**: The `INTERNAL_CODE` dictionary anchored in `src/application/exceptions.py`.
  * **Authentication & Caller Identity (`06_Authentication_And_Caller_Identity.md`)**: Target service-level `X-API-Key` contract.
  * **Semantic Versioning (`07_Semantic_Versioning.md`)**: Versioning approach per project maturity.
  * **User Story Format (`08_User_Story_Format.md`)**: Standard user-story template with project roles.

---

### 4. `docs/ai_rag/` (AI, NLP & RAG Engine Engineering)
* **Purpose**: Technical documentation and formulas for all Artificial Intelligence, embedding, and retrieval components.
* **What will be stored here during development**:
  * **Embeddings (`embeddings.md`)**: Embedding model specifications (ParsBERT, Shafagh), vector dimensions (768-d), and L2 normalization formulas.
  * **Retrieval & Deduplication (`chunking_and_retrieval.md`)**: Parallel multi-status vector search (`اجرا شده`, `مصوب`, `رد`, etc.), candidate chunk deduplication rules, and statute lookup logic.
  * **Prompts & Rubrics (`prompts_and_templates.md`)**: Committee evaluation prompt schemas, structured JSON output formats, and dynamic template persistence rules.

---

### 5. `docs/database/` (Database & Storage Architecture)
* **Purpose**: Relational schema specifications, data dictionaries, and migration workflows.
* **What will be stored here during development**:
  * **Schema & Models (`schema_and_models.md`)**: Legacy MSSQL table references, CTE query optimizations, and legacy `StatusID` to Persian domain status mappings.
  * **Migrations (`migrations.md`)**: Alembic async migration rules, autogeneration guidelines, and execution commands.

---

### 6. `docs/guides/` (Developer How-To Guides)
* **Purpose**: Step-by-step instructions for onboarding developers and common development tasks.
* **What will be stored here during development**:
  * **Local Development (`local_development.md`)**: Environment setup (.venv, MS ODBC Driver 18, .env, running FastAPI and workers).
  * **Testing (`testing.md`)**: Guide to running unit, integration, and E2E tests, using `pytest-mock`, and measuring test coverage.
  * **Adding New Features (`adding_new_feature.md`)**: Step-by-step recipe for implementing a new feature across Domain, Application, Infrastructure, and Presentation layers.

---

### 7. `docs/deployment/` (DevOps, Configuration & Operations)
* **Purpose**: Operational specifications for containerization, production deployment, and runtime settings.
* **What will be stored here during development**:
  * **Docker & Compose (`docker_and_compose.md`)**: Multi-stage Docker build specifications and multi-container `docker-compose.yaml` setup.
  * **Environment Variables (`environment_variables.md`)**: Complete dictionary of all `.env` keys, defaults, and configuration options.

---

### 8. `docs/planning/` (Project Roadmaps & Migration Backlogs)
* **Purpose**: Project-level milestone tracking, legacy migration checklists, and backlog documentation.
* **What is stored here**:
  * **Migration Backlog (`v2_unimplemented_features.md`)**: Complete checklist of features, database extractors, vector adapters, and use cases transitioning from legacy V1 to V2 Clean Architecture.
  * **Roadmaps (`roadmap.md`)**: Multi-phase release plans, sprint priorities, and version targets.

---

### 9. `docs/technology-stacks.md` (Current & Target Stack)
* **Purpose**: Single reference of verified dependencies and planned technologies, with gaps flagged.
* **What is stored here**:
  * The de-facto library set from `requirements.txt` plus imported-but-missing packages (`openai`, `dependency-injector`) and target components (Qdrant, ARQ, MSSQL/Excel extractors).

---

### 10. `docs/notes/` (Temporary Collaborative Notes & Spikes)
* **Purpose**: Short-term collaborative working notes, investigation logs, benchmark spikes, and meeting minutes.
* **What will be stored here**:
  * Temporary research findings (e.g., `spike_parsbert_batch_encoding.md`, `meeting_notes_2026_09.md`).
  * **Lifecycle Rule**: Once a spike or investigation is complete, distill any permanent findings into a formal guide (`docs/guides/`) or ADR (`docs/adr/`), then delete the temporary note.
