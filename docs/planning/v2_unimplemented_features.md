# V2 Unimplemented Features & Migration Backlog

This document tracks remaining target work for **Tavanir AI Assistant V2**. Some use cases, routes, retrieval adapters, and Generation components below are already implemented; status is stated explicitly where it affects the analysis path. The [Generation API test summary](../documentation/llm_generation_test_summary.md) records the current validation boundary.

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

### 1.2 Historical MSSQL Extraction

* **Implemented**: `MssqlSuggestionExtractor` in `src/infrastructure/services/extractors/mssql_suggestion_extractor.py` uses `pymssql` and the configured `MssqlSettings` to read historical suggestions in pages. `ExtractAndIngestHistoricalSuggestionsUseCase` orchestrates ingestion.
* **Remaining**: Deploy and verify the real source connection and batch ingestion on the target environment; schedule long-running work in the planned worker. The earlier example CTE and `aioodbc`/`pyodbc` dependency are not the current extractor contract.

### 1.3 Statute Retrieval and Multi-Collection Analysis
* **Current**: Suggestion retrieval is implemented via five Qdrant searches in three tracks, followed by chunk-ID deduplication, reranking, parent pooling, and PostgreSQL hydration.
* **Remaining**: Add statute/regulation retrieval and pass that evidence to the Generation input contract. The production analysis response currently returns `applied_statute_ids=[]`.

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
  * `SuggestionStatus` already exists with `EXECUTED`, `APPROVED`, `PENDING`, `REJECTED`, and `NOT_ACCEPTED`; any additional states require a separate contract change.
  * `RegisteredSuggestion` entity: `suggestion_id`, `title`, `current_problem`, `solution`, `status`, `context_title`, `date`, `committee_scrutiny`.
  * `Statute` entity: `statute_id`, `title`, `content`, `article_number`.
  * `SuggestionAnalysisResult` entity: Structured container for categorized precedents, statute citations, duplicate evaluation score, and committee recommendation.

### 2.2 Application DTOs and Generation Contract
* **Implemented**: `GenerationInput`, `CurrentSuggestionInput`, `SimilarSuggestionInput`, `RegulationInput`, `PreparedGeneration`, `GenerationResult`, `StructureIdeaDTO`, and `StructuredIdeaResult`. `AnalyzeSuggestionResponse` and its HTTP schema expose parsed analysis, uncertainty, cited IDs, fallback flag, and citation coverage alongside existing candidate lists.
* **Remaining**: Supplied-regulation rendering/citation mapping and full context-window accounting. `appliedStatuteIds` remains empty; coverage is not calibrated model confidence.

### 2.3 Generation Use Cases and Verification
* **Implemented**: Analyze hands already-prepared `GenerationInput` to the injected `GenerateSuggestionUseCase`, which prepares context, invokes the shared chat client, and parses against retained citations. Its existing no-usable-evidence guard returns diagnostics without Generation.
* **Implemented**: `StructureIdeaUseCase` validates a maximum 512-model-token description, runs PromptBuilder sections through ContextBuilder, invokes the same chat client, and parses five marked fields for `/expand-suggestion`.
* **Current working-tree issue**: Expansion's prompt example uses Persian markers; the strict parser still requires the original English markers. Resolve that Generation disagreement before claiming successful real-model output.
* **Remaining**: Fresh live endpoint/provider validation, full chat framing plus completion reserve, final-output retry/metrics policy if required, and expansion mock-mode parity. Do not repeat the completed generator handoff or change retrieval implementation here.
* **Other implemented use cases**: suggestion ingest, update, delete, bulk delete, and historical extraction/ingestion have source implementations. Statute ingestion and custom-template update remain target work.

## 3. Prompt Construction and Templates

* **Implemented**: Analyze uses `SuggestionPromptPreparer` with fixed/evidence sections; expansion uses three explicitly tuned sections and `StructureIdeaPromptConfig`. Both use `PromptBuilder`, `ContextBuilder`, and `LLMRequestBuilder` over processed sections. Static prompt instructions are Persian; Analyze requests JSON and expansion requires ordered English markers in plain text. See the [Generation API guide](../documentation/llm_generation_api.md).
* **Remaining**: Reconcile expansion prompt/parser markers and validate the full provider context allowance (input, chat framing, and reserved completion). The previously proposed `suggestion_analysis_system.jinja2` and `suggestion_analysis_user.jinja2` files do not exist; Jinja-based templates remain a target option, not the current prompt implementation.

## 4. Presentation Layer (FastAPI Routers)

* **Implemented**: `src/main.py` creates the FastAPI app; `src/presentation/routers/v1/suggestion.py` provides `POST /api/v1/suggestions/analyze` and suggestion ingestion/update/delete routes; API-key validation and exception handlers exist.
* **Current Generation behavior**: Analyze calls the injected generator and returns parsed answer/citations/uncertainty when usable evidence exists. Expansion calls `StructureIdeaUseCase` and returns `title`, `currentProblem`, `solution`, `advantage`, `disadvantage` in the existing envelope. Both use centralized provider/parser/budget error mappings.
* **Remaining**: Verify real HTTP-to-model completions and resolve the current expansion marker mismatch. Controlled tests and historical lower-level runs do not prove live deployment readiness.
* **Target only**: A custom-template update endpoint and its persistence service are not part of the current router.

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
* **Current File**: `src/infrastructure/configs/settings.py`
* **Requirements**:
  * `MssqlSettings` already defines source connection and batch settings; validate deployment values and secret handling.
  * `SuggestionAnalysisSettings`: Retrieval limits, score threshold, and prompt budget are implemented. `GenerationSettings` supplies provider/model, tokenizer, temperature, completion allowance, timeout, and positive `IDEA_MAX_PROMPT_TOKENS=4096`; deployment values must match the served model.


## 7. Generation Deployment Gate

* The default model is `Qwen/Qwen2.5-7B-Instruct` with a 4,096-token prompt budget and 4,096 completion-token allowance. A local 0.5B vLLM run succeeded only with temporary environment overrides; these are not deployment configuration.
* Verify a real request through `API → AnalyzeSuggestionUseCase / StructureIdeaUseCase → Generation → vLLM → parser → final HTTP response`. For Generation, cover normal and existing no-evidence outcomes, retained citations, expansion 512/513-token limits and exact markers, context overflow, malformed output, network/timeouts, matching model/tokenizer, and HTTP mappings. Preserve upstream retrieval behavior.
* Do not claim end-to-end readiness from mock API tests or the lower-level live runner alone. See the [test summary](../documentation/llm_generation_test_summary.md).
