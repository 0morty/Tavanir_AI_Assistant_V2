# Complete non-analysis E2E implementation plan and checklist

Recovered original documents from this chat. The design and repository baseline below are historical; this recovery does not execute the plan or change application/database state.

This file contains the original implementation plan followed by all **210 checklist items**, including 18 preparation/completion items. Analysis remains excluded.

---

# Deep E2E test implementation and execution plan

## 1. Objective and agreed scope

Build a reproducible automated suite based on the [non-analysis E2E checklist](D:/Jco_Projects/tavanir-ai-assistant-v2/docs/planning/non_analysis_api_e2e_test_checklist.md), reviewed against local `develop` commit `79cf610`.

The suite will cover ingestion, PUT, PATCH, deletion, bulk deletion, authentication, validation, host behavior, concurrency, faults, and recovery. Suggestion analysis and historical extraction remain excluded.

Agreed choices:

- Disposable PostgreSQL and Qdrant containers.
- A representative historical sample plus synthetic fixtures.
- Real embeddings for normal workflows.
- Separate controlled-provider and instrumented fault profiles.
- A local runner with CI-ready reports.
- Production source remains unchanged; discovered defects receive evidence and recommendations.

The checklist contains **210 items**, including 18 preparation/completion items. Parameterized scenarios will produce more executable tests than this count. Completion means every required item and variant has traceable evidence—not that the implementation necessarily passes every test.

## 2. Harness, environment, and test data

### Real application execution

Create a dedicated harness under `D:\Jco_Projects\tavanir-ai-assistant-v2\tests\e2e\non_analysis`.

- Launch the real application in an owned, single-worker Uvicorn subprocess with reload disabled.
- Send requests through an ordinary HTTP client over TCP.
- Preserve production lifespan, DI, use cases, repositories, normalizer, chunker, and embedding adapters.
- Supply isolated settings before subprocess imports. Do not edit the repository’s `.env`.
- Launch additional processes only for configuration variants, instrumented scenarios, or mock-mode checks.

Use separate evidence profiles:

| Profile | Application and dependencies |
|---|---|
| Real E2E | Unchanged application, real stores, real embedding provider |
| External fault E2E | Same application, with selected network operations intercepted |
| Controlled provider | Real application and stores, with deliberately malformed provider responses |
| Instrumented fault | Real orchestration and stores, with transparent test-only collaborator wrappers |
| Mock presentation | Actual HTTP mock host; results reported separately |

### Disposable infrastructure

Add a test-owned Compose configuration with PostgreSQL 16 and Qdrant matching the reviewed deployment version.

Use a unique Compose project, project-scoped networks and volumes, dynamically allocated loopback ports, and no development data mounts or fixed container names. Unique project names support environment isolation. [Docker documentation](https://docs.docker.com/compose/how-tos/project-name/)

Before any write or teardown, verify the target’s container identity and run ownership. A database name or collection prefix alone is insufficient.

Provision schema through Alembic migrations. Create only destination collections, indexes, and aliases needed by this suite. Do not reuse the existing provisioning script against inherited settings.

### Preflight requirements

The runner must verify:

- A working Python environment and reproducible dependency versions.
- Docker access and container readiness.
- Successful migrations.
- Correct Qdrant alias, vector names, and dimension.
- A real embedding request matching the configured model and dimension.
- Required local tokenizer assets, even though analysis is excluded.
- API authentication and `mockMode=false`.

`/health` is liveness only; it cannot establish dependency readiness.

Current exploration has **not confirmed runnable Python or Docker access**: the virtual-environment launch failed, and Docker inspection encountered a permission limitation. These must be resolved during implementation preflight.

### Historical sample

Default to **100 qualified suggestions**, selected reproducibly:

1. Allocate approximately 20 per available status.
2. Within each status, prioritize variation in commentary, context, dates, Unicode, and chunk counts.
3. Use a stable hash of suggestion ID to break ties.
4. Fill shortages from remaining qualified records and record unavailable categories.

Read source SQL and Qdrant without modifying either. Preserve original rows, versions, timestamps, point IDs, payloads, and vectors.

Resolve the source alias before export and recheck afterward. Compare selected SQL records and point sets before and after capture; reject drifting exports. A SQL transaction alone cannot provide an atomic snapshot across both stores.

Independently qualify records before using them. Report excluded or inconsistent records rather than silently labeling them healthy.

Historical records remain unchanged as background data and sentinels. Synthetic fixtures exercise mutations and deliberately inconsistent states.

### Independent verification

Implement raw database readers that bypass fault proxies and production repositories:

- **SQL:** exact fields, deletion flag, version, timestamps, and physical absence where required.
- **Qdrant:** complete pagination, payloads, vectors, and every lifecycle state.
- **Text/chunks:** independently reviewed golden fixtures for normalization, protected syntax, boundaries, and chunk contents.
- **Embeddings:** vector shape, finite values, sparse validity, and correspondence between provider input, response index, and stored chunk.

Qdrant inspection must explicitly request payloads and vectors and follow pagination to completion. [Qdrant API reference](https://api.qdrant.tech/api-reference/points/scroll-points)

Do not calculate expected normalization or chunking results by calling the production implementation.

## 3. Implementation stages and coverage

### Stage A — Make the checklist executable

Create a coverage manifest containing:

`case_id`, `variant_id`, requirement, profile, fixture, actions, expected HTTP/SQL/Qdrant results, fault schedule, evidence requirements, cleanup obligations, and pytest node ID.

Expand every listed variant: endpoints, field names, enum representations, valid codes, boundaries, failure positions, and lifecycle states.

Each collected test must link to the manifest. Missing mappings or required variants fail the completeness check.

Register explicit pytest markers and enforce strict marker validation. Ordinary discovery must not start services or mutate databases without an E2E opt-in. [pytest documentation](https://docs.pytest.org/en/stable/example/markers.html)

### Stage B — Implement normal and negative scenarios

| Area | Required coverage |
|---|---|
| Host and contracts | Startup/shutdown, public documentation routes, authentication, request IDs, envelopes, errors, configuration variants |
| Validation | Missing/null/blank/wrong-type values, aliases, Unicode identity, enum mappings, duplicate properties, content types, routing |
| Ingestion | Minimal/full records, normalization, evaluation thresholds, chunking, sparse vectors, duplicates, residual points, batch boundaries |
| PUT | Replacement, optional-field clearing, restoration, missing IDs, body/path identity, metadata propagation |
| PATCH | Independent overlays, ignored nulls, forbidden IDs, blank no-ops, evaluation creation/removal, repeated requests |
| Deletion | Soft deletion, repeat deletion, missing rows, all vector states, restoration lifecycle |
| Bulk deletion | One/100/101 items, duplicates, ordering, mixed results, first/middle/last failures, partial execution |
| Cross-endpoint flows | Full lifecycle, unrelated-record preservation, retries, persistence across restart |

Exercise explicit boundaries around text validity, evaluation length, SQL field lengths, chunk sizes, embedding batches, vector slices, and bulk limits. Use the configured production defaults, with separately labeled configuration variants where necessary.

Run all status and scrutiny mappings prescribed by the checklist. Historical sampling does not replace exhaustive synthetic coverage.

### Stage C — Validate the harness itself

Before trusting product results, prove that the harness:

- Detects an intentionally removed vector, wrong payload, and unrelated-record modification.
- Reads beyond one Qdrant page.
- Rejects writes to a source or unowned target.
- Detects missing manifest variants.
- Records failed fault triggers and expired barriers.
- Preserves evidence when tests or application processes fail.
- Cleans up after interrupted execution.

These controls prevent false passes caused by defective test infrastructure.

## 4. Deep fault, concurrency, and recovery testing

### Deterministic external faults

Use test-owned forwarding proxies for Qdrant REST and embedding traffic. Explicitly set Qdrant REST transport for this profile.

Fault rules must match the intended operation, parent/point IDs or input fingerprint, and attempt number. Support:

- Rejection before forwarding.
- Delay behind an acknowledged barrier.
- Successful upstream application followed by a lost response.
- First/later-batch failures.
- Transient recovery and retry exhaustion.
- Controlled malformed provider responses.

Record whether an operation actually applied. A timeout or connection failure does not prove rollback.

Never stop a shared embedding provider. Inject provider faults only through the owned proxy. Service stop/restart faults apply only to disposable stores.

### Precise local faults

Use a test-only subprocess bootstrap and DI wrappers for:

- Normalizer, sparse embedder, and chunker exceptions.
- Zero-chunk results.
- SQL failures before and after commit.
- Compensation failures.
- Exact cancellation and phase barriers.

Keep real collaborators underneath the wrappers. Do not replace an entire use case with a mock or add production test flags.

### Scheduled races and crashes

Implement acknowledged schedules for:

- Same-ID ingestion competing after duplicate checks.
- PUT/PATCH from the same original version.
- Two committed updates with interleaved vector cutovers.
- Update versus deletion or restoration.
- Failed deletion compensation versus a competing write.
- Overlapping bulk operations.
- Independent mutations on different IDs.
- Process termination after staging, after SQL commit, and between promotion/purge.
- Lost responses followed by retries.

Use a separate SQL transaction for advisory-lock contention. Use barriers and observed phase events to schedule races; arbitrary sleeps are insufficient.

Repeat these critical defect probes explicitly:

- Promotion succeeds, purge fails, and retry leaves no active replacement vectors.
- An older cutover activates or purges a newer operation’s points.
- Ingestion compensation removes another request’s accepted data.
- DELETE retry returns success while orphan vectors remain.
- Lost deletion acknowledgement restores an active SQL row without vectors.

After interruption, inspect both stores before resetting fixtures. Restarting the application must not be treated as evidence of an unimplemented repair mechanism.

### Contract characterization

Keep current-behavior observations separate from definite consistency requirements.

Calendar-invalid dates, boolean enum coercion, accepted aliases, blank PATCH no-ops, and temporary cutover blackout receive recorded behavior and contract-gap findings. Do not invent rejection rules or availability guarantees.

Successful mutations, however, must satisfy final SQL/vector consistency and preserve unrelated accepted writes.

## 5. Execution, reporting, cleanup, and acceptance

### Runner interface

Implement one runner with three commands:

```text
python -m tests.e2e.non_analysis.runner export-seed --config <private-config>

python -m tests.e2e.non_analysis.runner run --config <private-config> --profile full --seed 42 --resilience-repeats 10

python -m tests.e2e.non_analysis.runner cleanup --config <private-config> --run-id <run-id>
```

Profiles: `smoke`, `core`, `resilience`, `mock`, and `full`.

The configuration separates read-only source connections, managed destination settings, embedding configuration, timeout budgets, and artifact location. Secrets come from environment references and never enter reports.

### Execution sequence

1. Validate configuration, source revision, dependencies, and isolation.
2. Validate the historical export and provision a fresh stack.
3. Run smoke: ingest → PATCH → PUT → DELETE → repeat DELETE → PUT restore.
4. Run every normal and negative manifest variant.
5. Run fault/concurrency/recovery variants **10 times**, with distinct IDs and recorded seeds.
6. Run mock checks separately.
7. Recreate the stack and repeat smoke/core coverage to verify reproducibility.
8. Generate aggregate results and verify cleanup.

Start with serial test execution. Concurrency happens deliberately inside scheduled scenarios. Parallel workers remain disabled until each owns a complete independent stack.

Use bounded startup, request, barrier, and case deadlines based on actual retry budgets and declared operation counts. Never rerun assertions until green; later attempts retain earlier failures.

Measure latency by named workload, including 100-item bulk deletion. No latency or throughput SLA is invented.

### Evidence and artifacts

For each variant, retain:

- Application SHA, environment fingerprint, service/model versions, seed, and run ID.
- Sanitized HTTP requests/responses and correlation IDs.
- SQL and complete Qdrant before/after snapshots.
- Expected/observed assertions.
- Fault matches, attempts, barrier events, and upstream outcomes.
- Application/proxy logs and process exits.
- Cleanup results and defect classification.

Produce JUnit XML, structured JSON, a readable Markdown report, and a checklist-to-variant coverage matrix.

Store historical exports and raw evidence under the ignored directory `D:\Jco_Projects\tavanir-ai-assistant-v2\tests\e2e\reports`. Commit synthetic fixtures and harness code only.

### Guaranteed cleanup

In finalizers:

1. Restore proxies/services and release held transactions.
2. Settle or stop owned application processes.
3. Capture failure evidence.
4. Purge exact registered vector parents/points.
5. Physically remove exact registered SQL fixture rows.
6. Verify unchanged historical sentinels.
7. Remove only run-owned containers, networks, and volumes.

Ordinary DELETE is insufficient administrative cleanup because it retains SQL rows and may skip orphan vectors.

### Completion gates

**Implementation complete:** every checklist item/variant is mapped; harness controls work; commands reproduce the suite; analysis calls are prohibited.

**Execution complete:** every mandatory variant has an outcome, with no unexplained `Blocked` or `Not run`; required evidence and cleanup checks are complete.

**Readiness pass:** no material consistency failure, accepted-write loss, unrelated-data change, or unresolved harness defect. Known product defects remain failures.

A full run may finish with a **failed readiness verdict** while still completing the testing objective. Deliver the implementation/runbook, coverage matrix, evidence report, and concrete defect recommendations; production remediation remains a separate task.

---

# Non-analysis API E2E test checklist

## Review baseline and scope

- Reviewed branch: **local `develop`**.
- Reviewed commit: **`79cf6105204b150702afc8dc6e2b2dabffab85ab`** (`79cf610`). All source inspection used this immutable Git revision.
- Checklist prepared: **2026-10-03**.
- Evidence: static inspection of endpoint registration, schemas, use cases, DI wiring, adapters, repositories, error handlers, contracts, and existing tests. **No live E2E scenarios have been executed or marked passed.** This document is a test plan, not a release-readiness verdict.
- Coverage: the implemented HTTP surface and its connected ingestion, update, and deletion workflows. No remote fetch was performed; this baseline is the locally available `develop` revision.
- **Excluded:** `POST /api/v1/suggestions/analyze` and all suggestion analysis, similarity retrieval, reranking, prompt preparation, generation, and LLM-output scenarios. Do not call analysis to verify any case below; inspect the databases directly.
- Historical extraction/ingestion and generation use cases have no HTTP endpoint in the reviewed host. Worker/CLI ingestion, MSSQL extraction, alias switching jobs, regulation ingestion, and unexposed use cases are outside this endpoint checklist.

### How to use the checklist

Each checkbox has a stable case ID. Record `Not run`, `Pass`, `Fail`, or `Blocked` in the [execution log](#execution-log). Check the box only after the request, response, and applicable database assertions pass. For cases with multiple variants, record **every variant** separately; one successful variant does not complete the case.

Unqualified expectations describe the reviewed implementation. **PROBE** identifies a safety invariant, suspected defect, or behavior requiring a product decision; its current coded behavior is stated separately. Reproducing a known inconsistency is evidence of a defect, not a successful consistency test. **FAULT** requires controlled failure injection. Ordinary manual cases use the real application, PostgreSQL, Qdrant, and embedding provider. Mock-mode checks are listed separately and cannot establish real database correctness.

Run independent cases on fresh IDs. Run lifecycle cases in the stated sequence. Take snapshots before every mutation or failure test and inspect state after the operation settles. Never infer success from HTTP status alone.

## Endpoint inventory

The prefix `/api/v1` comes from the master router. Sources: [S01], [S02], [S03], [S18].

| Method | Path | Connected behavior | Checklist coverage |
| --- | --- | --- | --- |
| POST | `/api/v1/suggestions/ingest` | `IngestSuggestionUseCase.execute` | Common, validation, ingestion, dependencies, lifecycle |
| PUT | `/api/v1/suggestions/{suggestionId}` | `UpdateSuggestionUseCase.execute_put` | Common, validation, PUT, mutation failures, lifecycle |
| PATCH | `/api/v1/suggestions/{suggestionId}` | `UpdateSuggestionUseCase.execute_patch` | Common, validation, PATCH, mutation failures, lifecycle |
| DELETE | `/api/v1/suggestions/{suggestionId}` | `DeleteSuggestionUseCase.execute` | Common, deletion, lifecycle |
| POST | `/api/v1/suggestions/bulk-delete` | `BulkDeleteSuggestionsUseCase.execute` -> single delete per item | Common, bulk deletion, lifecycle |
| GET | `/` | Host metadata | Host checks |
| GET | `/health` | Host liveness only | Host checks |
| GET | `/scalar` | Scalar documentation HTML | Host checks |
| GET | `/static/scalar.js` | Mounted static asset | Host checks |
| GET | `/openapi.json` | FastAPI-generated API schema | Host checks |
| GET | `/docs` | FastAPI Swagger UI | Host checks |
| GET | `/docs/oauth2-redirect` | FastAPI default docs helper | Host checks |
| GET | `/redoc` | FastAPI ReDoc UI | Host checks |
| POST | `/api/v1/mock/reset` | Reset process-local in-memory store; mounted only in mock mode | Mock checks |
| POST | `/api/v1/suggestions/analyze` | Suggestion analysis | **Excluded; no test scenarios** |

There is no GET suggestion/list endpoint in this revision. Database inspection is necessary to verify stored fields. Public host/docs endpoints do not use API-key authentication. The five suggestion mutation endpoints and mock reset do.

## Execution preparation

- [ ] **SET-01** Record the application commit, base URL, run ID, tester, date, configuration, and service versions. To execute this exact checklist baseline, the running app must use `79cf610`; record differences before applying it to a later revision.
- [ ] **SET-02** Start the real host with `IS_MOCK=false` / `src.main:app`; verify `/` and `/health` report `mockMode: false`. Do not run against `src.presentation.mock_server:app` for real-store tests.
- [ ] **SET-03** Confirm PostgreSQL has the migrated `suggestions` table and read access for verification. Confirm the embedding provider/model works and its actual dimension matches Qdrant. Use configured values, not assumed default ports.
- [ ] **SET-04** Resolve the configured `QDRANT_SUGGESTION_ALIAS` to its physical collection and record both names. Online ingest/PUT/PATCH/DELETE use this **alias**, not the historical ingestion staging repository. Default alias: `tavanir_suggestion_active`; default physical target: `tavanir_suggestion_v1`.
- [ ] **SET-05** Verify the alias target has configured dense and sparse vector names and the matching dense dimension; defaults are `dense`, `sparse`, and `768`. This checklist does not create collections or switch aliases.
- [ ] **SET-06** Configure the API-key header using `API_KEY_NAME` (default `X-API-Key`) and the environment's actual key. Keep the key out of screenshots and result files. Send JSON bodies with `Content-Type: application/json`.
- [ ] **SET-07** Use a unique run prefix such as `e2e-20261003-a-`. Record IDs for fresh, active, deleted, missing, concurrency, and fault cases. Keep IDs within 64 characters except deliberate boundary tests.
- [ ] **SET-08** Save one unrelated active suggestion as a sentinel. Check its SQL row and vector-point snapshot after each mutation/fault case to catch broad cleanup or incorrect filters.
- [ ] **SET-09** Record `EMBEDDING_BATCH_SIZE`, `QDRANT_BATCH_SIZE`, SDK retry settings, Qdrant retries, and timeouts. Defaults: embedding batch `128`, vector batch `64`, embedding timeout `30s`. Update cutover has three attempts with `0.2s`, then `0.4s` delays, in addition to lower-level retries where applicable. Do not treat the first timeout as the final request result.
- [ ] **SET-10** Verify normal startup resources. `container.init_resources()` also initializes generation/tokenizer resources even though analysis is excluded; missing local tokenizer assets can block host startup. Record an environment blocker instead of inventing an ingestion failure result.
- [ ] **SET-11** Prepare reversible fault injection against disposable test services: a network proxy, controlled service stop/restart, or a test DB connection for lock scheduling. Match the configured Qdrant transport (HTTP or gRPC). Confirm the exact phase and whether an operation applied before its response was lost. Some local-component failures need an additional harness; mark them blocked if unavailable.
- [ ] **SET-12** Agree any latency/load thresholds before measuring them. The reviewed code supplies no endpoint latency SLA, global request-size limit, or guaranteed recovery deadline. Record measured values without inventing acceptance limits.

Sources: [S17], [S13], [S14].

### Reproducible lock and fault scheduling

To hold the same lock as the application, compute the key using the reviewed [lock helper](../../src/application/utils/advisory_lock.py): SHA-256 of the exact UTF-8 suggestion ID, first eight bytes interpreted as a signed big-endian integer. This standalone Python snippet requires only the standard library:

```python
import hashlib

suggestion_id = "e2e-20261003-a-basic"
lock_key = int.from_bytes(
    hashlib.sha256(suggestion_id.encode("utf-8")).digest()[:8],
    byteorder="big",
    signed=True,
)
print(lock_key)
```

In a separate connection to the same test PostgreSQL database, disable autocommit, replace `<lock-key>` with the printed integer, and keep the transaction open while sending the HTTP request:

```sql
BEGIN;
SELECT pg_advisory_xact_lock(<lock-key>);
-- Send the API request from another client and collect its response.
ROLLBACK;
```

For network faults, select the exact request by test ID and operation, then distinguish: (a) reject before forwarding, (b) forward/apply but suppress the acknowledgement, and (c) delay/release through a barrier. For update tests, use SQL version polling and captured staging point IDs to place the barrier before/after commit, promotion, or purge. For a later-batch failure, allow earlier slices to apply before rejecting the selected slice. Record the schedule and restore the proxy afterward. Random simultaneous requests alone cannot prove a concurrency branch was exercised.

## Fixtures and request shapes

Bodies are **flat JSON objects**, not wrapped in `data`. Error pointers use logical `/data/...` paths despite this flat request shape. Normal responses use the `status` + `data` envelope.

### Fixture A: short suggestion without commentary

```json
{
  "suggestionId": "e2e-20261003-a-basic",
  "title": "بهینه سازی مصرف انرژی",
  "problem": "مصرف بالای انرژی در تجهیزات روشنایی",
  "solution": "نصب تجهیزات کم مصرف و کنترل هوشمند",
  "status": "APPROVED"
}
```

With short core fields and no substantive commentary, expect **3** chunks: one `title`, one `problem`, one `solution`. The response is:

```json
{
  "status": 201,
  "data": {
    "suggestionId": "e2e-20261003-a-basic",
    "chunksCount": 3,
    "status": "CREATED"
  }
}
```

### Fixture B: full metadata and evaluation

Use Fixture A with a new ID and these additions:

```json
{
  "committeeScrutiny": 0,
  "description": "طرح پس از بررسی فنی برای اجرا تایید شد",
  "shamsiDate": "۱۴۰۳/۰۲/۱۸",
  "contextTitle": "مدیریت توزیع برق",
  "secretariatScrutiny": -2,
  "secretariatComment": "بررسی اولیه انجام شد و پرونده کامل است"
}
```

Merge the additions into the same flat object. With short core fields this produces **4** chunks, including one combined `evaluation` chunk. The date is stored as `1403/02/18`. Evaluation requires at least one normalized description/comment with **15 or more characters**, not just a scrutiny label.

### PUT, PATCH, and bulk examples

For PUT to `/api/v1/suggestions/<existing-id>`, use Fixture A's `title`, `problem`, `solution`, and `status`; omit `suggestionId` or match the path. Omitted optional fields are cleared. Expected response data: `suggestionId`, `chunksCount`, `version`, `status: "UPDATED"`; HTTP/envelope status `200`.

For PATCH to the same path:

```json
{"title": "عنوان جدید برای کاهش مصرف انرژی"}
```

For bulk deletion:

```json
{"suggestionIds": ["e2e-20261003-a-basic", "e2e-20261003-a-full"]}
```

Single DELETE returns HTTP `200` with `data: {"suggestionId": "<id>", "status": "DELETED"}`. It soft-deletes the SQL row and physically deletes that parent's vector points.

### Enumeration datasets

Run all five statuses through ingest, PUT, and PATCH, using each representation in VAL-10 below.

| Status ID | Enum name | Persian title |
| --- | --- | --- |
| 1 | `NOT_ACCEPTED` | `عدم پذیرش` |
| 2 | `REJECTED` | `رد` |
| 3 | `APPROVED` | `مصوب` |
| 4 | `PENDING` | `در حال اجرا` |
| 5 | `EXECUTED` | `اجرا شده` |

Valid committee codes are every integer **-10 through 21**. Valid secretariat codes are **-2 through 9, and 15, 16, 17**; 10-14 are invalid. Test each valid code with its enum/title mapping from [S08]. Committee `تایید` resolves to code **0**; explicit `-3` selects `APPROVED_PRELIMINARY`, which shares that title. Never infer a scrutiny code from a title alone when checking this ambiguity.

## Database verification oracles

Use these checks after every applicable scenario. Sources: [S08], [S13], [S14], [S15], [S16].

### PostgreSQL snapshot

Run a read-only query for the exact test ID, including deleted rows:

```sql
SELECT id, title, problem, solution, status_id,
       committee_scrutiny, committee_scrutiny_id, description,
       secretariat_scrutiny, secretariat_scrutiny_id, secretariat_comment,
       shamsi_date, context_title, is_deleted, version, created_at, updated_at
FROM suggestions
WHERE id = 'e2e-20261003-a-basic';
```

**SQL-NEW:** exactly one row; normalized content/metadata; correct numeric `status_id`; `is_deleted=false`; `version=1`; populated timestamps. Optional fields omitted on ingestion are SQL NULL.

**SQL-UPDATE:** same ID and `created_at`; `updated_at` reflects the update; version increments by one for each accepted PUT/PATCH, including a repeated identical request; normalized candidate fields; `is_deleted=false`. Allow DB timestamp precision when comparing.

**SQL-DELETE:** row remains; content/metadata remain; `is_deleted=true`; version increases by one on the first successful deletion; repeat deletion does not increase it again. A successful compensating restore after a vector-purge failure yields `is_deleted=false` and **original version + 2** with the real SQL repository.

**SQL-UNCHANGED:** all business fields, deletion flag, version, and timestamps match the snapshot. For a fresh failed ingestion with successful compensation, the row is physically absent rather than merely soft-deleted.

### Qdrant snapshot

Inspect through the configured runtime alias and record its physical target. Scroll by exact `parent_id`, request payload and vectors, and **follow pagination** until no `next_page_offset` remains. Inspect all states, not only `active`, so staging/deprecated leftovers cannot hide.

Example read request to Qdrant (use its own configured authentication if enabled):

```text
POST <qdrant-base-url>/collections/<runtime-alias>/points/scroll
```

```json
{
  "filter": {
    "must": [{"key": "parent_id", "match": {"value": "e2e-20261003-a-basic"}}]
  },
  "with_payload": true,
  "with_vector": true,
  "limit": 100
}
```

**VEC-NEW / VEC-UPDATE:** point count equals `data.chunksCount`; every `parent_id` matches the SQL ID; point ID equals payload `chunk_id`; IDs are unique UUIDs; every lifecycle `chunk_status` is lowercase **`active`**; no `staging`/`deprecated` leftovers after normal success. Qdrant payload fields use **snake_case**. `status` is the Persian suggestion status, independent of the lifecycle `chunk_status`.

Compare `context_title`, `date`, committee/secretariat titles and numeric scrutiny IDs with PostgreSQL. Optional null properties, including `parent_content`, are **omitted** from stored suggestion payloads (`exclude_none=True`); absence is expected, not an explicit JSON null. There is no vector-payload `version` field; correlate by captured chunk IDs, content, and metadata rather than assuming a version filter exists.

Named dense vectors have the configured dimension and finite values; sparse indices/values have matching lengths and finite weights. For substantive lexical fixtures, expect sparse terms. A deliberately stopword-only fixture may legitimately produce an **empty sparse vector**; it must not be rejected solely for being empty. Verify embedding-to-chunk association with provider request/response evidence when injecting reordered output.

One title chunk has `sub_index=0`; with a substantive context title it contains the `حوزه: ... | عنوان: ...` prefix. Problem and solution chunks contain only their respective field content and use contiguous `sub_index` values from zero. Only problem/solution are split; default target is 1500 characters with 150 overlap. **Title and evaluation are not split**, and an unbroken long token can exceed the splitter target. Do not assert an unconditional 1500-character bound for all chunks.

**VEC-UPDATE** additionally requires all previous point IDs to be absent; only the winning replacement set remains. **VEC-DELETE:** zero points for the parent across every state. **VEC-UNCHANGED:** exact IDs, payloads, vectors, and states match the snapshot. The sentinel and other collections/parents remain unchanged in all cases.

## Host, documentation, and transport checks

Sources: [S01], [S04], [S05], [S17].

- [ ] **HOST-01** GET `/` without a key -> `200`; plain JSON reports service `Tavanir AI Assistant V2`, version `2.0.0`, `mockMode=false`, documentation and health links. No `status/data` envelope is required here.
- [ ] **HOST-02** GET `/health` without a key -> `200`; plain JSON `status: "ok"`, service `tavanir-ai-assistant-v2`, `mockMode=false`.
- [ ] **HOST-03 — FAULT** After normal startup, make a database/provider unreachable and GET `/health`. Current behavior still reports `200/ok`; it is a **liveness** check, not evidence that either database or embedding provider is ready. Restore the dependency and verify a real mutation independently.
- [ ] **HOST-04** GET `/openapi.json` -> `200` valid schema; verify all five included mutation paths, methods, aliases, auth header name, and documented success responses. Analysis may remain in the schema but is not invoked/tested.
- [ ] **HOST-05** GET `/scalar` -> `200` HTML referencing `/openapi.json` and `/static/scalar.js`; open it and verify the local asset loads. Do not execute analysis via the UI.
- [ ] **HOST-06** GET `/static/scalar.js` -> `200`, nonempty JavaScript; GET a missing static filename -> `404`, not a server crash. Record actual error envelope behavior for the static mount.
- [ ] **HOST-07** GET `/docs`, `/redoc`, and `/docs/oauth2-redirect` separately -> `200` HTML. Verify displayed schemas, excluding analysis scenarios. External Swagger/ReDoc assets may require internet; distinguish a failed CDN load from the API HTML response.
- [ ] **HOST-08** GET an unknown API path -> `404 RESOURCE_NOT_FOUND` in `errors`; use a key to avoid mixing auth expectations with routing.
- [ ] **HOST-09** Use an unsupported method on a real path, e.g. GET `/api/v1/suggestions/ingest` -> `405 METHOD_NOT_ALLOWED`; verify allowed-method headers and no DB changes.
- [ ] **HOST-10** Request the trailing-slash variant of each endpoint; record any redirect and its `Location`. Follow it once and verify only one mutation occurred. Do not mistake a redirect for endpoint success.
- [ ] **HOST-11** Send a valid CORS preflight for POST, PUT, PATCH, and DELETE, including the API-key header -> allowed response according to the configured wildcard CORS policy; OPTIONS causes no writes. Also exercise an unsupported preflight method and record its rejection.
- [ ] **HOST-12** Check startup and clean restart with persistent databases; prior rows/points survive and a subsequent mutation succeeds. Record initialization failure as blocked if required resources are missing.

## Common authentication and response checks

Run API cases against **each of the five mutation endpoints** with otherwise valid requests/preconditions. Sources: [S02], [S03], [S04], [S05], [S06].

- [ ] **API-01** Omit the API-key header -> `401 API_KEY_MISSING`, `WWW-Authenticate: ApiKey`, source `/headers/<API_KEY_NAME>`; both databases unchanged.
- [ ] **API-02** Supply a wrong ASCII key -> `401 API_KEY_INVALID`; same header/pointer and unchanged databases.
- [ ] **API-03** Supply an empty header -> characterize the header extractor's missing-key handling; expect `401`, no writes. Whitespace and extra whitespace around a valid key must not authenticate unless they are literally part of the configured key.
- [ ] **API-04** Use correct key value with different header capitalization -> normal authorized behavior; use a wrong header name -> missing-key error.
- [ ] **API-05 — PROBE** Send conflicting duplicate API-key headers and a non-ASCII value that the client can transmit. Invariant: deterministic rejection without writes or a `500`. Current `secrets.compare_digest` on non-ASCII strings can raise; record the actual result and report a defect if it does.
- [ ] **API-06** Send no key with a valid body, then no key with a schema-invalid body. Neither writes anything. Record precedence separately; do not assume malformed JSON always reaches the authentication dependency first.
- [ ] **API-07** Successful responses have integer envelope `status` matching HTTP status, camelCase external fields, expected operation status (`CREATED`, `UPDATED`, `DELETED`), and no internal vectors or secret/configuration fields.
- [ ] **API-08** Validation/domain failures have nonempty `errors`; each item has integer `status`, machine-readable `code`, and a useful logical pointer. No success `data` appears. Pydantic multi-field validation currently remains HTTP `422`, even though multiple operation failures in bulk use `400`.
- [ ] **API-09** Run a validation failure and a provider failure with `ENVIRONMENT=production`: no `debug`, traceback, or exception details in the response. Run the corresponding non-production variant and inspect `debug.exception`, `debug.cause`, `debug.stackTrace` where supplied.
- [ ] **API-10** Single internal errors without a field coordinate omit `source` entirely. Domain/validation errors retain their pointer. Bulk items use indexed pointers even for internal failures.
- [ ] **API-11** Omit `X-Request-Id` -> a nonempty response request ID; send a valid UUID -> the same ID is returned. Repeat on success, authentication error, validation error, bulk partial result, and provider error.
- [ ] **API-12 — PROBE** Supply malformed/empty request IDs and concurrent distinct UUIDs. Verify safe handling, no cross-request ID mixing, and useful correlation in available logs; record any response category missing the header.
- [ ] **API-13** Error logs identify the path/operation, suggestion ID where applicable, failed phase, and cleanup outcome. For faults, match logs to the request ID and preserve the original failure separately from compensation failures.
- [ ] **API-14** Restore a failed dependency and send a fresh valid request. It succeeds, proving the earlier fault did not leave the process or connection pool unusable.

## Shared input-validation matrix

Run applicable variants against ingest, PUT, and PATCH. For PATCH, retain one valid non-null change when testing ignored optional nulls. For PUT/PATCH use an existing active fixture. Every rejected request must preserve both pre-request database snapshots, unless a case explicitly targets a later persistence failure. Sources: [S06], [S07], [S08].

- [ ] **VAL-01** Missing body, JSON `null`, array, string, and number instead of object -> `422`; missing body uses `MISSING_REQUIRED_FIELD`, and JSON null may also be classified as a missing body; other invalid shapes use `VALIDATION_ERROR`. Repeat for bulk with its appropriate object shape.
- [ ] **VAL-02** Malformed JSON, truncated JSON, and invalid encoding -> record the framework's validation/error response; malformed JSON normally becomes `422 VALIDATION_ERROR`. No writes; no traceback in production.
- [ ] **VAL-03** Wrap a valid flat payload in `{"data": {...}}` -> `422` for missing core fields/forbidden wrapper; no silent acceptance of the wrong request shape.
- [ ] **VAL-04** Unknown extra fields, raw internal version/deletion fields (`version`, `isDeleted`), and API fields `committeeScrutinyId`/`secretariatScrutinyId` -> `422 VALIDATION_ERROR`. Numeric scrutiny IDs are derived from the scrutiny input, not separately writable API fields.
- [ ] **VAL-05** For ingest, omit each of `suggestionId`, `title`, `problem`, `solution`, `status` separately -> `422 MISSING_REQUIRED_FIELD`; for PUT omit each of the four core fields. Test several missing fields together and inspect all schema errors without assuming fixed ordering.
- [ ] **VAL-06** Text fields `title`, `problem`, and `solution` as `null`, numbers, booleans, arrays, or objects -> `422` (type validation). PATCH text-field `null` instead follows PATCH's ignore semantics; test in PAT-03. Status uses its separate enum parsing below.
- [ ] **VAL-07** `title`, `problem`, or `solution` as `""` -> `422 VALIDATION_ERROR`; whitespace-only ingest text fields reach domain validation -> `422 INVALID_SUGGESTION_CONTENT`; whitespace-only PUT/PATCH text fields -> `422 VALIDATION_ERROR`.
- [ ] **VAL-08** Each of `title`, `problem`, and `solution` at trimmed lengths 1, 4, and 5, with other fields valid -> 1/4 rejected `422 INVALID_SUGGESTION_CONTENT`; substantive length 5 accepted, subject to normalization still leaving valid content.
- [ ] **VAL-09** Each noise value `-`, `--`, `---`, `.`, `..`, `...`, `ندارد`, `بدون شرح`, `هیچ`, `ثبت نشده`, `موردی ندارد`, `عدم وجود` in each of `title`, `problem`, and `solution` -> `422 INVALID_SUGGESTION_CONTENT`. Also test raw text that becomes too short/noise after normalization.
- [ ] **VAL-10** Each of the five statuses as integer, ASCII numeric string, Persian-digit numeric string, Arabic-Indic numeric string, exact enum name, and exact Persian title -> accepted and same SQL `status_id`/vector Persian `status`. Surround string forms with whitespace; trimming is supported.
- [ ] **VAL-11** Status 0, 6, negative integer, unknown enum/title, lowercase enum name, empty/whitespace, float, object, array -> `422 INVALID_SUGGESTION_STATUS`; explicit null on ingest/PUT is invalid. PATCH null is ignored when another valid change exists.
- [ ] **VAL-12 — PROBE** Status booleans: `true` currently follows integer parsing as ID 1; `false` is invalid ID 0. Scrutiny booleans can map to codes 0/1. Record this coercion explicitly; if the API requires booleans to be invalid, mark the acceptance as a contract gap.
- [ ] **VAL-13** Every valid committee code -10..21 and every valid secretariat code -2..9/15..17 -> accepted; verify SQL IDs/titles and all vector payloads. Sample equivalent numeric strings, Persian/Arabic digits, enum names, Persian titles, Arabic ي/ك variants and half-spaces for scrutiny lookups.
- [ ] **VAL-14** Committee `تایید`, `APPROVED`, `0`, and `-3` -> title `تایید`; first three map to 0, explicit -3 maps to -3. Preserve the numeric distinction across an unrelated PATCH and SQL reload.
- [ ] **VAL-15** Invalid committee -11/22/unknown name, and invalid secretariat -3/10/14/18/unknown name, plus float/list/object -> `422 INVALID_COMMITTEE_SCRUTINY` or `INVALID_SECRETARIAT_SCRUTINY` with canonical field pointer.
- [ ] **VAL-16** Optional scrutiny omitted, null, empty, and whitespace -> no scrutiny for ingest/PUT; existing scrutiny retained for PATCH. Optional text (`description`, `contextTitle`, `secretariatComment`) omitted/null/blank follows the same replace-versus-ignore semantics.
- [ ] **VAL-17** Valid date with ASCII, Persian, and Arabic-Indic digits and surrounding whitespace -> same ASCII `YYYY/MM/DD` in SQL and vectors. Date omitted/null/blank clears on PUT and stays absent on fresh ingest; PATCH preserves existing date.
- [ ] **VAL-18** Dates with wrong separator, unpadded month/day, wrong digit count, year 0999/5000, month 00/13, day 00/32, suffix text -> `422 INVALID_SHAMSI_DATE`; pointer currently defaults to `/data/date` rather than the request alias `shamsiDate`.
- [ ] **VAL-19 — PROBE** Calendar-invalid but regex-valid dates (`1402/07/31`, `1402/12/30`) are currently accepted. Record as a calendar-validation limitation; confirm whether calendar correctness is required before marking this behavior acceptable.
- [ ] **VAL-20** `shamsiDate` number/boolean/list/object -> non-null values are stringified by the schema and ordinarily fail date validation. Verify no strange input is stored as an arbitrary date or produces a server crash.
- [ ] **VAL-21** Legacy `tributaryScrutiny`/`tributaryComment` alone -> same canonical secretariat SQL fields/vector metadata as equivalent modern names, on ingest, PUT, and PATCH.
- [ ] **VAL-22** Both modern and legacy scrutiny keys non-null, or both comment keys non-null -> `422 VALIDATION_ERROR`, including blank strings. Legacy null plus non-null canonical value and cross-pair canonical scrutiny + legacy comment are allowed. **PROBE:** canonical null plus non-null legacy value must be exercised separately in camelCase and snake_case; the pre-validator injects a snake_case canonical key, so an existing camelCase-null key can shadow it and trigger duplicate/extra-field rejection. Do not promise uniform acceptance across spellings.
- [ ] **VAL-23 — PROBE** Snake_case request names are currently accepted (`populate_by_name=True`). Exercise equivalent snake_case and mixed-style payloads; responses remain camelCase. Supply both aliases of one field and record extra-field rejection/precedence; do not assume strict camelCase enforcement despite the naming contract.
- [ ] **VAL-24** Optional text numeric/boolean/array/object -> `422 VALIDATION_ERROR`. Surround valid text with spaces and verify expected trimming/normalization, not accidental loss of content.
- [ ] **VAL-25 — PROBE** Ingest ID lengths 1, 64, 65; contextTitle normalized lengths 255 and 256 on ingest/PUT/PATCH. 64/255 must persist; 65/256 exceed SQL storage limits but the schema has no matching max constraint, so current persistence may return `500 INTERNAL_ERROR`. Verify rollback/staging cleanup; record the validation gap.
- [ ] **VAL-26** Unicode/Persian ID and case-distinct IDs within SQL bounds -> exact identity preserved, no text normalization applied to the ID. Ingest trims surrounding ID whitespace; path IDs for PUT/PATCH/DELETE are used as supplied.
- [ ] **VAL-27 — PROBE** Percent-encoded spaces and special characters in path IDs, slash-containing IDs, omitted ID segment, and very long path IDs -> record routing versus lookup behavior; no mutation of a different ID. A missing segment is routing failure, not a guaranteed field-level `422`.
- [ ] **VAL-28** Include additional query parameters and an incidental body on DELETE -> characterize ignored inputs; only the path-selected suggestion changes. No query/body field can redirect a mutation to a different ID.
- [ ] **VAL-29** Ingest suggestionId empty, whitespace-only, null, number, boolean, array, or object -> `422 VALIDATION_ERROR`; no row/points. Compare leading-zero/digit-script IDs (`00123`, `123`, Persian digits, ASCII digits): these are distinct stored strings, not numeric aliases.
- [ ] **VAL-30 — PROBE** Send JSON using an application/json charset, a +json media type, no Content-Type, and a conflicting text/plain/form/multipart type. Record decoding/validation behavior; wrong representations must cause no writes. Do not assume an implemented `415` policy absent from the code.
- [ ] **VAL-31 — PROBE** Duplicate JSON property names, escaped Unicode versus literal Unicode, and large valid/invalid bodies -> record parser behavior and persistence identity; never infer a request-size limit or deterministic alias precedence without evidence. Measure resource use against agreed thresholds.
- [ ] **VAL-32** Use valid suggestion IDs equal to route words such as `ingest` and `bulk-delete` with PUT/PATCH/DELETE -> only the path-selected row changes through that method; POST's fixed routes retain their own request contracts.

## Ingestion: success, chunking, and duplicate behavior

Sources: [S09], [S13], [S14], [S15], [S16]. Apply SQL-NEW and VEC-NEW to every success.

- [ ] **ING-01** Ingest Fixture A -> `201`, matching ID, `CREATED`, `chunksCount=3`; SQL-NEW, VEC-NEW, sentinel unchanged.
- [ ] **ING-02** Ingest Fixture B -> `201`, `chunksCount=4`; full normalized metadata in SQL and every vector payload; one evaluation chunk includes both substantive comments and appropriate labels.
- [ ] **ING-03** Only committee description substantive; only secretariat comment substantive; both substantive -> each produces exactly one evaluation chunk. A scrutiny enum alone does not produce evaluation.
- [ ] **ING-04** Normalized commentary lengths 14, 15, and 16, plus commentary noise placeholders -> evaluation absent below 15/noise, present at 15/16. Check the threshold after normalization, not raw input length.
- [ ] **ING-05** Context title null, below 5 characters, and at/above 5 substantive characters -> metadata stored as supplied/normalized; title-chunk prefix appears only when context is valid for the chunker's anchoring rule.
- [ ] **ING-06** Long problem and solution across paragraph/newline/Persian punctuation boundaries -> multiple field-isolated chunks with contiguous per-field indices and sensible overlap; count equals actual persisted points; no title/evaluation content leaks into those fields.
- [ ] **ING-07 — PROBE** Extremely long title, long evaluation commentary, and an unbroken long problem/solution token -> inspect actual chunk length and provider limit behavior. Title/evaluation are unsplit; generic provider context failure is currently `500 EMBEDDING_FAILED`, not a guaranteed `422`.
- [ ] **ING-08** Text with Arabic ي/ك, diacritics, emojis, repeated letters, ZWNJ, Persian/Arabic digits, tabs/newlines -> expected normalized text persists consistently in both stores; neither ID nor enum identity is altered.
- [ ] **ING-09** Core content with Markdown headings/lists/checklists, code, tables, URLs/links, math, and decimal numbers -> normalization preserves protected syntax/content while normalizing surrounding Persian. Compare to an independently reviewed fixture expectation.
- [ ] **ING-10** Lexically sparse/stopword-heavy valid content -> dense vector stored; empty sparse representation is allowed when all lexical tokens are filtered. Separately test tokens near BM25's configured max length.
- [ ] **ING-11** Duplicate existing active ID with identical body -> `409 SUGGESTION_ALREADY_EXISTS`, pointer `/data/suggestionId`; SQL/vector state including IDs/version/timestamps unchanged.
- [ ] **ING-12** Duplicate active ID with different valid body -> same `409`, no overwrite/purge. Duplicate soft-deleted ID -> same `409`; ingestion cannot restore a deleted row (PUT can).
- [ ] **ING-13** Duplicate ID with domain-invalid core content but schema-valid shape -> duplicate pre-check is first in the use case, so `409` can precede domain content rejection. Schema-invalid duplicate body still fails before entering the use case.
- [ ] **ING-14** Pre-seed residual vectors of any lifecycle state for an ID absent from SQL, then ingest it -> residual points purged, only fresh active points remain, one new SQL row. Use controlled setup on disposable data.
- [ ] **ING-15** Generate enough chunks to cross a Qdrant slice and embedding sub-batch boundary; test exact configured boundary and one beyond -> all points stored once, correct count/association, no duplicate points after transient retry.
- [ ] **ING-16** Supply status and scrutiny labels with seemingly inconsistent business meanings -> current code accepts independently valid enums; verify the stored combination is unchanged rather than enforcing an undocumented committee workflow.
- [ ] **ING-17 — PROBE** Include literal `_TAVANIR_TOKEN_0_` in otherwise valid text alongside a protected code/URL block -> normalization must preserve the literal text and protected block independently. Capture any placeholder collision/corruption as a normalization defect.
- [ ] **ING-18** One evaluation side has substantive commentary and the other has short/noise commentary -> one evaluation point includes only the substantive side's block; valid scrutiny metadata from both sides still propagates to every chunk.

## Dependency and ingestion failure scenarios

Faults apply to the **real HTTP request**. Where a local component cannot be faulted through the deployed test host, mark `Blocked: needs fault harness`; a test that replaces the use case with an AsyncMock is not E2E evidence. Sources: [S05], [S09], [S13], [S14], [S16].

### Error mapping actually reachable through these workflows

| Injected failure | Current top-level single-request status/code | Important distinction |
| --- | --- | --- |
| Dense provider connection failure/timeout | `503 EMBEDDER_CONNECTION_FAILED` | SQL/vector writes have not begun |
| Dense provider 401, 429, context-limit 400, other provider API failure | `500 EMBEDDING_FAILED` | Adapter currently does not emit specialized embedder auth/context exceptions; no guaranteed `Retry-After` header |
| Sparse embedder failure | `500 EMBEDDING_FAILED` | No persistence has begun |
| Normalizer throws `TextNormalizationError` | `422 TEXT_NORMALIZATION_FAILED` | No persistence has begun |
| Chunker raises `ChunkingError`/`SuggestionChunkingError` or returns no chunks | `422 CHUNKING_FAILED` | Needs a fault harness for otherwise valid mandatory fields; arbitrary runtime exceptions use `500 INTERNAL_ERROR` |
| Dense/sparse response count mismatch at strict zip | `500 INTERNAL_ERROR` | No persistence has begun |
| Qdrant adapter storage failure | `500 RETRIEVAL_FAILED` | Even when the operation is ingestion/update/delete |
| Raw SQL/runtime exception | `500 INTERNAL_ERROR` | No dedicated DB-unavailable HTTP translation is implemented |

- [ ] **DEP-01 — FAULT** Dense provider unreachable, connection reset, and request timeout -> mapping above, no SQL row/no points for fresh ingest; unchanged old state for PUT/PATCH. After exhausting configured retries, the request terminates and the host remains usable.
- [ ] **DEP-02 — FAULT** Provider returns 401, 429 with/without retry metadata, 500, unknown model, and context-limit error -> current `500 EMBEDDING_FAILED`; no writes. Record code/contract mismatch rather than expecting registry-only codes that the adapter never raises.
- [ ] **DEP-03 — FAULT** Provider response has missing/extra embeddings -> `500 INTERNAL_ERROR`, no writes. Reordered valid embedding response indices must associate vectors with correct chunks; duplicate/missing indices of the correct count are a protocol-integrity probe, not validated by count alone.
- [ ] **DEP-04 — FAULT** Wrong vector dimension, non-finite values, malformed sparse representation, or provider response decoding failure -> controlled rejection, no false success. Record whether failure occurs before persistence or at Qdrant; dimension rejection there uses `500 RETRIEVAL_FAILED` and workflow compensation applies.
- [ ] **DEP-05 — FAULT** Local normalizer/sparse computation failure, chunker `ChunkingError`/`SuggestionChunkingError`, zero chunks, and arbitrary chunker runtime exception -> mapping above and no pre-persistence writes; distinguish domain chunking `422` from runtime `500 INTERNAL_ERROR`. Record harness limitations explicitly.
- [ ] **ING-F01 — FAULT** PostgreSQL unavailable during duplicate pre-check -> `500 INTERNAL_ERROR`, no vector calls/writes and no SQL insert.
- [ ] **ING-F02 — FAULT** SQL save/commit definitely fails before applying -> `500 INTERNAL_ERROR`, no row/points. Separately lose the commit acknowledgement after application: inspect committed state; do not assume rollback undoes an acknowledged-unknown commit.
- [ ] **ING-F03 — FAULT** Qdrant residual purge fails after SQL commit -> `500 RETRIEVAL_FAILED`; successful compensation removes new SQL row; record residual old points if vector cleanup also fails.
- [ ] **ING-F04 — FAULT** Cause a fatal first vector upsert failure or exhaust transient retries; repeat on a later slice after earlier slices applied -> `500 RETRIEVAL_FAILED`; successful cleanup leaves zero parent points and SQL row absent. Verify all slices, not just the last attempted one.
- [ ] **ING-F05 — FAULT** Fail promotion before demotion, between demotion/promotion, and after promotion applies but before acknowledgement -> error response and compensating deletion. Inspect actual point states; a lost acknowledgement can leave **active** orphans if cleanup fails, not only staging points.
- [ ] **ING-F06 — FAULT** Upsert/promotion fails and vector compensation fails, SQL compensation succeeds -> error, SQL row absent, residual points possible; record IDs/states and original versus cleanup error. No implemented worker is guaranteed to repair them.
- [ ] **ING-F07 — FAULT** Vector operation fails, vector cleanup succeeds, SQL compensation fails -> error, SQL row may remain with no vectors. A subsequent ingest of that ID normally returns `409`; record the inconsistency and required repair.
- [ ] **ING-F08 — FAULT** Both compensations fail -> original error returned; inspect both actual stores, capture critical logs, leave case failed/blocked for recovery. Never mark a partially stored suggestion as a successful ingestion.
- [ ] **ING-F09 — FAULT / PROBE** Kill/cancel the request after SQL commit and during vector upsert/promotion -> capture SQL-only, staging, partial, or active state; restart and retry same ID. Cancellation/crash can bypass `except Exception` compensation; duplicate pre-check may prevent automatic completion.
- [ ] **ING-F10 — PROBE** Send simultaneous same-ID ingests with distinguishable content; hold both after duplicate pre-check, then release. Invariant: one accepted creation and no cross-request overwrite/purge. Current ingestion has no lock/recheck and SQL uses upsert, so both can pass and overwrite/delete each other's data. Repeat with one request failing after SQL save.
- [ ] **ING-F11 — FAULT** A transient Qdrant upsert-slice failure recovers before configured attempts are exhausted -> `201` and complete SQL-NEW/VEC-NEW; retry does not duplicate points. Also test failure one attempt beyond the allowed recovery window.
- [ ] **ING-F12 — FAULT** Runtime alias/collection missing or pointing at an incompatible vector schema after startup -> Qdrant operation failure, `500 RETRIEVAL_FAILED`; verify SQL compensation and actual target isolation. Restore the original alias configuration before a fresh retry.
- [ ] **ING-F13 — FAULT** Fully compensated failed ingest, then dependencies recover and same-ID ingest is retried -> `201`, exactly one coherent row/point set, no failed-attempt point IDs. If only orphan vectors remained with SQL absent, retry's residual purge removes them.
- [ ] **ING-F14** Seed orphan vectors with no SQL row, then trigger an early validation/embedding failure -> SQL remains absent and original orphan points remain unchanged; early failures happen before residual purge. Existing SQL row with no points still conflicts `409` on ingestion; this API is not a repair operation.

## PUT: full replacement and restoration

Sources: [S03], [S07], [S10]. Run shared validation cases too. Every normal success must satisfy SQL-UPDATE and VEC-UPDATE.

- [ ] **PUT-01** Replace all fields on an active Fixture B -> `200 UPDATED`, response version old+1; both stores contain replacement content/metadata, old vector IDs absent.
- [ ] **PUT-02** Omit all optional fields while supplying four required core fields -> SQL optional fields become NULL; date/context/scrutiny metadata cleared in new points; previous evaluation chunk absent.
- [ ] **PUT-03** Explicit null and blank optional fields -> same clearing behavior; null core/status fails shared validation and preserves old state.
- [ ] **PUT-04** PUT a soft-deleted row -> `200`, `is_deleted=false`, version deleted-row version+1, complete new active points. Repeat when deleted row still has leftover points and confirm superseded points are removed.
- [ ] **PUT-05** PUT nonexistent ID -> `404 SUGGESTION_NOT_FOUND`, pointer `/data/suggestionId`; no SQL creation, no vector writes. PUT is not an upsert API for absent suggestions.
- [ ] **PUT-06** Body suggestionId omitted, null, exactly matching, and matching after surrounding spaces -> accepted with path ID used. Different nonblank ID -> `422 VALIDATION_ERROR`, no writes.
- [ ] **PUT-07 — PROBE** Body suggestionId `""`/whitespace currently passes the match check and the path ID is used. Record this behavior separately from the docstring's strict matching language.
- [ ] **PUT-08** Change only status, scrutiny, date, or context while retaining core values -> regenerated chunks/vectors carry updated metadata everywhere; numeric scrutiny identity preserved.
- [ ] **PUT-09** Add/remove substantive commentary and grow/shrink problem/solution -> new chunk count increases/decreases correctly; no leftover evaluation/sub-chunks or deprecated points.
- [ ] **PUT-10** Send the exact same valid PUT twice sequentially -> both `200`; each increments version and replaces point IDs. Final business content stable; this implementation does not preserve version/point IDs on repeated identical PUT.
- [ ] **PUT-11** Replace old non-null secretariat evaluation with an omitted one, then restore with modern/legacy keys -> proper removal then reconstruction of both SQL and vector metadata.
- [ ] **PUT-12** Fail a PUT on an existing active and a deleted row using each mutation failure phase below; distinguish preserved active state from preserved deleted state.

## PATCH: partial update semantics

Sources: [S03], [S07], [S10]. Run shared validation cases too. Every normal success must satisfy SQL-UPDATE and VEC-UPDATE.

- [ ] **PAT-01** PATCH each core field separately -> only that business field changes; other fields/metadata remain equivalent after normalization; version old+1; all vectors rebuilt correctly.
- [ ] **PAT-02** PATCH status, committee scrutiny, description, shamsiDate, contextTitle, secretariat scrutiny, and secretariat comment separately -> each overlay works **without requiring status in the body**; other evaluation fields preserved.
- [ ] **PAT-03** Include null core/optional fields alongside one valid change -> null values ignored, old values retained. PATCH cannot clear fields with null.
- [ ] **PAT-04** `{}` and all-null bodies -> `422 VALIDATION_ERROR`; unchanged SQL/vector state.
- [ ] **PAT-05** Include suggestionId/suggestion_id with matching, different, null, or empty value -> always `422 VALIDATION_ERROR`; ID presence itself is forbidden.
- [ ] **PAT-06** Provided core empty/whitespace -> `422 VALIDATION_ERROR`; short/noise core -> `422 INVALID_SUGGESTION_CONTENT`; old state unchanged.
- [ ] **PAT-07 — PROBE** Only blank optional text/date/scrutiny, e.g. `{"description":""}`, `{"shamsiDate":" "}`, `{"committeeScrutiny":""}` -> raw pre-validator sees a non-null value, later validators turn it into null; current use case can accept a no-op, re-embed, and increment version. Record as behavior/contract gap, not a meaningful field clear.
- [ ] **PAT-08** Blank optional values alongside another valid change -> blank values normalize to null and preserve their old values; only the intended change appears.
- [ ] **PAT-09** PATCH absent ID and soft-deleted ID -> `404 SUGGESTION_NOT_FOUND`, no resurrection/no vector writes.
- [ ] **PAT-10** Add secretariat comment only to a row with no secretariat evaluation -> evaluation object created; add scrutiny only -> code/title metadata without fabricating commentary; preserve existing comment/code on later independent changes.
- [ ] **PAT-11** Change commentary below/at/above 15 normalized characters -> evaluation chunk removed/added correctly; change long problem/solution to shorter text -> old sub-chunks disappear.
- [ ] **PAT-12** PATCH several fields together -> one version increment, one coherent replacement set; no mixture of old/new metadata.
- [ ] **PAT-13** PATCH a field to its existing value twice -> current behavior is two successful updates, two version increments, new vector IDs each time. Record this behavior when testing client retries.
- [ ] **PAT-14** PATCH modern versus legacy secretariat aliases and ambiguity of committee title `تایید` -> canonical metadata consistent; conflict cases rejected before writes.
- [ ] **PAT-15** A validation-invalid value plus several valid changes -> entire request rejected, no partial field update.

## PUT/PATCH failure phases and recovery

Run every applicable fault for **both PUT and PATCH**. Freeze the original SQL version/content and complete old point set. Sources: [S10], [S13], [S14], [S16].

| Failure phase | SQL state when failure definitely precedes application | Vector state with successful cleanup |
| --- | --- | --- |
| Initial lookup / validation / normalization / chunking / embeddings | Original unchanged | Original unchanged |
| New staging upsert | Original unchanged | Original set unchanged; attempted new IDs removed |
| Lock denial / version mismatch / SQL write failure before commit | Original unchanged, apart from any legitimate concurrent winner | Attempted new IDs removed; winner/old active set preserved |
| Cutover or superseded purge **after SQL commit** | **New SQL row/version remains committed** | Depends on which vector operation applied; no SQL rollback/outbox recovery implemented |

- [ ] **MUT-F01 — FAULT** Initial SQL lookup unavailable -> `500 INTERNAL_ERROR`, no new staging points. Shared DEP faults before staging preserve old SQL and vectors.
- [ ] **MUT-F02 — FAULT** First/later-slice staging upsert failure -> `500 RETRIEVAL_FAILED`; original row/version and active IDs remain; successful cleanup removes exactly attempted new IDs, not another operation's points.
- [ ] **MUT-F03 — FAULT** Staging failure plus cleanup failure -> old active set preserved where possible; inspect residual staging points, logs, and alias target. Capture a cleanup gap rather than declaring the old/new set fully consistent.
- [ ] **MUT-F04 — FAULT** Hold the matching advisory transaction lock in another SQL connection, then mutate -> `409 SUGGESTION_IN_PROCESSING`, original SQL state preserved; this request's shadow staging IDs removed. Release the lock and verify a fresh request succeeds.
- [ ] **MUT-F05 — FAULT** Arrange two requests with the same initial version; let one commit first -> stale phase-2 request returns `409 SUGGESTION_IN_PROCESSING`; rejected request does not overwrite the winning SQL row and cleans only its own staged IDs.
- [ ] **MUT-F06 — FAULT** Delete the row or soft-delete it after PATCH's initial read; enter phase 2 -> missing/currently deleted record rejection or version conflict according to check order; no unintended resurrection. A changed version is checked before deleted state, so `409` can precede `404`.
- [ ] **MUT-F07 — FAULT** SQL save/commit failure before application -> `500 INTERNAL_ERROR`, original row/flag/version unchanged; new staging IDs removed after the transaction exits. Separately test unknown commit outcome and inspect actual committed state.
- [ ] **MUT-F08 — FAULT** Phase-2 rejection/SQL failure plus exact-ID cleanup failure -> original/winning SQL unchanged; residual staging possible; no residual is treated as an accepted update merely because its points exist.
- [ ] **MUT-F09 — FAULT / PROBE** Fail promotion transiently before application, then recover within cutover attempts -> eventual `200` only counts as a consistency pass if winning SQL and final active set match. Repeat between ACTIVE demotion and STAGING promotion.
- [ ] **MUT-F10 — FAULT / PROBE** Promotion succeeds, superseded purge fails once, next retry succeeds -> assert final replacement points remain **active**. Current retry repeats promotion, which demotes newly active points when no staging remains; HTTP `200` can therefore leave only deprecated points. This is a critical defect probe.
- [ ] **MUT-F11 — FAULT** Persistent cutover failure through all three attempts -> `500 RETRIEVAL_FAILED`; new SQL version already committed; inspect old/new/staging/deprecated states. Restart alone has no implemented outbox repair guarantee.
- [ ] **MUT-F12 — FAULT** Promotion/purge applied but acknowledgement lost -> inspect actual applied operations before retry. Check that retries cannot lose the final active set or create a misleading success response.
- [ ] **MUT-F13 — PROBE** Observe the parent continuously during normal cutover, especially with delayed second payload update. Invariant: no window with zero active chunks when uninterrupted availability is required. Current two separate demote/promote calls are not atomic despite comments.
- [ ] **MUT-F14 — FAULT** Cancel/kill the request after shadow staging, after SQL commit, and between promotion/purge -> restart; inspect orphan staging, committed SQL/new vector mismatch, and incomplete purge. Record repair requirements; no automatic reconciliation is implemented.
- [ ] **MUT-F15 — FAULT / PROBE** Retry the same PUT/PATCH after a cutover error or response loss -> version may advance again; verify final coherent content/count/active set and cleanup of all abandoned point sets. Record observable state before deciding whether a retry is safe.

## Single DELETE: success, idempotence, and compensation

Sources: [S03], [S11], [S13], [S14].

- [ ] **DEL-01** Delete active Fixture B -> `200 DELETED`, correct ID; SQL-DELETE and VEC-DELETE; sentinel unchanged.
- [ ] **DEL-02** Delete active row with zero points, with many sub-chunks, and with mixed active/staging/deprecated points -> `200`; soft-deleted row retained, every parent point purged.
- [ ] **DEL-03** Repeat deletion of the normally deleted row -> `200 DELETED`; version/timestamps unchanged on repeat; no new vectors. Real implementation is idempotent here.
- [ ] **DEL-04** Delete nonexistent SQL ID -> `404 SUGGESTION_NOT_FOUND`, source `/data/suggestionId`; no row creation. If orphan points exist for that absent ID, current behavior does not purge them; record separately.
- [ ] **DEL-05 — PROBE** Seed a deleted SQL row with leftover vectors, then DELETE again -> current early no-op returns `200` without purging. Invariant: deleted suggestions must not retain active orphan points; report the unrepaired leftovers.
- [ ] **DEL-06 — FAULT** Hold the matching advisory lock -> `409 SUGGESTION_IN_PROCESSING`; row and points unchanged. Release, then retry -> normal success.
- [ ] **DEL-07 — FAULT** SQL unavailable, soft-delete fails, or commit definitely fails before application -> `500 INTERNAL_ERROR`; no Qdrant purge; original row/points preserved. Separately inspect unknown commit-acknowledgement outcomes.
- [ ] **DEL-08 — FAULT** Qdrant purge definitely fails before deletion, SQL compensation succeeds -> `500 RETRIEVAL_FAILED`; row restored active, version original+2, content preserved; original points remain. Error response does not imply unchanged SQL version.
- [ ] **DEL-09 — FAULT** Qdrant purge fails and SQL compensation fails -> original vector error returned; row may remain deleted while points remain; capture critical logs and manual-repair need.
- [ ] **DEL-10 — FAULT / PROBE** Qdrant deletion applies but acknowledgement is lost -> code may restore SQL active with no points. Inspect both stores and record inconsistency; do not count an active SQL row alone as successful restoration.
- [ ] **DEL-11 — FAULT / PROBE** Another transaction holds the advisory lock during compensating restore -> invariant: restore must not overwrite a concurrent change. Current code logs lock failure but still reads/saves; schedule a competing write and compare final content/version/flag.
- [ ] **DEL-12 — FAULT / PROBE** Kill the app after SQL soft-delete commit but before purge; restart and retry DELETE -> current no-op can return `200` with vectors still present. Verify the data remains inconsistent and record recovery need.
- [ ] **DEL-13 — FAULT** Delete while embedding provider is down -> deletion still succeeds when SQL/Qdrant work; no embedding generation belongs to this workflow. Repeat an already-deleted no-op while Qdrant is down -> current early-return success with no Qdrant call.
- [ ] **DEL-14** Delete then PUT -> restoration succeeds with new active vectors; delete then PATCH -> `404`; delete then ingest same ID -> `409`. Preserve SQL history/versions through the sequence.

## Bulk DELETE: validation, per-item errors, and partial success

Sources: [S03], [S07], [S11], [S12]. Each item runs sequentially through the real single-delete workflow; the request is **not all-or-nothing**.

| Batch result | HTTP and body | Item error status/code |
| --- | --- | --- |
| All items succeed (including already deleted) | `200`, `status:200`, `data` array, no `errors` | None |
| Some succeed and some fail | `207`, `status:207`, both `data` and `errors` | Per-item values below |
| All items fail | `400`, only `errors` (no `data` or top-level `status`) | Per-item values below |
| Unknown ID | As determined by whole batch | `404 SUGGESTION_NOT_FOUND` |
| Lock/version processing conflict | As determined by whole batch | `409 SUGGESTION_IN_PROCESSING` |
| Other DomainError, including Qdrant VectorStorageError | As determined by whole batch | `400 DOMAIN_ERROR` |
| Unexpected runtime/SQL exception | As determined by whole batch | `400 INTERNAL_ERROR` |
| Invalid request schema | `422`, `errors`; no items executed | `MISSING_REQUIRED_FIELD` or `VALIDATION_ERROR` |

Bulk **runtime per-item** error pointers are `/data/suggestionIds/<original-zero-based-index>`. Schema missing/bounds/duplicate/blank-list errors generally point to `/data/suggestionIds`; list-element type errors can include the index. Error DTO ID/detail/index/count totals are not exposed as extra response fields; resolve runtime-failed IDs through original input positions. Bulk currently serializes optional `source`/`debug` as null where applicable, unlike single error responses using `exclude_none=True`; do not demand identical null omission.

- [ ] **BULK-01** One active ID -> `200`, data array of one DELETED item; SQL-DELETE/VEC-DELETE.
- [ ] **BULK-02** Several and exactly 100 unique active IDs -> `200`; input-order success list; each row deleted once, each vector parent empty, sentinel unchanged.
- [ ] **BULK-03** Active plus already-deleted IDs -> all succeed `200`; repeat-deleted versions remain unchanged. Entire already-deleted batch also succeeds in real mode.
- [ ] **BULK-04** Existing + missing IDs, with failure at first, middle, and last index -> `207`; successful IDs deleted, missing rows remain absent, pointers use original positions, later items still execute.
- [ ] **BULK-05** All IDs missing -> `400` errors only, every item `404 SUGGESTION_NOT_FOUND`; no writes.
- [ ] **BULK-06 — FAULT** One advisory-lock conflict and other active IDs -> `207`, conflict item `409`; conflicted row/points unchanged, others deleted. All conflicted -> whole HTTP `400`, per-item `409`.
- [ ] **BULK-07 — FAULT** Qdrant fails for one item then recovers for later items -> `207` with failed item `400 DOMAIN_ERROR`; apply DEL-08/09/10 state checks to it; other items succeed. Do not expect single-delete `RETRIEVAL_FAILED` in this bulk error item.
- [ ] **BULK-08 — FAULT** SQL/runtime failure for one item -> `400 INTERNAL_ERROR` item; subsequent items continue where dependency recovers. Permanent failure for every item -> top-level `400`, no data.
- [ ] **BULK-09** Mix missing, conflicted, domain-failed, and successful IDs -> `207`; each input belongs exactly once to data or an error pointer. Validate error order and independent database outcomes.
- [ ] **BULK-10** Missing suggestionIds -> `422 MISSING_REQUIRED_FIELD`; null, empty list, 101 IDs, string/non-list, unknown extra field -> `422 VALIDATION_ERROR`, no items executed. This differs from route prose that groups bounds under `400`.
- [ ] **BULK-11** Null/numeric/boolean/object list elements, empty ID, whitespace ID -> `422 VALIDATION_ERROR`; no item, even preceding valid entries, is deleted.
- [ ] **BULK-12** Exact duplicate and duplicate after trim (`["id", " id "]`) -> `422`; no partial execution. Case-distinct IDs remain distinct if both exist.
- [ ] **BULK-13** Surround valid IDs with spaces -> trimming selects the intended stored IDs; success response contains cleaned IDs; error pointer still refers to the original list position.
- [ ] **BULK-14** Reissue a completed all-success or partial-success batch -> previously deleted rows succeed without another version increment; still-missing IDs fail; verify new whole-batch status based on current results.
- [ ] **BULK-15 — FAULT** Keep Qdrant unavailable across every active item -> each executes its own compensation; top-level `400`/per-item `DOMAIN_ERROR`; inspect every restored row/version and vector state. No success is inferred from the response status alone.
- [ ] **BULK-16 — PROBE** Include previously deleted rows with orphan points -> their early-success result must not hide remaining points; apply DEL-05 to every reported success.
- [ ] **BULK-17 — FAULT** Disconnect the client or kill the process after some sequential items complete -> earlier deletions persist; later items may be unprocessed. Restart and inspect each input ID before retry; no batch-wide rollback is implemented.
- [ ] **BULK-18 — PROBE** Measure exactly-100 item latency and pool/lock recovery, including failures. No fabricated SLA or parallelism expectation; verify no leaked locks/connections and successful fresh request afterward.

## Cross-endpoint lifecycle and concurrency

These are distinct E2E workflows; analysis remains excluded. Use barrier/proxy scheduling for reproducible races, not just simultaneous clicks. Sources: [S09], [S10], [S11], [S12], [S13], [S14].

- [ ] **FLOW-01** Ingest -> PATCH one field -> PUT replacement -> DELETE -> repeat DELETE -> PUT restore. Expect versions `1 -> 2 -> 3 -> 4 -> 4 -> 5`, correct lifecycle flags, and final matching active points; inspect both stores at every step.
- [ ] **FLOW-02** Ingest two distinguishable suggestions -> mutate/delete/bulk-delete one -> the other row and all its point IDs/payloads/vectors remain unchanged.
- [ ] **FLOW-03** Validation/auth failures at each lifecycle stage -> neither store changes and the next valid step still works.
- [ ] **FLOW-04** Two same-ID PUTs, two PATCHes, and PUT versus PATCH from the same original snapshot -> stale mutation rejected by lock/version controls; final SQL and active vector set correspond to one coherent accepted winner. If a later request legitimately reads the new version, two sequential successes are allowed.
- [ ] **FLOW-05 — PROBE** Hold update A after SQL commit/before cutover; let update B read/commit the new version, then interleave cutovers -> invariant: final vectors match latest committed SQL; A must not activate/purge B's points. Current parent-wide promotion and superseded purge can interfere after locks are released.
- [ ] **FLOW-06 — PROBE** Stage update A, let update B commit/promote while A is stale, then release A's phase-2 cleanup -> rejected A's staging must never be promoted into B's final active set; cleanup must preserve B's points.
- [ ] **FLOW-07 — PROBE** Update versus DELETE with pauses before/after each SQL commit and vector operation -> final accepted lifecycle state matches SQL and vectors. Check update-after-delete rejection/restoration rules and deletion purging a concurrent PUT restoration's newly generated points.
- [ ] **FLOW-08 — PROBE** DELETE purge failure/compensation versus PUT/PATCH winner -> compensation must not overwrite or restore the wrong revision, or erase winning vectors. Check lock-denial path specifically.
- [ ] **FLOW-09** Two same-ID deletes with controlled lock contention -> conflict while lock held or idempotent success after commit; first actual soft-delete increments once. Observe both requests' final point purge outcomes.
- [ ] **FLOW-10 — PROBE** Bulk versus single delete, and overlapping bulk batches -> per-item statuses match lock/existence state, no unrelated deletions, no hidden orphan vectors after no-op items.
- [ ] **FLOW-11** Concurrent mutations on different IDs -> independent correct results; no false same-ID conflict, vector cross-contamination, shared response metadata, or sentinel changes.
- [ ] **FLOW-12 — PROBE** Fresh-ID ingest versus update/delete after ingest's SQL commit but before vector work -> no cross-operation purge/compensation loss. Current ingestion is not protected by update/delete advisory locking.
- [ ] **FLOW-13 — FAULT** Slow embedding on several updates while unrelated deletion/ingestion runs -> process remains usable; SQL locks are not held throughout embedding. Record measured latency against agreed limits and inspect pool recovery afterward.
- [ ] **FLOW-14 — PROBE** Lose a successful HTTP response and retry ingest/PUT/PATCH/DELETE/bulk separately -> ingest duplicate `409`; PUT/PATCH can increment again; DELETE idempotent; bulk recomputes results. Verify final state and document this retry behavior for callers.
- [ ] **FLOW-15 — FAULT** Restart after successful operations -> persisted SQL flags/versions and vector states unchanged; continue lifecycle with correct new version, without invoking analysis.

## Mock mode: separate presentation checks

These check the mock HTTP host only. They do **not** exercise real ingestion/embedding or either database. Sources: [S01], [S18].

- [ ] **MOCK-01** Start `src.presentation.mock_server:app` -> `/` and `/health` report `mockMode=true`; `/api/v1/mock/reset` exists. In real mode the reset route is absent (`404`/routing behavior), and real stores are untouched.
- [ ] **MOCK-02** Reset with missing/wrong key -> `401` without state reset; valid key -> `200`, data `message` and `seededItems:6`.
- [ ] **MOCK-03** Ingest a new mock ID, update/delete it and a seeded ID, reset, then use mutations to verify seed `sug-101` is restored and custom ID is gone. Repeat reset -> still six fresh seeds, no accumulated state.
- [ ] **MOCK-04** Mock ingest/PUT/PATCH return fixed `chunksCount=4`. Record this limitation; it must not be used to validate real chunk counts or actual point persistence.
- [ ] **MOCK-05** Repeat mock DELETE -> current mock returns `404`, unlike real idempotent `200`. Include already-deleted IDs in mock bulk and capture the resulting mock-only partial/full failures.
- [ ] **MOCK-06** Source-characterized divergence: mock PUT retains some omitted date/context/secretariat fields; mock PATCH ignores some evaluation overlays unless status is supplied. These fields are not exposed in mutation responses, and there is no GET endpoint. Verify only with an in-memory inspection harness; mark **Blocked with HTTP-only tooling**. Do not invoke analysis to inspect mock state or treat doubles as authoritative real semantics.
- [ ] **MOCK-07** Restart mock process -> seed state resets; start two mock processes -> each has separate in-memory state. No claim of shared or durable mock data.
- [ ] **MOCK-08** Auth, request validation, envelopes, camelCase response aliases, and request-ID behavior are still checked through the actual presentation layer; exclude the analysis endpoint here too.

## Known limitations and defect probes from source review

These are **static findings**, not reproduced runtime verdicts. Keep related cases open until executed. They explain why some expected invariants may fail in the reviewed revision.

| Risk / current behavior | Source evidence at reviewed commit | Cases |
| --- | --- | --- |
| Same-ID ingestion has only a pre-check; SQL upsert and parent-wide cleanup can overwrite or delete a competing request | `ingest_suggestion_use_case.py` pre-check/persistence/compensation; SQL `save` uses ON CONFLICT DO UPDATE | ING-F10, FLOW-12 |
| Vector promotion is two separate payload mutations, with a possible gap after active demotion | Qdrant `base.py` `activate_staging_chunks`, lines 358-408 | MUT-F09, MUT-F13, FLOW-05 |
| Retrying whole cutover after purge failure can demote the successful replacement set when no staging remains | Update cutover loop, lines 234-263; Qdrant promotion | MUT-F10, MUT-F12 |
| Update/delete release SQL transaction locks before parent-wide vector changes | Update phase 2/3; delete commit then purge; Qdrant superseded filter | FLOW-05..08 |
| Update failure after SQL commit has no transactional outbox/reconciliation implementation | Update lines 221-233 contain target-design FIXME; lines 234-263 implement bounded retries only | MUT-F11..15 |
| Repeated DELETE skips purge for a deleted row, leaving crash-created orphan points | Delete lines 63-78 | DEL-05, DEL-12, BULK-16 |
| Delete compensation continues even after failing to acquire its advisory lock | Delete lines 109-124 | DEL-11, FLOW-08 |
| Applied-but-unacknowledged vector operations can make SQL compensation inconsistent with actual vector state | Ingestion/deletion synchronous compensation; no distributed transaction | ING-F05..09, DEL-10 |
| API max lengths do not match SQL ID/context limits; calendar validity is not checked | Request schemas; SQL String(64)/String(255); ShamsiDate regex | VAL-19, VAL-25 |
| Raw PATCH non-null check can admit a blank-value no-op; booleans enter integer enum parsing; mixed null/legacy aliases can shadow injected fields | Patch pre-validator; shared enum parsers; request alias pre-validators | PAT-07, VAL-12/22 |
| Dense provider auth/context/rate errors use generic embedding HTTP/code mapping | Dense adapter properties + BaseOpenAIService auth fallback; exception registry | DEP-02 |
| Bulk and mock behavior differ from single real endpoint behavior | Bulk per-item catches/route serialization; mock use cases | BULK cases, MOCK-04..06 |
| Contracts and runtime differ on strict camelCase input, multi-validation/bounds status, and date pointer alias | BaseRequestModel; validation handler; bulk schema; date error registry | API-08, VAL-18/23, BULK-10 |

No case assumes that comments describing “atomic”, “zero-blackout”, or future outbox workers are implemented guarantees. If a consistency probe fails, preserve evidence and report it; this checklist authorizes no production repair or source change.

## Existing test evidence and coverage boundary

The reviewed API integration tests for ingestion/mutations override use cases with `AsyncMock`, so their successful HTTP assertions do not establish real PostgreSQL/Qdrant consistency. Mock-server tests validate doubles. Repository/unit tests cover narrower seams. `tests/e2e` contains an initializer but no runnable endpoint E2E suite in this revision. Existing tests were inspected, not executed for this document.

Relevant existing files: [ingestion API tests](../../tests/integration/presentation/test_suggestion_ingestion_api.py), [mutation API tests](../../tests/integration/presentation/test_suggestion_mutation_api.py), [API infrastructure tests](../../tests/integration/presentation/test_api_infrastructure.py), [mutation unit tests](../../tests/unit/application/use_cases/test_suggestion_mutation_use_cases.py), [mock host tests](../../tests/unit/presentation/test_mock_server.py).

This checklist covers implemented non-analysis endpoint scenarios and material validation, dependency, compensation, retry, crash, and race boundaries discoverable in the reviewed source. It cannot guarantee every possible timing, payload, infrastructure failure, or future behavior. Repeat the review when routes, schemas, storage, or use cases change.

## Execution log

Copy one row per case **and per variant**, or link a separate run log. Store sanitized response bodies, SQL snapshots, paginated Qdrant snapshots, proxy scheduling evidence, and relevant logs. `Blocked` is not `Pass`.

| Case / variant | Commit / mode | Preconditions / IDs | Request ID | HTTP/code observed | SQL before/after | Qdrant before/after | Result | Evidence / defect / cleanup |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Example: ING-01 / Fixture A | 79cf610 / real | fresh run ID | UUID | Not run | Not run | Not run | Not run | |

- [ ] **DONE-01** Every required normal/negative case and every field/enum variant has a recorded outcome; fault/concurrency cases have actual schedules or an explicit blocker.
- [ ] **DONE-02** Every successful mutation satisfies both store oracles; sentinel/other parents remain unchanged.
- [ ] **DONE-03** Every failure's committed/compensated state is recorded; known gaps have defect references, not assumed recovery.
- [ ] **DONE-04** Remove disposable fixtures and leftover staging/deprecated/orphan points through the agreed test cleanup procedure, including soft-deleted rows that ordinary DELETE does not physically remove. Verify cleanup using the exact run IDs; preserve failure evidence first.
- [ ] **DONE-05** Restore faulted services/proxies, release test advisory locks, verify a fresh healthy mutation, and record remaining inconsistencies.
- [ ] **DONE-06** No suggestion analysis/generation scenario was executed as part of this checklist. Issue a pass statement only for the cases actually run; list blockers and failures separately.

## Source map

All references below refer to the reviewed commit, even if the files later change. Paths are relative to this checklist for repository browsing. Read code over stale scaffold descriptions or target-design comments.

- **S01:** [host/app factory](../../src/main.py) — route registration, metadata, liveness, CORS, docs/static, mock routing.
- **S02:** [master API router](../../src/presentation/routers/router.py) — prefix and shared authentication.
- **S03:** [suggestion router](../../src/presentation/routers/v1/suggestion.py) — lines 68-90 ingest; 92-155 PUT/PATCH; 158-185 DELETE; 187-265 bulk serialization.
- **S04:** [security](../../src/presentation/security.py) — API-key extraction, comparison, auth error header/pointer.
- **S05:** [exception handlers](../../src/presentation/exception_handlers.py) — registry, validation pointers/status, debug policy, unhandled exceptions.
- **S06:** [base requests](../../src/presentation/schemas/requests.py), [responses](../../src/presentation/schemas/responses.py) — aliases, extra fields, envelopes.
- **S07:** [ingest request](../../src/presentation/schemas/v1/ingest_suggestion_request.py), [PUT request](../../src/presentation/schemas/v1/update_suggestion_request.py), [PATCH request](../../src/presentation/schemas/v1/patch_suggestion_request.py), [bulk request](../../src/presentation/schemas/v1/bulk_delete_request.py), [validators](../../src/presentation/schemas/validators.py) — actual input contract.
- **S08:** [domain entities](../../src/domain/entities.py), [enums](../../src/domain/enums.py), [domain exceptions](../../src/domain/exceptions.py) — content/noise/date invariants and codes/titles/lifecycle states.
- **S09:** [ingestion use case](../../src/application/use_cases/ingest_suggestion_use_case.py) — duplicate gate, persistence order, synchronous compensation.
- **S10:** [update use case](../../src/application/use_cases/update_suggestion_use_case.py) — full/partial construction, staging, locks/version check, cutover retries.
- **S11:** [delete use case](../../src/application/use_cases/delete_suggestion_use_case.py) — idempotence, soft-delete, purge, compensation.
- **S12:** [bulk-delete use case](../../src/application/use_cases/bulk_delete_suggestions_use_case.py) — sequential isolation and error classification.
- **S13:** [SQL suggestion model](../../src/infrastructure/db/sql_models/suggestion_model.py), [SQL repository](../../src/infrastructure/db/repositories/sql/suggestion_repository.py), [unit of work](../../src/infrastructure/db/unit_of_work.py) — limits, upsert, flags/versions, transaction scope.
- **S14:** [Qdrant base repository](../../src/infrastructure/db/repositories/qdrant/base.py), [suggestion repository](../../src/infrastructure/db/repositories/qdrant/suggestion_repository.py), [payload schemas](../../src/infrastructure/db/repositories/qdrant/payload_schemas.py) — slices/retries, parent/ID cleanup, promotion, stored payload.
- **S15:** [suggestion normalizer](../../src/application/services/suggestion_normalizer.py), [Shekar normalizer](../../src/infrastructure/services/text_processing/shekar_text_normalizer.py), [field-aware chunker](../../src/infrastructure/services/chunkers/field_aware_suggestion_chunker.py) — normalized fields, Markdown preservation, thresholds/splitting.
- **S16:** [hybrid embedding](../../src/application/services/hybrid_embedding_service.py), [dense adapter](../../src/infrastructure/services/embeddings/openai_dense_embedder.py), [sparse adapter](../../src/infrastructure/services/embeddings/persian_bm25_embedder.py), [provider error base](../../src/infrastructure/services/base_openai_service.py) — vector association, empty sparse output, actual provider translation.
- **S17:** [container](../../src/containers.py), [settings](../../src/infrastructure/configs/settings.py), [lifespan](../../src/presentation/lifespan.py) — runtime alias, dependency wiring/resources, configured values.
- **S18:** [mock router](../../src/presentation/routers/v1/mock_admin.py), [mock host](../../src/presentation/mock_server.py), [mock use cases](../../src/infrastructure/mocks/mock_use_cases.py), [mock store](../../src/infrastructure/mocks/in_memory_suggestion_store.py), [mock overrides](../../src/infrastructure/mocks/container_overrides.py) — separate doubles and reset lifecycle.
- Contracts reviewed for comparison: [naming/data exchange](../contracts/03_Naming_And_Data_Exchange.md), [JSON/API conventions](../contracts/04_JSON_API_Conventions.md), [internal error codes](../contracts/05_Internal_Error_Codes.md), [authentication](../contracts/06_Authentication_And_Caller_Identity.md).

[S01]: ../../src/main.py
[S02]: ../../src/presentation/routers/router.py
[S03]: ../../src/presentation/routers/v1/suggestion.py
[S04]: ../../src/presentation/security.py
[S05]: ../../src/presentation/exception_handlers.py
[S06]: ../../src/presentation/schemas/requests.py
[S07]: ../../src/presentation/schemas/v1/ingest_suggestion_request.py
[S08]: ../../src/domain/entities.py
[S09]: ../../src/application/use_cases/ingest_suggestion_use_case.py
[S10]: ../../src/application/use_cases/update_suggestion_use_case.py
[S11]: ../../src/application/use_cases/delete_suggestion_use_case.py
[S12]: ../../src/application/use_cases/bulk_delete_suggestions_use_case.py
[S13]: ../../src/infrastructure/db/repositories/sql/suggestion_repository.py
[S14]: ../../src/infrastructure/db/repositories/qdrant/base.py
[S15]: ../../src/infrastructure/services/chunkers/field_aware_suggestion_chunker.py
[S16]: ../../src/application/services/hybrid_embedding_service.py
[S17]: ../../src/containers.py
[S18]: ../../src/infrastructure/mocks/mock_use_cases.py
