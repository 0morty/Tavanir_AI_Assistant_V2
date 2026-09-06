# Git Commit Convention for Tavanir AI Assistant V2

## Introduction

This file defines a standard template for writing commit messages based on **Conventional Commits**. The goal is team-wide consistency, readability, and the possibility of automation (CHANGELOG generation and version control).

---

## General Shape

```text
<type>(<scope>): <short summary>
```

- **`type`**: the kind of change (`feat`, `fix`, `refactor`, `chore`, ...)
- **`scope`** *(optional)*: the part or layer of the system the change affects.
- **`summary`**: a short, clear description (under 72 characters, imperative mood).

---

## Change Types

```text
# feat:     add a new feature
# fix:      fix a bug
# docs:     documentation-only changes
# style:    formatting (no logic change)
# refactor: rewrite without changing behavior
# perf:     improve performance
# test:     add/update tests
# chore:    settings, dependencies, scripts
# ci:       CI/CD changes
# build:    build system or dependencies
# revert:   revert to a previous commit
```

---

## Suggested Scopes aligned with the Project Architecture

The project is built on Clean Architecture. The scopes below are matched to the real layers and concepts of the codebase:

| Scope | Description |
|---|---|
| `api` | Presentation layer / routers / schemas (FastAPI) |
| `worker` | Async worker (ARQ) |
| `ingestion` | Ingestion pipeline (extract/chunk/embed/index) |
| `retrieval` | Vector retrieval and deduplication (Qdrant) |
| `rag` | Analysis prompt assembly and answer generation |
| `embedding` | Embedder adapters / `IDenseEmbedder` implementations |
| `infra` | Settings, database, background tasks, storage |
| `config` | Application and environment settings |
| `docs` | Documentation |
| `ci` | CI/CD pipelines |
| `deps` | Project dependencies |

> A sub-scope can be added as needed, e.g. `ingestion/chunking`.

---

## Practical Examples

```text
feat(api): add analyze-suggestion endpoint
fix(worker): resolve embedding timeout on large batches
perf(retrieval): add parallel per-status search
refactor(rag): simplify analysis prompt assembly
docs: add contracting conventions
chore(deps): add openai and dependency-injector to requirements
ci: add docker image build workflow
```

For changes made before a release:

```text
chore(release): prepare version v1.2.0-rc.1
```

---

## Body / Footer Rules

> **Rule of thumb:** commit messages must be **short and meaningful**. Write a body only when extra description is genuinely necessary — the default is a single concise subject line.

```text
feat(ingestion): add zero-downtime suggestion update

Reindex is now performed as delete-then-reindex while the
master record stays active for reads.

BREAKING CHANGE: ingestion response shape changed
Fixes #42
```

- **Body**: explains the *what* and *why* (not the *how*), wrapped at 72 characters.
- **Footer**: `BREAKING CHANGE:` for incompatible changes, and an Issue link (`Fixes #123`).