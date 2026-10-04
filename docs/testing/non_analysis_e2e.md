# Non-analysis HTTP E2E suite

The suite runs the actual application in an owned Uvicorn process with one worker,
reload disabled, normal lifespan, and normal dependency injection. Requests cross
TCP. Production source is unchanged. Analysis and generation requests are rejected
by the harness, including encoded path variants.

The input specification is `docs/planning/non_analysis_api_e2e_test_checklist.md`
(210 stable cases). `tests/e2e/non_analysis/manifest.py` expands executable scenario
descriptors into traceable variants and pytest node IDs. Preparation and completion
items are recorded as run gates. Reports distinguish implementation completeness,
execution completeness, and product readiness. Known consistency failures are
ordinary failed tests; reproducing a defect does not turn it into a pass.

## Isolation and data

The default uses the existing dedicated test stack described in
[database_isolation.md](database_isolation.md). It verifies both Docker ownership
and server-side environment markers before writes and cleanup. The test login must
be restricted, and development endpoints and credentials are rejected. The root
`.env` is never edited; allowlisted embedding settings are inherited, while test
database and isolated API settings are supplied before subprocess imports.

`infrastructure: "disposable"` selects a unique Compose project with dynamically
allocated loopback ports, generated credentials, labeled named volumes, PostgreSQL
16, and Qdrant 1.17.1. Only the test initialization script is mounted, read-only.
Real migrations and destination collections/indexes/aliases are provisioned.
The default preserves the already-populated test stack requested for this task.

The existing seeder truncates the test data tables. Automatic seeding therefore
requires **all three destinations to be empty**: SQL suggestions, suggestion
vectors, and regulatory vectors. Populated test data is retained as immutable
sentinel/background data. Offline seed vectors are labeled separately; normal
HTTP ingestion and updates always call the configured real embedding provider.

The read-only export qualifies available test records, balances statuses, and
prioritizes commentary, context, dates, Unicode and chunk-count diversity with
stable ID-hash ties. It records exclusions, unavailable categories and any
shortage from the requested 100. It captures exact SQL rows, timestamps, point IDs,
payloads and dense/sparse vectors before/after export. Both raw captures verify the
alias targets the expected collection; the export records the configured alias name.
Drift fails capture. Synthetic
mutation fixtures have exact registered IDs; a boundary ID can be claimed only
after raw SQL and vector readers prove it absent. Existing background IDs cannot
be claimed or mutated.

## Commands

Run from the repository root using the project Python:

```powershell
.\.venv\Scripts\python.exe -m tests.e2e.non_analysis.runner export-seed --config <private-config.json>
.\.venv\Scripts\python.exe -m tests.e2e.non_analysis.runner run --config <private-config.json> --profile full --seed 42 --resilience-repeats 10
.\.venv\Scripts\python.exe -m tests.e2e.non_analysis.runner cleanup --config <private-config.json> --run-id <run-id>
```

Configuration is optional for the existing test stack. A minimal private file is:

```json
{
  "infrastructure": "existing",
  "api_key": {"env": "E2E_TEST_API_KEY"},
  "embedding": {
    "TEI_API_KEY": {"env": "E2E_TEST_TEI_API_KEY"}
  },
  "startup_timeout": 90,
  "request_timeout": 45
}
```

Use environment references for secrets. Generated subprocess configuration stores
references, not secret values. HTTP headers, response evidence, application logs,
and exception reports redact configured secrets. Never commit private configuration
or exports. Reports reside under ignored `tests/e2e/reports/<run-id>`.

Profiles are `smoke`, `core`, `resilience`, `mock`, and `full`. Full execution runs
smoke/core, the configured resilience attempts with distinct fixture IDs/seeds,
separate mock checks, and a second smoke/core pass on a freshly provisioned
disposable stack. `--resilience-repeats` accepts 1–100 and defaults to ten; full
execution completeness requires at least ten and every configured attempt.
Run IDs must be fresh; the run command rejects a nonempty artifact directory before
writing run artifacts so an earlier failed attempt cannot be overwritten. Assertion
failures remain in the aggregate report even if a later attempt passes. Pytest exits
2–5 or unverified cleanup stop later phases; failed post-case snapshot/sentinel
verification or fixture cleanup stops the pytest session. Setup-only errors remain
unexecuted coverage. Parallel
pytest workers are rejected; deliberate concurrency is
scheduled inside a case.

Ordinary discovery skips live scenarios and does not start services. Offline
harness controls can run independently:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/e2e/non_analysis/test_harness_controls.py tests/e2e/non_analysis/test_fault_controls.py tests/e2e/non_analysis/test_manifest_controls.py tests/e2e/non_analysis/test_scenario_controls.py tests/e2e/non_analysis/test_sample_controls.py -q --strict-markers
```

## Evidence and fault schedules

Raw SQL readers bypass production repositories. Qdrant REST readers explicitly
request payloads and vectors and follow every pagination offset, across all
active/staging/deprecated states. Normal successful mutations verify versions,
deletion flags, metadata, complete chunk sets, vector shape/finite values, previous
point removal, and unchanged sentinels. Golden text expectations do not call the
production normalizer or chunker.

Dependency preflight records installed package versions, runtime settings, the
requirements-file hash, configured embedding provider/model, destination dimension,
and local tokenizer readiness. The provider probe checks response count and
dimension; these checks do not verify a provider weight revision.

The instrumented profile initializes the normal composition root and wraps
injected collaborators with required delegates. It records precise phases,
request IDs, point IDs, attempts, real application outcomes, and acknowledged
barriers. It does not replace entire use cases. The external proxy can reject
before forwarding, hold an acknowledged barrier, forward and lose the response,
or serve controlled malformed provider responses. Raw verification bypasses it.
Shared embedding services are never stopped.
Changed Qdrant endpoints require a live run-owned proxy proof; configured
development ports are rejected. Proxy ownership is checked again at host start.

Crash scenarios terminate only the owned application process, inspect both stores,
restart it, and record recovery gaps. A restart does not prove repair. Advisory-lock
tests hold a separate guarded SQL transaction. Barrier deadlines and missed fault
matches fail the harness scenario instead of silently passing.

Mock checks use the actual mock HTTP host. A test-only read-only observer writes
in-memory state after requests for metadata behaviors that have no public GET
endpoint. Those results cannot establish real database correctness.

## Cleanup and verdict

Before mutation, the harness atomically journals every exact fixture ID. It records
failure state before cleanup, stops or settles owned requests, removes every
lifecycle state's vector points, physically deletes the registered SQL rows, and
verifies unchanged background/sentinel rows and both vector collections. Ordinary
API DELETE is insufficient cleanup. Disposable resources are removed only after
run labels, identities, storage mounts, and loopback bindings are verified.
The runner journals the pytest launcher and its native process identities before
releasing the test process. Interrupted cleanup settles that process tree, then
verifies each persisted application PID, native creation identity, exact command,
and owned descendants. Only those processes may be terminated. Missing or
uncertain process evidence refuses database cleanup and preserves infrastructure.
Migration, seeder and tokenizer preparation commands use the same ownership
procedure and retain exact module arguments or a verified bootstrap hash. Their
processes must be settled before a disposable stack can be removed.

Artifacts include JUnit XML, sanitized HTTP/application/fault logs, SQL/vector
snapshots, exact cleanup journals, `manifest.json`, `results.json`, `coverage.csv`,
and `report.md`. Readiness requires no material failed consistency probe. Reported
unimplemented or unexecuted variants make completeness false; skipped/blocked
variants never count as passes.
The 18 preparation/completion items have separate evidence and outcomes. An
approved fault/mock variant catalog prevents removal of a variant from hiding
behind another variant of the same checklist case. Source and per-phase harness
fingerprints record provenance; a changed production fingerprint or differing
phase harness fingerprints prevent a readiness pass. CLI
documentation checks cover HTML, schema and assets. Browser rendering must be
recorded separately when it is verified.
