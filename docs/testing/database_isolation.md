# Development and test database isolation

Development continues to use the root `.env` and `docker-compose.yaml`. Tests use
dedicated configuration and a separate `tavanir-tests` Compose project.

| Resource | Development | Tests |
| --- | --- | --- |
| Postgres port | 7432 by default | 7442 by default |
| Postgres database | `tavanir_db` | `tavanir_test_db` |
| Postgres application login | Development configuration | Restricted `tavanir_test` role |
| Qdrant HTTP / gRPC | 7333 / 7334 by default | 7343 / 7344 by default |
| Suggestion collection | `tavanir_suggestion_v1` | `test_tavanir_suggestion_v1` |
| Suggestion alias | `tavanir_suggestion_active` | `test_tavanir_suggestion_active` |
| Regulatory collection | `tavanir_regulatory_knowledge_v1` | `test_tavanir_regulatory_knowledge_v1` |
| Storage | Existing development bind mounts | Separate labeled Docker named volumes |
| Network | Existing development network | Separate test project network |

The test containers bind to `127.0.0.1`. Their credentials differ from development.
The helper validates configured development ports as well as the default ports;
changing a development port does not make it a permitted test target.

## Start and verify the test services

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m scripts.test_databases up
.\.venv\Scripts\python.exe -m scripts.test_databases check
```

On first use, `up` creates an ignored `.env.test` from `.env.test.example` with
generated test credentials and an environment identifier. It starts only the two
test database containers using cached images, verifies Docker ownership and the
Postgres identity, applies the real migrations to the test database, and provisions
the test Qdrant collections and alias. It does not start embedding or generation
services. Keep `.env.test` local; do not commit it.

Postgres uses `test_admin` only during container initialization. Tests connect as
`tavanir_test`, which cannot create databases or roles and is not a superuser. An
administrator-owned marker table identifies the test instance; the test role can
read the marker but cannot change it. Qdrant has a matching test-instance marker.

If ports need changing, use the `TEST_*` values in `.env.test`. Never put development
credentials or development service ports there. An incomplete `.env.test` fails
validation rather than falling back to development settings. Changing credentials
or the environment identifier on an existing test volume requires an explicit
test-volume reset because initialization runs only when that volume is new.

## Run tests

Ordinary unit tests do not require database services:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit -q
```

Real database tests are marked `db` and skipped unless explicitly enabled:

```powershell
.\.venv\Scripts\python.exe -m pytest --run-db-tests -m db -q
```

The existing SQL repository tests remain in `tests/unit` for compatibility, but
their use of the guarded `session_factory` marks them as real database tests.
Their pure mapper tests still run without the database flag.

Run database tests serially. Combining `--run-db-tests` with xdist workers is
rejected because this local stack shares Qdrant collections and test identifiers.
Parallel database testing needs separately provisioned stores per worker.

`tests/conftest.py` selects all database connection settings **before** application
settings or test modules are imported. Only `TEST_*` overrides select test targets;
normal development variables cannot redirect them. Already-imported development
settings cause an immediate error. Live fixtures recheck application settings and
the connected server's marker before performing schema work or database tests.

New SQL tests should use `session_factory` and `clean_db_session` from the shared
test fixtures. Repository commits release a savepoint inside an outer transaction.
The fixture rolls back that outer transaction on both success and failure and
disposes its engine. Cleanup no longer uses table-wide `DELETE` statements.
Unrelated existing rows remain intact. Tests that intentionally need independent
committed connections must use guarded test configuration and remove only their
own exact identifiers, as demonstrated in `test_database_isolation.py`.

New Qdrant integration tests should use the `db` marker and the
`qdrant_test_database` fixture, then clean up only their own points in the test
collections. New process-based test runners must apply the shared test environment
before importing application code; do not launch them with development settings.
Do not run bare Alembic commands to prepare tests; use the guarded `up` helper.

## Stop or reset

```powershell
# Stop test containers; retain their named volumes for later use.
.\.venv\Scripts\python.exe -m scripts.test_databases down

# Delete the verified test containers and test volumes, including test data.
.\.venv\Scripts\python.exe -m scripts.test_databases down --volumes
```

The helper fixes the project name and checks container, volume, and network labels,
mounted storage, and running service port bindings. It refuses unexpected resources.
Neither command selects the development project or its storage.

## Verification of this change

The focused configuration, repository, rollback, role-permission, and Qdrant suites
passed: **94 tests**. The live rollback tests verify that explicit commits disappear
after fixture teardown, including a simulated failed test, while a separately
committed sentinel remains unchanged. The marker-permission test verifies that the
restricted Postgres role cannot rewrite the environment marker.

Without the opt-in flag, the same focused selection passed **66 tests** and
skipped all **28 database tests**. Collection with `--run-db-tests -m db` selects
all 28, including the SQL repository tests in `tests/unit`.

A neighboring historical-ingestion settings suite has an unrelated existing
failure: the checked-out `scripts/docker_entrypoint.sh` contains CRLF line endings.
That production script was not changed. The new test initialization script has
LF endings enforced by `.gitattributes`.

The installed Qdrant client 1.19.0 warns about the existing server 1.17.1 version
difference. All focused database operations passed; this change does not upgrade
either dependency. Local HTTP API-key transport also emits the client's expected
insecure-connection warning; the test services are bound to loopback.
