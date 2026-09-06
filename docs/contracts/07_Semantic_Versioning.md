# Semantic Versioning Approach for Tavanir AI Assistant V2

## Introduction

When managing software versioning (Semantic Versioning), the recurring question is: "What should constitute a Minor version?" The answer depends on the maturity stage of the product.

Two common approaches are discussed below, both applicable to the nature of this project (a RAG subsystem).

---

## 1. Approach One: "Every User Story is a MINOR"

In the active development phase (`0.x.x` or before `1.0.0`), every Story that creates a new capability can be a MINOR.

### Example in the development phase:

| Version | Story | Description |
|:---:|---|---|
| **0.1.0** | Suggestion analysis added | new capability |
| **0.2.0** | Real-time ingestion added | new capability, no breaking change |
| **0.3.0** | Historical extraction added | new capability |
| **0.4.0** | Statute ingestion added | new capability |
| **0.5.0** | Custom template management added | new capability |

### Advantages:
- Every User Story is tested and delivered independently.
- QA knows exactly what each version contains.
- Versioning is very precise and traceable.
- Rollback and change review are simpler.

### Drawback:
- As the system grows, the number of versions explodes.
- Differences between versions become trivial.
- Not meaningful for the API consumer.

> In a stable/production phase, the "every User Story = MINOR" model is not suitable; a MINOR should represent a meaningful change.

---

## 2. Approach Two: "Every Feature is a MINOR"

This model aligns more precisely with the core philosophy of Semantic Versioning.

### In this approach:
- Several User Stories together form a complete Feature.
- The Minor version only bumps when the Feature is fully usable.

### Example (project features):

| Feature | User Stories | Version |
|---|---|---|
| **Suggestion Analysis** | analyze endpoint + multi-status retrieval + structured output | **1.1.0** |
| **Suggestion Ingestion** | real-time ingest + delete + deduplication | **1.2.0** |
| **Historical Extraction** | MSSQL streaming + batch indexing + progress logging | **1.3.0** |
| **Statute Ingestion** | Excel parsing + statute indexing | **1.4.0** |
| **Template Management** | custom template persistence + atomic safe-write | **1.5.0** |

### Advantages:
- Versions are meaningful to the consumer.
- Each version represents complete value.
- Release management is simpler and more understandable.

---

## Conclusion

- **In the early development phase (before 1.0.0):**
  - Every User Story can be a MINOR.
  - **Goal:** precise control and granular development.
- **In the stable product phase (after 1.0.0):**
  - Every Feature should be a MINOR.
  - **Goal:** meaningful, understandable versions for the consumer (the upstream Tavanir system).

The choice between the two approaches depends on product maturity and the team's need for granular releases. Any incompatible change (Breaking Change) must always be marked by a **MAJOR** version bump.