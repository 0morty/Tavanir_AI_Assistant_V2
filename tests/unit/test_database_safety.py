"""Pure regression tests for the test database boundary; no services are used."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from tests.database_safety import (
    DatabaseTestConfig,
    TestDatabaseSafetyError,
    assert_postgres_identity,
    assert_safe_config,
    load_test_config,
)


@pytest.fixture
def safe_config() -> DatabaseTestConfig:
    return DatabaseTestConfig(
        pg_host="127.0.0.1",
        pg_port=17432,
        pg_database="tavanir_test_db",
        pg_username="tavanir_test",
        pg_password="unit-only-role-secret",
        pg_admin_password="unit-only-admin-secret",
        q_host="127.0.0.1",
        q_port=17333,
        q_grpc_port=17334,
        q_api_key="unit-only-vector-secret",
        environment_id="tavanir-test-unit",
    )


def test_dedicated_loopback_configuration_is_accepted(safe_config):
    assert_safe_config(safe_config)


def test_validated_configuration_cannot_be_mutated_after_guarding(safe_config):
    assert_safe_config(safe_config)
    with pytest.raises(FrozenInstanceError):
        safe_config.pg_port = 7432


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pg_host", "10.20.30.40"),
        ("pg_host", "database.example.invalid"),
        ("q_host", "10.20.30.40"),
        ("q_host", "qdrant.example.invalid"),
        ("pg_database", "tavanir_db"),
        ("pg_database", "postgres"),
        ("pg_username", "postgres"),
        ("pg_username", "tavanir_user"),
        ("pg_password", ""),
        ("pg_admin_password", ""),
        ("q_api_key", ""),
        ("environment_id", ""),
        ("pg_port", 7432),
        ("q_port", 7333),
        ("q_grpc_port", 7334),
        ("pg_port", 0),
        ("q_port", 65536),
        ("q_grpc_port", -1),
    ],
)
def test_unsafe_configuration_fails_closed(safe_config, field, value):
    with pytest.raises(TestDatabaseSafetyError):
        assert_safe_config(replace(safe_config, **{field: value}))


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("pg_port", "q_port"),
        ("pg_port", "q_grpc_port"),
        ("q_port", "q_grpc_port"),
    ],
)
def test_test_services_cannot_share_a_host_port(safe_config, first, second):
    with pytest.raises(TestDatabaseSafetyError):
        assert_safe_config(
            replace(safe_config, **{second: getattr(safe_config, first)})
        )


@pytest.mark.parametrize(
    "development",
    [
        {"POSTGRES_SERVER": "localhost", "POSTGRES_PORT": "17432"},
        {"POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "17432"},
        {"QDRANT_HOST": "localhost", "QDRANT_PORT": "17333"},
        {"QDRANT_HOST": "127.0.0.1", "QDRANT_GRPC_PORT": "17334"},
    ],
)
def test_test_named_database_does_not_allow_development_endpoint_reuse(
    safe_config, development
):
    with pytest.raises(TestDatabaseSafetyError):
        assert_safe_config(safe_config, development=development)


def test_non_overlapping_development_configuration_is_allowed(safe_config):
    assert_safe_config(
        safe_config,
        development={
            "POSTGRES_SERVER": "127.0.0.1",
            "POSTGRES_PORT": "7432",
            "QDRANT_HOST": "127.0.0.1",
            "QDRANT_PORT": "7333",
            "QDRANT_GRPC_PORT": "7334",
        },
    )


def _identity(config: DatabaseTestConfig) -> dict:
    return {
        "current_database": config.pg_database,
        "current_user": config.pg_username,
        "is_superuser": False,
        "is_createdb": False,
        "is_createrole": False,
        "environment": "test",
        "environment_id": config.environment_id,
    }


def test_marked_test_database_and_restricted_role_are_accepted(safe_config):
    assert_postgres_identity(_identity(safe_config), safe_config)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("current_database", "tavanir_db"),
        ("current_database", "another_test_db"),
        ("current_user", "postgres"),
        ("current_user", "another_test_user"),
        ("is_superuser", True),
        ("is_createdb", True),
        ("is_createrole", True),
        ("environment", "development"),
        ("environment", ""),
        ("environment_id", "another-test-instance"),
        ("environment_id", ""),
    ],
)
def test_actual_database_identity_must_match_every_safety_condition(
    safe_config, field, value
):
    identity = _identity(safe_config)
    identity[field] = value
    with pytest.raises(TestDatabaseSafetyError):
        assert_postgres_identity(identity, safe_config)


@pytest.mark.parametrize(
    "field",
    [
        "current_database",
        "current_user",
        "is_superuser",
        "is_createdb",
        "is_createrole",
        "environment",
        "environment_id",
    ],
)
def test_missing_database_identity_fields_fail_closed(safe_config, field):
    identity = _identity(safe_config)
    del identity[field]
    with pytest.raises(TestDatabaseSafetyError):
        assert_postgres_identity(identity, safe_config)


@pytest.mark.parametrize("value", [None, "false", "0", 0])
def test_privilege_flags_must_be_real_false_booleans(safe_config, value):
    identity = _identity(safe_config)
    identity["is_superuser"] = value
    with pytest.raises(TestDatabaseSafetyError):
        assert_postgres_identity(identity, safe_config)


def test_config_repr_and_safety_errors_do_not_expose_credentials(safe_config):
    secrets = [
        safe_config.pg_password,
        safe_config.pg_admin_password,
        safe_config.q_api_key,
    ]
    with pytest.raises(TestDatabaseSafetyError) as failure:
        assert_safe_config(replace(safe_config, pg_port=7432))
    rendered = repr(safe_config) + str(failure.value)
    assert all(secret not in rendered for secret in secrets)


def _write_test_config(path: Path, config: DatabaseTestConfig) -> None:
    path.write_text(
        "\n".join(
            [
                f"TEST_POSTGRES_SERVER={config.pg_host}",
                f"TEST_POSTGRES_PORT={config.pg_port}",
                f"TEST_POSTGRES_DB={config.pg_database}",
                f"TEST_POSTGRES_USERNAME={config.pg_username}",
                f"TEST_POSTGRES_PASSWORD={config.pg_password}",
                f"TEST_POSTGRES_ADMIN_PASSWORD={config.pg_admin_password}",
                f"TEST_QDRANT_HOST={config.q_host}",
                f"TEST_QDRANT_PORT={config.q_port}",
                f"TEST_QDRANT_GRPC_PORT={config.q_grpc_port}",
                f"TEST_QDRANT_API_KEY={config.q_api_key}",
                f"TEST_ENVIRONMENT_ID={config.environment_id}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_missing_dedicated_test_configuration_does_not_fall_back_to_development(
    tmp_path,
):
    (tmp_path / ".env").write_text(
        "POSTGRES_DB=tavanir_db\nPOSTGRES_PORT=7432\n", encoding="utf-8"
    )
    with pytest.raises(TestDatabaseSafetyError):
        load_test_config(tmp_path, environ={})


def test_loader_uses_dedicated_example_when_local_test_file_is_absent(
    tmp_path, safe_config
):
    _write_test_config(tmp_path / ".env.test.example", safe_config)
    assert load_test_config(tmp_path, environ={}) == safe_config


def test_test_host_alias_is_supported_when_server_key_is_absent(tmp_path, safe_config):
    path = tmp_path / ".env.test.example"
    _write_test_config(path, safe_config)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "TEST_POSTGRES_SERVER=", "TEST_POSTGRES_HOST="
        ),
        encoding="utf-8",
    )
    assert load_test_config(tmp_path, environ={}) == safe_config


def test_local_test_file_overrides_dedicated_example(tmp_path, safe_config):
    _write_test_config(tmp_path / ".env.test.example", safe_config)
    local = replace(safe_config, pg_password="different-unit-only-secret")
    _write_test_config(tmp_path / ".env.test", local)
    assert load_test_config(tmp_path, environ={}) == local


def test_raw_development_environment_cannot_override_test_configuration(
    tmp_path, safe_config
):
    _write_test_config(tmp_path / ".env.test.example", safe_config)
    loaded = load_test_config(
        tmp_path,
        environ={
            "POSTGRES_SERVER": "development-db.invalid",
            "POSTGRES_HOST": "development-alias.invalid",
            "POSTGRES_PORT": "7432",
            "POSTGRES_DB": "tavanir_db",
            "POSTGRES_USERNAME": "postgres",
            "POSTGRES_PASSWORD": "development-only-secret",
            "QDRANT_HOST": "development-vector.invalid",
            "QDRANT_PORT": "7333",
            "QDRANT_GRPC_PORT": "7334",
            "QDRANT_API_KEY": "development-vector-secret",
        },
    )
    assert loaded == safe_config
    environment = loaded.application_environment()
    assert environment["POSTGRES_SERVER"] == safe_config.pg_host
    assert environment["POSTGRES_PORT"] == str(safe_config.pg_port)
    assert environment["POSTGRES_DB"] == safe_config.pg_database
    assert environment["POSTGRES_USERNAME"] == safe_config.pg_username
    assert environment["QDRANT_HOST"] == safe_config.q_host
    assert environment["QDRANT_PORT"] == str(safe_config.q_port)
    assert environment["QDRANT_GRPC_PORT"] == str(safe_config.q_grpc_port)


def test_only_prefixed_test_environment_can_override_test_file(tmp_path, safe_config):
    _write_test_config(tmp_path / ".env.test.example", safe_config)
    loaded = load_test_config(tmp_path, environ={"TEST_POSTGRES_PORT": "18432"})
    assert loaded.pg_port == 18432
    assert loaded.pg_database == safe_config.pg_database


def test_exported_bootstrap_flag_cannot_hide_a_development_endpoint_collision(
    tmp_path, safe_config
):
    _write_test_config(tmp_path / ".env.test.example", safe_config)
    with pytest.raises(TestDatabaseSafetyError):
        load_test_config(
            tmp_path,
            environ={
                "TAVANIR_TEST_DATABASES_BOOTSTRAPPED": "1",
                "POSTGRES_SERVER": "127.0.0.1",
                "POSTGRES_PORT": str(safe_config.pg_port),
                "POSTGRES_DB": "tavanir_db",
                "POSTGRES_USERNAME": "postgres",
            },
        )


def test_incomplete_local_test_file_does_not_inherit_missing_fields_from_example(
    tmp_path, safe_config
):
    _write_test_config(tmp_path / ".env.test.example", safe_config)
    (tmp_path / ".env.test").write_text(
        "TEST_POSTGRES_DB=tavanir_test_db\n", encoding="utf-8"
    )
    with pytest.raises(TestDatabaseSafetyError):
        load_test_config(tmp_path, environ={})


def _run_fresh_bootstrap_process(tmp_path, safe_config, body):
    _write_test_config(tmp_path / ".env.test", safe_config)
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("TEST_", "POSTGRES_", "QDRANT_"))
        and key != "TAVANIR_TEST_DATABASES_BOOTSTRAPPED"
    }
    environment.update(
        POSTGRES_SERVER="127.0.0.1",
        POSTGRES_HOST="127.0.0.1",
        POSTGRES_PORT="7432",
        POSTGRES_DB="tavanir_db",
        POSTGRES_USERNAME="postgres",
        POSTGRES_PASSWORD="development-only-secret",
        QDRANT_HOST="127.0.0.1",
        QDRANT_PORT="7333",
        QDRANT_GRPC_PORT="7334",
        QDRANT_API_KEY="development-vector-secret",
    )
    script = (
        """
import socket
import sys
from pathlib import Path

def forbid_network(*args, **kwargs):
    raise AssertionError("Network use is forbidden in pure bootstrap regressions")

socket.socket.connect = forbid_network
socket.socket.connect_ex = forbid_network
from tests.database_safety import (
    TestDatabaseSafetyError, assert_application_settings, bootstrap_test_environment,
)
repo_root = Path(sys.argv[1])
"""
        + body
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def test_bootstrap_selects_test_stores_before_real_settings_import(
    tmp_path, safe_config
):
    output = _run_fresh_bootstrap_process(
        tmp_path,
        safe_config,
        """
config = bootstrap_test_environment(repo_root)
from src.infrastructure.configs import settings
assert_application_settings(settings, config)
assert settings.db_settings.POSTGRES_DB == "tavanir_test_db"
assert settings.db_settings.POSTGRES_USERNAME == "tavanir_test"
assert settings.db_settings.POSTGRES_PORT == 17432
assert settings.qdrant_settings.QDRANT_PORT == 17333
assert settings.qdrant_settings.QDRANT_SUGGESTION_COLLECTION.startswith("test_")
print("isolated")
""",
    )
    assert output == "isolated"


def test_bootstrap_rejects_development_settings_already_imported(tmp_path, safe_config):
    output = _run_fresh_bootstrap_process(
        tmp_path,
        safe_config,
        """
from src.infrastructure.configs import settings
assert settings.db_settings.POSTGRES_DB == "tavanir_db"
try:
    bootstrap_test_environment(repo_root)
except TestDatabaseSafetyError:
    print("blocked")
else:
    raise AssertionError("Already-loaded development settings were accepted")
""",
    )
    assert output == "blocked"


def test_repeated_bootstrap_accepts_its_own_injected_settings(tmp_path, safe_config):
    output = _run_fresh_bootstrap_process(
        tmp_path,
        safe_config,
        """
first = bootstrap_test_environment(repo_root)
from src.infrastructure.configs import settings
second = bootstrap_test_environment(repo_root)
assert first == second
assert_application_settings(settings, second)
print("idempotent")
""",
    )
    assert output == "idempotent"
