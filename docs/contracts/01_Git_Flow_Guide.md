# Git Flow Guide for Tavanir AI Assistant V2

This document is a complete guide to using **Git Flow** in the **Tavanir AI Assistant V2 (JadooChatRAG)** project — a RAG subsystem based on FastAPI — from the start of development through release.

> **Architecture note:** This is a single-module, standalone repository — it has no Monorepo structure. Branch naming is therefore done **without** an application-name prefix.

## 1. Introduction

Git Flow is an organized method for managing branches that keeps development, release, and maintenance regular.

| Branch | Description |
|---|---|
| `master` | Released, stable versions (Production) |
| `develop` | Latest changes ready for release (current working branch) |
| `feature/*` | New feature development (e.g. `feature/suggestion-analysis`) |
| `release/*` | Release preparation, bug fixes, and CHANGELOG updates |
| `hotfix/*` | Immediate production fixes (e.g. `hotfix/fix-api-key-validation`) |

## 2. Getting Started

All development must branch from `develop`:

```bash
git checkout develop
git pull origin develop
git checkout -b feature/suggestion-analysis
```

## 3. Creating a New Feature

```bash
# Develop the feature and commit changes (per Commit Convention — file 02)
git add .
git commit -m "feat(api): add analyze-suggestion endpoint"

# Push the feature branch
git push origin feature/suggestion-analysis
```

After review and approval by a Reviewer, the branch is merged into `develop`.

## 4. Creating a Release

```bash
git checkout develop
git pull origin develop
git checkout -b release/v0.1.0
```

Set the version per Semantic Versioning (file 07) and update `CHANGELOG.md`:

```bash
git add CHANGELOG.md
git commit -m "chore: prepare release v0.1.0"
git checkout master
git merge release/v0.1.0
git tag v0.1.0
git push origin master --tags
git checkout develop
git merge release/v0.1.0
git push origin develop
```

## 5. Creating a Hotfix

```bash
git checkout master
git pull origin master
git checkout -b hotfix/fix-api-key-validation
# Fix the problem
git commit -m "fix(api): correct API key validation"
git checkout master
git merge hotfix/fix-api-key-validation
git tag v0.1.1
git push origin master --tags
git checkout develop
git merge hotfix/fix-api-key-validation
git push origin develop
```

## 6. Recommendations

- Always pull `develop` before creating a new branch.
- Update the CHANGELOG for every release.
- Set the version according to Semantic Versioning (MAJOR.MINOR.PATCH) — see file 07.
- Use a Pull Request / Merge Request for merging feature/release branches.
- Each branch should cover a single topic only (e.g. only ingestion, or only retrieval).

## 7. Quick Command Samples

```bash
# Feature
git checkout develop && git pull
git checkout -b feature/statute-ingestion
git commit -am "feat(ingestion): parse statute excel files"
git push origin feature/statute-ingestion

# Release
git checkout -b release/v1.2.0
git commit -am "chore: update CHANGELOG & version"
git checkout master && git merge release/v1.2.0 && git tag v1.2.0
git push origin master --tags
git checkout develop && git merge release/v1.2.0 && git push origin develop

# Hotfix
git checkout -b hotfix/fix-embedding-timeout
git commit -am "fix(worker): resolve embedding timeout on large batches"
git checkout master && git merge hotfix/fix-embedding-timeout && git tag v1.2.1
git push origin master --tags
git checkout develop && git merge hotfix/fix-embedding-timeout && git push origin develop
```