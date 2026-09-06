# User Story Standard Format for Tavanir AI Assistant V2

## Introduction

A **User Story** is one of the core concepts of Agile methodology, expressing a system requirement from the stakeholder's point of view. The goal is to focus on the real need and the value a capability creates.

---

## Standard User Story Format

The most common template:

```text
As a <Role>,
I want to <Goal>,
So that <Benefit>.
```

Or in single-line form:
> **As a `<Role>`, I want to `<Goal>` so that `<Benefit>`.**

---

## User Story Components

### 1. Role (`As a <Role>`)
Identifies who uses the capability. Common roles in this project:
- `Upstream System` (the mandated caller / the legacy Tavanir suggestion system)
- `Committee Analyst` (the domain expert who reviews suggestions)
- `Operator` (platform administrator / support)
- `Developer` (service developer)

### 2. Goal (`I want to <Goal>`)
States what the user wants to do.
- `analyze an incoming suggestion`
- `ingest a suggestion in real time`
- `extract historical suggestions from the legacy database`
- `load organizational statutes from Excel files`
- `manage the custom prompt template`

### 3. Benefit (`So that <Benefit>`)
Explains what value performing this brings.
- `so that similar precedents and applicable statutes are surfaced.`
- `so that it becomes retrievable by the analysis pipeline.`
- `so that the committee can review historical decisions.`
- `so that the analysis is grounded in current regulations.`

---

## Practical Examples (aligned with the project backlog)

| No. | Topic | Standard User Story |
|:---:|---|---|
| **1** | Suggestion analysis | **As an** Upstream System, **I want to** analyze an incoming suggestion **so that** similar precedents and applicable statutes are surfaced. |
| **2** | Real-time ingestion | **As an** Upstream System, **I want to** ingest a suggestion in real time **so that** it becomes retrievable by the analysis pipeline. |
| **3** | Historical extraction | **As an** Operator, **I want to** extract historical suggestions from the legacy MSSQL database **so that** the committee can review past decisions. |
| **4** | Statute ingestion | **As an** Operator, **I want to** load organizational statutes from Excel files **so that** the analysis is grounded in current regulations. |
| **5** | Custom template | **As a** Developer, **I want to** manage the custom prompt template **so that** evaluation instructions can be updated without a deployment. |
| **6** | Error contract | **As a** Developer, **I want to** receive a consistent error envelope **so that** clients handle failures predictably. |

---

## Notes

- Every User Story must be independent, testable, and have clear value.
- Roles must be aligned with the actual stakeholders of the project (not with an end-user product layer), because the service has no end-user layer.
- User Story numbering (e.g. `US-100`) can be used in branch names (per file 01).