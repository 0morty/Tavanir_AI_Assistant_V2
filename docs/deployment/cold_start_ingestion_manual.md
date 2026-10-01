# Cold-Start Historical Suggestion Ingestion Manual

A step-by-step operational guide for developers and DevOps engineers to extract, normalize, embed, and enrich databases with legacy suggestions using the Day 0 cold-start ingestion pipeline.

---

## 1. System Overview & Architecture

The historical ingestion pipeline executes a high-throughput, fault-tolerant batch ETL process from legacy MSSQL into the modern dual-write data store:
1. **PostgreSQL Relational DB:** Stores normalized suggestion entities, skipped records audit log, and offset watermark checkpoints.
2. **Qdrant Vector DB:** Stores dense (TEI) and sparse (Persian BM25) vector chunks with payload metadata behind an atomic search alias (`ADR-001`).

```text
+-----------------------------------------------------------------------------------+
|                         INGESTION EXECUTION PIPELINE                              |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| 1. INFRASTRUCTURE READINESS                                                       |
|    - IQdrantAdminService.wait_until_ready() verifies cluster connectivity         |
|    - If --reset: delete existing collection & clear PostgreSQL watermark          |
|    - Idempotently provision suggestion collection schema                          |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| 2. BULK THROUGHPUT OPTIMIZATION                                                   |
|    - IQdrantAdminService.set_indexing_threshold(0): disables live HNSW indexing   |
|      (delivers 5-10x faster batch insertion into flat storage)                    |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| 3. STREAMING EXTRACTION & PERSISTENCE LOOP (ExtractAndIngestHistoricalSuggestions)|
|                                                                                   |
|    [MSSQL Offset Streaming]                                                       |
|              │                                                                    |
|              ▼                                                                    |
|    [In-Memory Normalization] ──> Persian digits, Shamsi dates, Persian text       |
|              │                                                                    |
|              ▼                                                                    |
|    [Field Chunking]          ──> Title, Problem, Solution, Evaluation chunks      |
|              │                                                                    |
|              ▼                                                                    |
|    [Hybrid Embeddings]       ──> Micro-batched concurrent Dense (TEI) & BM25      |
|              │                                                                    |
|              ▼                                                                    |
|    [Pattern A Dual-Write]    ──> a. Save suggestions to PostgreSQL (uow.commit()) |
|                                  b. Upsert chunks to Qdrant (outside SQL tx)      |
|                                     (on failure: compensating delete_batch in SQL)|
|                                  c. Commit watermark checkpoint (uow.commit())    |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| 4. HNSW RE-INDEXING & STABILIZATION (finally block)                               |
|    - IQdrantAdminService.set_indexing_threshold(20000): re-enables graph indexing |
|    - IQdrantAdminService.wait_for_indexing_settled(): polls until GREEN & ok      |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| 5. GATEKEEPER HYBRID SMOKE TESTS                                                  |
|    - Runs representative Persian domain search queries against Qdrant collection  |
|    - Verifies search recall > 0 before traffic cutover                            |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| 6. ATOMIC ALIAS CUTOVER (ADR-001)                                                 |
|    - IQdrantAdminService.switch_alias(tavanir_suggestion_active -> target)        |
|    - Zero-downtime production traffic cutover                                     |
+-----------------------------------------------------------------------------------+
```

---

## 2. Prerequisites & Environment Setup

Before starting ingestion, verify that all external services and environment variables are active.

### A. Infrastructure Services
Ensure the following services are reachable:
- **PostgreSQL (v16+):** Target relational database.
- **Qdrant (v1.17+):** Target vector store.
- **MSSQL:** Source legacy database.
- **TEI / vLLM:** Dense embedding microservice (`/v1/embeddings`).

### B. Database Migrations
Apply all Alembic migrations to ensure the relational schema is up to date:
```bash
# From repository root
alembic upgrade head
```

Verify that the following tables exist in PostgreSQL:
- `suggestions`
- `ingestion_checkpoints`
- `skipped_suggestions`

### C. Environment Configuration (`.env`)
Verify the following variables in your `.env` file:
```dotenv
# PostgreSQL
POSTGRES_SERVER=localhost
POSTGRES_PORT=7432
POSTGRES_DB=tavanir_db
POSTGRES_USERNAME=postgres
POSTGRES_PASSWORD=your_password

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=7333
QDRANT_GRPC_PORT=7334
QDRANT_API_KEY=your_qdrant_api_key
QDRANT_SUGGESTION_COLLECTION=tavanir_suggestion_v1
QDRANT_SUGGESTION_ALIAS=tavanir_suggestion_active

# MSSQL Source
MSSQL_SERVER=192.168.1.100
MSSQL_PORT=1433
MSSQL_DATABASE=LegacySuggestionsDB
MSSQL_USER=etl_reader
MSSQL_PASSWORD=your_mssql_password
MSSQL_BATCH_SIZE=200
MSSQL_QUERY_TIMEOUT=120

# TEI / Dense Embedder
TEI_HOST=localhost
TEI_PORT=8080
EMBEDDING_MODEL=google/embedding-gemma-2b
EMBEDDING_DIMENSION=768

# Historical Ingestion Defaults
CHECKPOINT_JOB_NAME=historical_suggestion_ingestion
```

---

## 3. Execution Mode 1: Local Virtual Environment

Use this mode for local development, debugging, and interactive monitoring.

### Step 1: Activate Virtual Environment
```powershell
# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate
```

### Step 2: Choose Execution Scenario

#### Scenario A: Fresh Day 0 Initial Run (`--reset`)
Drops existing Qdrant collection, clears PostgreSQL checkpoint watermarks, and runs full ingestion from offset 0:
```bash
python scripts/extract_and_ingest_historical_suggestions.py --reset --batch-size 200
```

#### Scenario B: Resume Interrupted Ingestion (`--resume`)
Resumes from the exact last-committed watermark in PostgreSQL (`ingestion_checkpoints` table):
```bash
python scripts/extract_and_ingest_historical_suggestions.py --resume --batch-size 200
```

#### Scenario C: Emergency Run without Gatekeeper Smoke Tests
Skips post-ingestion search verification (e.g. if embedding endpoint is temporarily degraded for search queries):
```bash
python scripts/extract_and_ingest_historical_suggestions.py --resume --skip-gatekeeper
```

### Step 3: Command-Line Flags Reference

| Flag | Type | Default | Description |
|---|---|---|---|
| `--batch-size` | `int` | `200` | Number of suggestion records per offset page |
| `--resume` / `--no-resume` | `bool` | `True` | Whether to resume from last committed PostgreSQL watermark |
| `--reset` | `flag` | `False` | Drops target collection & clears PostgreSQL watermark before start |
| `--skip-gatekeeper` | `flag` | `False` | Skips Gatekeeper hybrid smoke tests before alias switch |

---

## 4. Execution Mode 2: Containerized Docker Compose

Use this mode for staging and production environments to run ingestion in an isolated container.

### Step 1: Verify Shared Network
Ensure the core services (`tavanir_postgres`, `tavanir_qdrant`) are running on `tavanir_network`:
```bash
docker compose up -d tavanir_postgres tavanir_qdrant
```

### Step 2: Run Ingestion Container
Run the dedicated ingestion compose file:
```bash
# Default run (resumes from watermark)
docker compose -f docker-compose.historical_ingest.yaml up --build
```

### Step 3: Run with Custom Flags
To override arguments (e.g. `--reset` with custom `--batch-size`):
```bash
docker compose -f docker-compose.historical_ingest.yaml run --rm historical_ingest --reset --batch-size 250
```

To view logs while running detached:
```bash
docker logs -f tavanir_historical_ingest
```

---

## 5. Graceful Drain & Shutdown (Ctrl+C / SIGINT)

The ingestion script is equipped with **graceful drain signal handling**:
- When `SIGINT` (Ctrl+C) or `SIGTERM` is received, the script does **not** terminate abruptly.
- It logs: `shutdown_signal_received | action="Draining current batch before stopping..."`.
- The current in-flight batch completes:
  1. Relational records are committed to PostgreSQL.
  2. Vectors are upserted into Qdrant.
  3. Watermark offset is saved to `ingestion_checkpoints`.
- The `finally` block restores the Qdrant HNSW indexing threshold (`20000`).
- The script exits cleanly with: `ingestion_stopped_early_by_user | message="Watermark preserved."`.
- **To resume later:** Simply run with `--resume`.

---

## 6. Post-Ingestion Verification

After the script finishes, execute the following validation steps.

### Step 1: Verify PostgreSQL Relational State
Connect to PostgreSQL and verify counts:
```sql
-- 1. Total ingested suggestions
SELECT COUNT(*) FROM suggestions;

-- 2. Watermark status
SELECT job_name, last_offset, last_processed_id, total_processed, updated_at 
FROM ingestion_checkpoints;

-- 3. Review skipped/corrupted records audit log
SELECT error_type, reason, COUNT(*) 
FROM skipped_suggestions 
GROUP BY error_type, reason;
```

### Step 2: Verify Qdrant Vector Collection & Alias
Using `curl` or Qdrant Web UI:
```bash
# Check collection status and point count
curl -X GET "http://localhost:7333/collections/tavanir_suggestion_v1" \
     -H "api-key: your_qdrant_api_key"

# Check active search alias
curl -X GET "http://localhost:7333/aliases" \
     -H "api-key: your_qdrant_api_key"
```

Expected output confirms:
1. `status: "green"`
2. `points_count` matches total chunks.
3. Alias `tavanir_suggestion_active` points to `tavanir_suggestion_v1`.

---

## 7. Troubleshooting & Recovery Playbook

### Problem 1: `ConnectionError: Failed to connect to Qdrant cluster after 10 attempts`
- **Cause:** Qdrant container is not running or ports are blocked.
- **Fix:**
  1. Check container status: `docker ps | grep qdrant`.
  2. Test TCP port: `curl http://localhost:7333/readyz`.
  3. Verify `QDRANT_HOST`, `QDRANT_PORT`, and `QDRANT_API_KEY` in `.env`.

### Problem 2: `Gatekeeper smoke test FAILED: 0 results returned for query`
- **Cause:** Vectors were not indexed properly or dense/sparse embedders produced zero vectors.
- **Fix:**
  1. Verify TEI embedding endpoint: `curl http://localhost:8080/health`.
  2. Check Qdrant collection optimizer status: ensure HNSW indexing finished settling.
  3. Run smoke test manually or run with `--resume --skip-gatekeeper` if only the test query threshold failed.

### Problem 3: `MSSQL Login failed / Network connection timeout`
- **Cause:** Database firewall, FreeTDS driver issue, or invalid credentials.
- **Fix:**
  1. Verify host and port in `MSSQL_SERVER` and `MSSQL_PORT`.
  2. Ensure `freetds-dev` is installed in the Linux/Docker environment.
  3. Test connectivity using `nc -zv $MSSQL_SERVER 1433` or sqlcmd.

### Problem 4: Script interrupted in the middle of a batch
- **Resolution:** No manual database cleanup is needed. The pipeline uses **Pattern A Persistence with Compensating Rollback**:
  - If Qdrant fails, SQL changes are deleted via compensating rollback.
  - If process dies, the checkpoint watermark remains at the last fully succeeded batch.
  - Simply re-run with `--resume`.
