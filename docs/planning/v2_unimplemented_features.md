# V2 Unimplemented Features & Migration Backlog

This document outlines all features and infrastructure components from the legacy **Tavanir AI Assistant (Suggestion Committee RAG)** that are **not yet implemented** in the new **JadooChatRAG** Clean Architecture codebase.

---

## 1. Infrastructure Layer

### 1.1 Excel Document Loader
* **Target File**: `src/infrastructure/services/loaders/excel_document_loader.py`
* **Interface**: Implements `IDocumentLoader`
* **Requirements**:
  * Parse `.xlsx` and `.xls` files containing legal articles, regulations, and organizational bylaws.
  * Extract rows into formatted Persian text representations with associated metadata (`statute_id`, `article_number`, `source_file`).
  * Integrate into `DocumentLoaderFactory`.
  * **Dependencies**: Add `openpyxl` / `pandas` to `requirements.txt`.

### 1.2 MSSQL Extractor Service & Database Connector
* **Target File**: `src/infrastructure/services/extractors/mssql_suggestion_extractor.py`
* **Requirements**:
  * Establish connection to the legacy MSSQL suggestion database (via `aioodbc` / `SQLAlchemy`).
  * Implement the optimized Common Table Expression (CTE) query:
    ```sql
    WITH RankedSuggestions AS (
        SELECT 
            si.SuggestionCode,
            si.SuggestionTitle,
            s.CurrentProblem,
            s.CurrentSolution,
            cs.ScrutinyResult,
            cs.StatusID,
            sc.ContextTitle,
            ROW_NUMBER() OVER (PARTITION BY si.SuggestionCode ORDER BY cs.Iteration DESC) as rn
        FROM SuggestionInfo si
        JOIN suggestion s ON si.SuggestionID = s.SuggestionID
        LEFT JOIN CommitteeSessionResult csr ON si.SuggestionID = csr.SuggestionID
        LEFT JOIN ComitteeScrutiny cs ON csr.SessionID = cs.SessionID
        LEFT JOIN SuggestContext sc ON si.ContextID = sc.ContextID
    )
    SELECT * FROM RankedSuggestions WHERE rn = 1
    ORDER BY SuggestionCode
    OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY;
    ```
  * Map legacy numeric `StatusID` codes into standardized Persian status strings (`اجرا شده`, `مصوب`, `در حال بررسی`, `رد`, `عدم پذیرش`).
  * Stream extraction using configurable batch sizing (e.g., 1,000 records/batch).
  * **Dependencies**: Add `aioodbc` or `pyodbc` to `requirements.txt`.

### 1.3 Multi-Status & Multi-Collection Qdrant Retrieval Adapter
* **Target File**: `src/infrastructure/database/repositories/qdrant_repository.py` or dedicated retrieval adapter
* **Requirements**:
  * Support querying distinct status subsets in parallel (`اجرا شده`, `مصوب`, `در حال بررسی`, `رد`, `عدم پذیرش`) with optional `context_title` filtering.
  * Support querying the `statutes` collection / document partition.
  * Implement multi-chunk flattening and ID deduplication: when multiple chunks of the same parent suggestion match, retain only the chunk with the lowest distance / highest similarity score.
  * Return categorized candidate hits for prompt assembly.

### 1.4 Dynamic Prompt Template Persistence Service
* **Target File**: `src/infrastructure/services/template/dynamic_template_service.py`
* **Requirements**:
  * Provide atomic read/write persistence for custom prompt configurations (`assets/custom_template.json`).
  * Implement crash-resilience via temporary file write and atomic `os.replace`.
  * Ensure concurrency safety across asynchronous tasks using `asyncio.Lock`.

### 1.5 In-Process SentenceTransformer Embedder (Optional / Local Mode)
* **Target File**: `src/infrastructure/services/embeddings/sentence_transformer_embedder.py`
* **Interface**: Implements `IDenseEmbedder`
* **Requirements**:
  * Local in-memory inference for `ParsBERT V3` / `Shafagh` models using `sentence-transformers`.
  * Run model encoding inside `asyncio.to_thread` to prevent blocking FastAPI's event loop.
  * Vector normalization to unit length for cosine similarity.

---

## 2. Domain & Application Layer

### 2.1 Domain Entities & Enums
* **Target File**: `src/domain/entities.py` & `src/domain/enums.py`
* **Requirements**:
  * `SuggestionStatus` enum: `EXECUTED` (`اجرا شده`), `APPROVED` (`مصوب`), `UNDER_REVIEW` (`در حال بررسی`), `REJECTED` (`رد`), `NOT_ACCEPTED` (`عدم پذیرش`).
  * `RegisteredSuggestion` entity: `suggestion_id`, `title`, `current_problem`, `solution`, `status`, `context_title`, `date`, `committee_scrutiny`.
  * `Statute` entity: `statute_id`, `title`, `content`, `article_number`.
  * `SuggestionAnalysisResult` entity: Structured container for categorized precedents, statute citations, duplicate evaluation score, and committee recommendation.

### 2.2 Application DTOs & Commands / Queries
* **Target Directory**: `src/application/dtos/`
* **Requirements**:
  * `AnalyzeSuggestionDTO`: Input payload (`title`, `current_problem`, `solution`, `context_title`).
  * `SuggestionAnalysisResultDTO`: Output structured recommendation, matched positive/negative precedents, and statute references.
  * `IngestSuggestionDTO`: Real-time ingestion payload for a single suggestion.
  * `DeleteSuggestionDTO`: Payload for single or bulk suggestion deletion.
  * `SetCustomTemplateDTO`: Payload for updating system prompt, evaluation instructions, and output schema.

### 2.3 Use Cases (CQRS)
* **Target Directory**: `src/application/use_cases/`
* **Requirements**:
  * `AnalyzeSuggestionUseCase` (`queries/analyze_suggestion_use_case.py`):
    1. Synthesize input text (`title` + `current_problem` + `solution`).
    2. Normalize Persian text using `ShekarTextNormalizer`.
    3. Generate query embeddings.
    4. Execute parallel vector searches across status categories and statutes.
    5. Deduplicate and group candidate precedents.
    6. Construct Chain-of-Thought prompt with token budgeting.
    7. Invoke LLM with strict temperature (`0.1`) and return structured decision analysis.
  * `IngestSuggestionUseCase` (`commands/ingest_suggestion_use_case.py`):
    * Normalize, chunk, embed, and upsert a single registered suggestion into Qdrant.
  * `DeleteSuggestionUseCase` (`commands/delete_suggestion_use_case.py`):
    * Filtered deletion of suggestion chunks from Qdrant by `suggestion_id` or list of IDs.
  * `ExtractAndIngestHistoricalSuggestionsUseCase` (`commands/extract_and_ingest_historical_suggestions_use_case.py`):
    * Orchestrate batch extraction from MSSQL, chunking, embedding, and bulk ingestion into Qdrant.
  * `ExtractAndIngestStatutesUseCase` (`commands/extract_and_ingest_statutes_use_case.py`):
    * Orchestrate Excel statute file parsing, normalization, chunking, and indexing into Qdrant.
  * `SetCustomTemplateUseCase` (`commands/set_custom_template_use_case.py`):
    * Validate and persist user-defined prompt templates.

---

## 3. Prompt Engineering & Jinja2 Templates

### 3.1 Suggestion Analysis Templates
* **Target Files**:
  * `src/infrastructure/services/llm/templates/suggestion_analysis_system.jinja2`
  * `src/infrastructure/services/llm/templates/suggestion_analysis_user.jinja2`
* **Requirements**:
  * **System Prompt**:
    * Persona: Tavanir Suggestion Committee Expert Assistant.
    * Strict evaluation rules: duplicate prevention, organizational relevance, feasibility, and statute compliance.
  * **User Prompt Structure**:
    1. *Incoming Suggestion Data*: Title, Current Problem, Solution, Context.
    2. *Organizational Rules & Statutes*: Top-$k$ retrieved legal articles.
    3. *Positive Precedents*: Executed / Approved historical suggestions (flagging potential duplicates or previous implementations).
    4. *Negative Precedents*: Rejected suggestions (preventing recurring flawed suggestions).
    5. *Pending Suggestions*: In-review submissions.
    6. *Output Schema*: Strict structured output (Recommendation, Duplicate Analysis, Compliance Verdict, Justification).

---

## 4. Presentation Layer (FastAPI Routers)

### 4.1 Suggestion Analysis Router
* **Target File**: `src/presentation/routers/v1/suggestion_analysis_router.py`
* **Prefix**: `/analyze-suggestion`
* **Endpoints**:
  * `POST /analyze-suggestion/analyze`: Executes end-to-end RAG analysis on an incoming suggestion.
  * `POST /analyze-suggestion/set-template`: Updates and persists custom prompt templates.

### 4.2 Suggestion Ingestion & Management Router
* **Target File**: `src/presentation/routers/v1/suggestion.py`
* **Prefix**: `/ingest-suggestion`
* **Endpoints**:
  * `POST /ingest-suggestion/ingest`: Real-time ingestion endpoint for new suggestions.
  * `POST /ingest-suggestion/delete`: Bulk/single deletion of suggestions from vector storage.

---

## 5. Startup Lifespan & Background Tasks

### 5.1 Lifespan Auto-Ingestion Guard
* **Target File**: `src/presentation/lifespan.py`
* **Requirements**:
  * Check Qdrant collection record counts on application startup:
    * If `statutes` collection has 0 points $\rightarrow$ execute `ExtractAndIngestStatutesUseCase`.
    * If `suggestions` collection has 0 points $\rightarrow$ execute `ExtractAndIngestHistoricalSuggestionsUseCase` (streaming from MSSQL).

### 5.2 Background Worker Tasks
* **Target File**: `src/infrastructure/tasks/use_case_tasks.py`
* **Requirements**:
  * Register batch ingestion tasks in the ARQ task registry for asynchronous execution and progress logging.

---

## 6. Configuration Settings

### 6.1 Settings Extensions
* **Target File**: `src/infrastructure/configs/config.py`
* **Requirements**:
  * `MssqlSettings`: Server, Port, User, Password, Database, Driver name, Batch Size.
  * `SuggestionAnalysisSettings`: Status categories, retrieval limit per status, similarity thresholds, context token budget.
