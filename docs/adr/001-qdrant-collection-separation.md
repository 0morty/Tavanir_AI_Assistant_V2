# ADR-001: Separate Qdrant Collections for Suggestions and Regulatory Knowledge

- **Status:** Accepted
- **Date:** 2026-09-05
- **Decision Owners:** Tavanir AI Assistance Engineering Team
- **System:** دستیار هوشمند سامانه نظام پیشنهادات
- **Component:** RAG Retrieval Layer / Qdrant Vector Database

---

## 1. Context

The Tavanir AI Assistance system uses a Retrieval-Augmented Generation (RAG) architecture to assist in evaluating newly submitted suggestions.

For every incoming suggestion, the system performs two fundamentally different retrieval tasks:

1. **Historical suggestion retrieval**
   - Search previous registered suggestions.
   - Find semantically similar suggestions.
   - Detect potentially duplicated or substantially overlapping proposals.
   - Retrieve historical precedents that may help evaluate the new suggestion.

2. **Regulatory knowledge retrieval**
   - Search statutes, regulations, directives, procedures, guidelines, and other organizational knowledge.
   - Find documents applicable to the subject of the incoming suggestion.
   - Determine whether the suggestion may conflict with binding requirements.
   - Retrieve non-binding guidance that may help the generation model understand how the suggestion should be evaluated.

The high-level retrieval architecture is therefore:

```text
                         Incoming Suggestion
                                │
                ┌───────────────┴───────────────┐
                │                               │
                ▼                               ▼
      Historical Retrieval            Regulatory Retrieval
                │                               │
                ▼                               ▼
     Previous Suggestions          Statutes / Regulations /
                                   Directives / Guidelines
                │                               │
                ▼                               ▼
      Similarity / Duplicate          Applicability /
          Detection                   Guidance Retrieval
                │                               │
                └───────────────┬───────────────┘
                                ▼
                         Evidence Assembly
                                │
                                ▼
                          Generation Model
```

Although these data sources can technically be stored in a single Qdrant collection and separated using payload filters, their retrieval purposes, ranking semantics, metadata, lifecycle, and expected future optimization requirements differ.

A collection architecture must therefore be selected before implementation.

---

## 2. Decision

The system will use **two separate Qdrant collections**:

```text
tavanir_suggestion_v1
```

for historical registered suggestions, and:

```text
tavanir_regulatory_knowledge_v1
```

for regulatory and guidance knowledge.

The resulting storage architecture is:

```text
Qdrant
│
├── tavanir_suggestion_v1
│   │
│   ├── Previous registered suggestions
│   │
│   ├── Dense vectors
│   ├── Sparse vectors
│   └── Suggestion-specific metadata
│
└── tavanir_regulatory_knowledge_v1
    │
    ├── Statutes
    ├── Regulations
    ├── Directives
    ├── Procedures
    ├── Guidelines
    │
    ├── Dense vectors
    ├── Sparse vectors
    └── Regulatory-specific metadata
```

Both collections may initially use the same embedding and retrieval technologies, including:

```text
Dense Embedding:
google/embeddinggemma-300m

Sparse Retrieval:
Native Persian BM25 sparse representation

Vector Database:
Qdrant

Retrieval:
Hybrid Dense + Sparse Search

Candidate Fusion:
RRF or another evaluated fusion strategy

Reranker:
BAAI/bge-reranker-v2-m3
```

However, the two collections will remain independently configurable so their retrieval pipelines can evolve separately.

---

## 3. Decision Drivers

The decision is primarily driven by the following requirements.

### 3.1 Different Retrieval Objectives

The two collections answer fundamentally different questions.

`tavanir_suggestion_v1` answers:

> Which previous suggestions are semantically similar to the incoming suggestion?

Its primary retrieval objectives include:

- similarity detection;
- duplicate detection;
- identification of historical precedent;
- discovery of related previously evaluated proposals.

`tavanir_regulatory_knowledge_v1` answers:

> Which rules, statutes, directives, procedures, or guidelines are applicable to this suggestion?

Its primary objectives include:

- regulatory applicability;
- identification of potentially conflicting requirements;
- retrieval of binding requirements;
- retrieval of relevant organizational guidance;
- retrieval of contextual information required for evaluation.

Therefore, similarity has different semantic meanings in the two corpora.

A historical suggestion can be highly relevant because it expresses essentially the same idea.

A regulation can be highly relevant even when its wording is substantially different from the incoming suggestion.

For example:

```text
Incoming suggestion:

"Use drones for inspection of transmission lines."
```

A historically similar suggestion may contain:

```text
"Use unmanned aerial vehicles for inspecting high-voltage infrastructure."
```

while an applicable regulation may instead contain:

```text
"Requirements for aerial operations near high-voltage electrical infrastructure."
```

The first retrieval task is primarily about semantic similarity.

The second is about applicability and authority.

These should therefore be treated as separate retrieval contracts.

---

## 4. Why a Single Collection with Prefiltering Was Not Selected

A technically valid alternative is:

```text
tavanir_knowledge_v1
```

containing both corpora, with metadata such as:

```json
{
  "source_group": "suggestion"
}
```

or:

```json
{
  "source_group": "regulatory"
}
```

The application could then execute two filtered searches:

```text
source_group = suggestion
```

and:

```text
source_group = regulatory
```

This approach would prevent suggestions and regulations from competing for the same `top_k` retrieval positions.

Therefore, a single collection with mandatory filtering is not considered technically incorrect.

It was not selected because it introduces unnecessary coupling between two retrieval systems that are already known to serve different purposes.

The two-collection architecture provides greater flexibility for future tuning, deployment, scaling, migration, and maintenance.

---

## 5. Independent Retrieval Configuration

Initially, both collections may use identical retrieval parameters.

For example:

```text
Dense model:       EmbeddingGemma
Sparse model:      Persian BM25
Distance metric:   Cosine
Fusion:            RRF
Reranker:          BGE reranker
```

However, evaluation may later show that optimal retrieval settings differ.

For example:

```text
tavanir_suggestion_v1

Dense candidates:       60
Sparse candidates:      40
Fusion candidates:      30
Reranker candidates:    20
Final results:           5
```

while:

```text
tavanir_regulatory_knowledge_v1

Dense candidates:       30
Sparse candidates:      70
Fusion candidates:      40
Reranker candidates:    25
Final results:           8
```

The actual values must be determined through retrieval evaluation and must not be hard-coded based solely on assumptions.

The important architectural requirement is that each retrieval pipeline can be optimized independently.

---

## 6. Independent Vector Index Configuration

Using separate collections allows vector database configuration to evolve independently.

Future evaluation may indicate different requirements for:

- HNSW configuration;
- indexing thresholds;
- quantization;
- optimizer configuration;
- shard count;
- replication;
- on-disk vector storage;
- memory allocation;
- indexing strategy.

For example:

```text
tavanir_suggestion_v1
```

may eventually become substantially larger and more write-intensive than:

```text
tavanir_regulatory_knowledge_v1
```

The suggestion collection can then be optimized specifically for its workload without changing the regulatory collection.

---

## 7. Independent Sparse Retrieval Statistics

The linguistic characteristics of suggestions and regulatory documents differ.

Suggestions may contain:

- employee terminology;
- operational descriptions;
- informal or semi-formal Persian;
- problem descriptions;
- proposed solutions;
- department-specific terminology.

Regulatory documents may contain:

- formal administrative terminology;
- legal terminology;
- standardized expressions;
- article and clause terminology;
- mandatory language;
- organizational procedural language.

Because sparse retrieval methods such as BM25 depend on corpus-level term statistics, the two corpora may benefit from maintaining independent statistical models.

Conceptually:

```text
Suggestion corpus
        │
        ▼
Suggestion BM25 statistics
```

and:

```text
Regulatory corpus
        │
        ▼
Regulatory BM25 statistics
```

This prevents the vocabulary distribution of one corpus from unnecessarily influencing sparse retrieval behavior in the other.

---

## 8. Different Chunking Strategies

The two collections also use different source structures.

### 8.1 Suggestion Chunking

Registered suggestions have structured application fields such as:

```text
title
current_problem
solution
committee_scrutiny_description
```

The chunking strategy may therefore use field-aware or parent-child chunking.

Example:

```text
Suggestion
│
├── Parent representation
│
├── Title / summary representation
├── Current problem chunk
├── Proposed solution chunk
└── Committee scrutiny chunk
```

### 8.2 Regulatory Knowledge Chunking

Regulatory documents may contain:

```text
Document
│
├── Chapter
│   ├── Section
│   │   ├── Article
│   │   │   ├── Paragraph
│   │   │   └── Table
│   │   └── Article
│   └── Section
└── Appendix
```

Their ingestion pipeline therefore requires structural document parsing and potentially table-aware chunking.

Because the two corpora already require different ingestion and reconstruction logic, separating their storage boundaries keeps the architecture aligned with their domain models.

---

## 9. Different Metadata Schemas

Different metadata schemas are **not themselves the reason for using two collections**.

Qdrant payloads can support different metadata structures inside one collection.

The separation is instead based on retrieval and operational requirements.

Nevertheless, each collection will maintain metadata appropriate to its domain.

### 9.1 `tavanir_suggestion_v1`

Example metadata:

```json
{
  "suggestion_id": "SUG-12345",
  "source_type": "suggestion",
  "chunk_id": "SUG-12345-solution-01",
  "parent_id": "SUG-12345",

  "status": "مصوب",
  "status_id": 1,

  "context_title": "...",
  "committee_scrutiny": "...",
  "date": "1405/05/20",

  "chunk_type": "solution",
  "embedding_version": "embeddinggemma-300m-v1"
}
```

### 9.2 `tavanir_regulatory_knowledge_v1`

Example metadata:

```json
{
  "document_id": "REG-2026-018",
  "source_type": "guideline",
  "chunk_id": "REG-2026-018-ARTICLE-12",
  "parent_id": "REG-2026-018",

  "document_type": "guideline",
  "is_binding": false,
  "authority_level": "guidance",

  "article": "12",
  "section": "3",

  "effective_from": "1404/01/01",
  "effective_to": null,

  "version": "2",
  "embedding_version": "embeddinggemma-300m-v1"
}
```

---

## 10. Regulatory Documents Remain in One Collection

The regulatory collection will contain multiple knowledge types:

```text
tavanir_regulatory_knowledge_v1
│
├── statute
├── regulation
├── directive
├── procedure
├── guideline
└── other approved regulatory knowledge
```

Separate Qdrant collections will **not** be created for each of these categories.

They belong to the same general retrieval contract:

> Retrieve authoritative or useful organizational knowledge applicable to the incoming suggestion.

Their differences will instead be represented through metadata.

Recommended fields include:

```text
document_type
source_type
is_binding
authority_level
effective_from
effective_to
organization
version
article
section
```

For example:

```text
document_type = statute
is_binding = true
```

or:

```text
document_type = guideline
is_binding = false
```

This enables filtering while avoiding unnecessary collection proliferation.

---

## 11. Authority Semantics

The retrieval and generation layers must preserve the distinction between binding regulatory requirements and advisory guidance.

Retrieved evidence should conceptually be organized as:

```text
Regulatory Evidence
│
├── Binding
│   ├── Statutes
│   ├── Regulations
│   └── Mandatory directives
│
└── Non-Binding
    ├── Guidelines
    ├── Recommendations
    └── Advisory procedures
```

The generation model must not treat a non-binding guideline as equivalent to a mandatory statute.

Metadata such as:

```text
is_binding
authority_level
document_type
```

must therefore remain available throughout retrieval, reranking, evidence assembly, and generation.

---

## 12. Independent Lifecycle Management

The two corpora have different lifecycle characteristics.

Suggestions are expected to change frequently:

```text
New suggestion
      ↓
Evaluation
      ↓
Status change
      ↓
Execution / rejection / approval
```

Regulatory knowledge changes differently:

```text
New document
      ↓
Revision
      ↓
New version
      ↓
Previous version superseded
      ↓
Effective period changes
```

Using separate collections enables independent:

- reindexing;
- migration;
- backup;
- restoration;
- version upgrades;
- embedding migrations;
- chunking migrations;
- deployment rollback.

For example, changing the suggestion chunking strategy may require:

```text
tavanir_suggestion_v1
        ↓
tavanir_suggestion_v2
```

without modifying:

```text
tavanir_regulatory_knowledge_v1
```

Similarly, a new regulatory parser could produce:

```text
tavanir_regulatory_knowledge_v2
```

without rebuilding the suggestion collection.

---

## 13. Collection Versioning Convention

Collection names will include a version suffix.

Initial collections:

```text
tavanir_suggestion_v1

tavanir_regulatory_knowledge_v1
```

Future incompatible changes may result in:

```text
tavanir_suggestion_v2
```

or:

```text
tavanir_regulatory_knowledge_v2
```

A new collection version should be created when a change requires substantial reindexing or changes the retrieval representation, including major changes to:

- embedding models;
- sparse embedding algorithms;
- chunking strategies;
- vector dimensions;
- document representation;
- index architecture;
- payload conventions required by retrieval;
- corpus processing logic.

Minor application-level changes do not require a new collection version.

---

## 14. Retrieval Service Boundary

Application code should expose the two corpora through independent retrieval components.

Recommended conceptual interfaces:

```python
SuggestionRetriever.search(...)
```

and:

```python
RegulatoryKnowledgeRetriever.search(...)
```

rather than a generic application-level call such as:

```python
KnowledgeRetriever.search_everything(...)
```

The retrieval orchestrator will decide which retrievers are required for a particular workflow.

For the standard suggestion evaluation workflow:

```text
Incoming Suggestion
        │
        ├───────────────────────────────┐
        │                               │
        ▼                               ▼
SuggestionRetriever           RegulatoryKnowledgeRetriever
        │                               │
        ▼                               ▼
tavanir_suggestion_v1       tavanir_regulatory_knowledge_v1
        │                               │
        ▼                               ▼
Hybrid Retrieval              Hybrid Retrieval
        │                               │
        ▼                               ▼
Reranking                     Reranking
        │                               │
        └───────────────┬───────────────┘
                        ▼
                 Evidence Assembly
                        │
                        ▼
                 Generation / Decision
```

Both retrievals should normally be executable in parallel when the workflow requires both.

---

## 15. Consequences

### 15.1 Positive Consequences

The selected architecture provides:

- independent retrieval tuning;
- independent vector index configuration;
- independent scaling;
- independent sparse retrieval statistics;
- clearer domain boundaries;
- safer query behavior;
- independent collection migration;
- independent backups and restoration;
- independent chunking evolution;
- easier retrieval evaluation;
- clearer observability;
- easier debugging;
- reduced risk of accidentally mixing suggestion and regulatory retrieval results.

It also aligns the physical storage architecture with the actual retrieval architecture:

```text
Historical similarity retrieval
        ≠
Regulatory applicability retrieval
```

---

### 15.2 Negative Consequences

The architecture introduces some additional operational complexity.

The system must manage two:

- Qdrant collections;
- collection configurations;
- ingestion targets;
- payload-index configurations;
- monitoring targets;
- migration processes;
- health checks;
- backup units.

Application code must also coordinate two retrieval pipelines.

This overhead is considered acceptable because the system has exactly two major retrieval domains rather than a large number of small collections.

The architecture must avoid unnecessary further collection fragmentation.

---

## 16. Risks of Choosing the Opposite Architecture

If both corpora were stored in a single collection, several risks would exist.

### 16.1 Configuration Coupling

Collection-level vector and indexing decisions would affect both corpora.

A future optimization required only by suggestions could consequently affect regulatory retrieval and vice versa.

---

### 16.2 Migration Coupling

Changes to one corpus could require rebuilding or migrating a collection that also contains unrelated data.

For example:

```text
New suggestion chunking strategy
```

could become operationally coupled to:

```text
Regulatory knowledge storage
```

even though no regulatory data changed.

---

### 16.3 Greater Dependence on Correct Filtering

A single collection would require every retriever to correctly apply a mandatory source filter.

For example:

```text
source_group = suggestion
```

or:

```text
source_group = regulatory
```

A missing filter caused by an application bug could mix the two retrieval domains.

With separate collections, this class of error is eliminated at the storage boundary.

---

### 16.4 Corpus-Level Sparse Retrieval Coupling

If sparse retrieval statistics were calculated across the combined corpus, differences between suggestion language and formal regulatory language could affect term weighting.

Maintaining independent corpora provides a cleaner basis for corpus-specific sparse retrieval.

---

### 16.5 Reduced Long-Term Flexibility

One collection would be simpler initially but would make future changes to:

- vector indexing;
- sharding;
- quantization;
- embedding models;
- migration;
- retrieval optimization;
- lifecycle management

more coupled than necessary.

Since the two retrieval domains are already clearly known during architecture design, accepting this coupling provides limited long-term benefit.

---

## 17. Alternatives Considered

### Alternative A — Single Collection Without Source Filtering

```text
tavanir_knowledge_v1
```

with suggestions and regulations participating in the same nearest-neighbor search.

**Rejected.**

This could cause suggestions and regulatory documents to compete for the same candidate budget and would mix two different definitions of relevance.

---

### Alternative B — Single Collection With Mandatory Prefiltering

```text
tavanir_knowledge_v1
```

with:

```text
source_group = suggestion
```

and:

```text
source_group = regulatory
```

**Technically acceptable but not selected.**

This design would provide logical retrieval isolation and could provide good performance using indexed Qdrant payload filters.

However, both retrieval domains would remain coupled at the collection configuration, lifecycle, migration, and operational levels.

Because independent evolution is considered important for this system, two collections provide a better long-term architecture.

---

### Alternative C — Separate Collection for Every Document Type

Example:

```text
suggestions
statutes
regulations
directives
guidelines
procedures
```

**Rejected.**

This creates unnecessary collection proliferation.

Regulatory documents share the same high-level retrieval objective and should therefore remain within:

```text
tavanir_regulatory_knowledge_v1
```

and be differentiated using metadata.

---

## 18. Final Architecture

The accepted architecture is:

```text
                              Tavanir RAG
                                  │
                           Incoming Suggestion
                                  │
                 ┌────────────────┴────────────────┐
                 │                                 │
                 ▼                                 ▼
       Suggestion Retrieval              Regulatory Retrieval
                 │                                 │
                 ▼                                 ▼
      tavanir_suggestion_v1       tavanir_regulatory_knowledge_v1
                 │                                 │
          ┌──────┴──────┐                  ┌──────┴──────┐
          │             │                  │             │
        Dense         Sparse             Dense         Sparse
          │             │                  │             │
          └──────┬──────┘                  └──────┬──────┘
                 ▼                                ▼
              Fusion                           Fusion
                 │                                │
                 ▼                                ▼
             Reranker                         Reranker
                 │                                │
                 ▼                                ▼
      Similar / Duplicate             Applicable Regulatory
         Suggestions                         Evidence
                 │                                │
                 └───────────────┬────────────────┘
                                 ▼
                         Evidence Assembly
                                 │
                                 ▼
                          Generation Model
                                 │
                ┌────────────────┴────────────────┐
                │                                 │
                ▼                                 ▼
       Historical Assessment          Regulatory Assessment
```

---

## 19. Decision Summary

The system will use:

```text
tavanir_suggestion_v1
```

for historical suggestion retrieval, and:

```text
tavanir_regulatory_knowledge_v1
```

for statutes, regulations, directives, procedures, guidelines, and related regulatory knowledge.

The separation is **not based primarily on differences in metadata**.

It is based on the fact that the collections implement two different retrieval contracts:

```text
tavanir_suggestion_v1

Question:
"What previous suggestions are similar to this suggestion?"

Primary relevance:
Semantic similarity / duplication / historical precedent
```

versus:

```text
tavanir_regulatory_knowledge_v1

Question:
"What authoritative or useful regulatory knowledge applies
to this suggestion?"

Primary relevance:
Applicability / authority / regulatory relevance / guidance
```

The additional operational overhead of maintaining two collections is accepted in exchange for stronger domain separation, independent tuning, safer retrieval, independent migrations, and greater long-term flexibility.

**Decision: Accepted — use two separate Qdrant collections.**
