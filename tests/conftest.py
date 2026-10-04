"""Select test-only store settings before importing any application module."""

from pathlib import Path

import pytest

from tests.database_safety import TestDatabaseSafetyError, bootstrap_test_environment

try:
    TEST_DATABASES = bootstrap_test_environment(Path(__file__).resolve().parents[1])
except TestDatabaseSafetyError as exc:
    raise pytest.UsageError(str(exc)) from None

# Fixture registration must happen after the environment boundary above.
pytest_plugins = ["tests.database_fixtures"]


def pytest_addoption(parser):
    parser.addoption(
        "--run-db-tests",
        action="store_true",
        default=False,
        help="Run real database tests against marked, dedicated test services",
    )


def pytest_configure(config):
    workers = config.getoption("numprocesses", default=None)
    if config.getoption("run_db_tests") and workers not in (None, 0, "0"):
        raise pytest.UsageError(
            "Run database tests serially; the local test stack is shared by this suite"
        )


def pytest_collection_modifyitems(config, items):
    for item in items:
        # These existing SQL tests lived in tests/unit but exercise real storage.
        if "session_factory" in item.fixturenames:
            item.add_marker(pytest.mark.db)
        if item.get_closest_marker("db") and not config.getoption("run_db_tests"):
            item.add_marker(
                pytest.mark.skip(reason="Real database tests require --run-db-tests")
            )


@pytest.fixture(scope="session")
def test_database_config():
    return TEST_DATABASES
