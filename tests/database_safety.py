"""Fail-closed configuration and identity checks for dedicated local test stores.

This module imports no application settings. Bootstrap must run before their
eager singletons are imported, including during pytest collection.
"""

from __future__ import annotations

import ipaddress
import os
import sys
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import dotenv_values

GUARD_COLLECTION = "test_environment_guard"
GUARD_POINT_ID = "00000000-0000-0000-0000-000000000001"


class TestDatabaseSafetyError(RuntimeError):
    """A safe error that never includes connection credentials."""

    __test__ = False


def _loopback(host: str) -> bool:
    if not isinstance(host, str):
        return False
    if host.lower().rstrip(".") == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class DatabaseTestConfig:
    pg_host: str
    pg_port: int
    pg_database: str
    pg_username: str
    pg_password: str = field(repr=False)
    pg_admin_password: str = field(repr=False)
    q_host: str
    q_port: int
    q_grpc_port: int
    q_api_key: str = field(repr=False)
    environment_id: str

    @property
    def postgres_url(self) -> str:
        host = f"[{self.pg_host}]" if ":" in self.pg_host else self.pg_host
        return f"postgresql+asyncpg://{quote_plus(self.pg_username)}:{quote_plus(self.pg_password)}@{host}:{self.pg_port}/{self.pg_database}"

    @property
    def qdrant_url(self) -> str:
        host = f"[{self.q_host}]" if ":" in self.q_host else self.q_host
        return f"http://{host}:{self.q_port}"

    def compose_environment(self) -> dict[str, str]:
        return {
            "TEST_POSTGRES_SERVER": self.pg_host,
            "TEST_POSTGRES_PORT": str(self.pg_port),
            "TEST_POSTGRES_DB": self.pg_database,
            "TEST_POSTGRES_USERNAME": self.pg_username,
            "TEST_POSTGRES_PASSWORD": self.pg_password,
            "TEST_POSTGRES_ADMIN_PASSWORD": self.pg_admin_password,
            "TEST_QDRANT_HOST": self.q_host,
            "TEST_QDRANT_PORT": str(self.q_port),
            "TEST_QDRANT_GRPC_PORT": str(self.q_grpc_port),
            "TEST_QDRANT_API_KEY": self.q_api_key,
            "TEST_ENVIRONMENT_ID": self.environment_id,
        }

    def application_environment(self) -> dict[str, str]:
        return {
            "POSTGRES_SERVER": self.pg_host,
            "POSTGRES_HOST": self.pg_host,
            "POSTGRES_PORT": str(self.pg_port),
            "POSTGRES_DB": self.pg_database,
            "POSTGRES_USERNAME": self.pg_username,
            "POSTGRES_PASSWORD": self.pg_password,
            "POSTGRES_STORAGE_PATH": "./data/test/postgres_storage",
            "QDRANT_HOST": self.q_host,
            "QDRANT_PORT": str(self.q_port),
            "QDRANT_GRPC_PORT": str(self.q_grpc_port),
            "QDRANT_API_KEY": self.q_api_key,
            "QDRANT_PREFER_GRPC": "false",
            "QDRANT_HTTPS": "false",
            "QDRANT_STORAGE_PATH": "./data/test/qdrant_storage",
            "QDRANT_SUGGESTION_COLLECTION": "test_tavanir_suggestion_v1",
            "QDRANT_SUGGESTION_ALIAS": "test_tavanir_suggestion_active",
            "QDRANT_REGULATORY_COLLECTION": "test_tavanir_regulatory_knowledge_v1",
            "ENVIRONMENT": "test",
        }


def assert_safe_config(
    config: DatabaseTestConfig, development: Mapping | None = None
) -> None:
    if not _loopback(config.pg_host) or not _loopback(config.q_host):
        raise TestDatabaseSafetyError(
            "Test databases must use dedicated loopback services"
        )
    if config.pg_database != "tavanir_test_db" or config.pg_username != "tavanir_test":
        raise TestDatabaseSafetyError(
            "Test database and restricted login names do not match the test stack"
        )
    for value in (
        config.pg_password,
        config.pg_admin_password,
        config.q_api_key,
        config.environment_id,
    ):
        if not isinstance(value, str) or not value.strip():
            raise TestDatabaseSafetyError(
                "Dedicated test credentials and environment marker are required"
            )
    ports = (config.pg_port, config.q_port, config.q_grpc_port)
    if (
        any(type(value) is not int or not 1 <= value <= 65535 for value in ports)
        or len(set(ports)) != 3
    ):
        raise TestDatabaseSafetyError("Test service ports must be valid and distinct")
    blocked = {7432, 7333, 7334}
    development = development or {}
    for key in ("POSTGRES_PORT", "QDRANT_PORT", "QDRANT_GRPC_PORT"):
        if development.get(key):
            try:
                blocked.add(int(development[key]))
            except (ValueError, TypeError):
                raise TestDatabaseSafetyError(
                    "Development endpoint configuration is invalid"
                ) from None
    if any(value in blocked for value in ports):
        raise TestDatabaseSafetyError(
            "Tests cannot reuse development database service ports"
        )
    for test_secret, key in (
        (config.pg_password, "POSTGRES_PASSWORD"),
        (config.pg_admin_password, "POSTGRES_PASSWORD"),
        (config.q_api_key, "QDRANT_API_KEY"),
    ):
        if development.get(key) and test_secret == development[key]:
            raise TestDatabaseSafetyError(
                "Test credentials must differ from development credentials"
            )


def load_test_config(
    repo_root: Path, environ: Mapping | None = None
) -> DatabaseTestConfig:
    environment = os.environ if environ is None else environ
    path = repo_root / ".env.test"
    if not path.is_file():
        path = repo_root / ".env.test.example"
    if not path.is_file():
        raise TestDatabaseSafetyError(
            "Dedicated .env.test or .env.test.example is required"
        )
    values = {
        **dotenv_values(path),
        **{key: value for key, value in environment.items() if key.startswith("TEST_")},
    }

    def required(key):
        value = values.get(key)
        if not isinstance(value, str) or not value.strip():
            raise TestDatabaseSafetyError(
                f"Dedicated test configuration requires {key}"
            )
        return value

    def number(key):
        try:
            return int(required(key))
        except ValueError:
            raise TestDatabaseSafetyError(
                f"Dedicated test configuration requires a valid {key}"
            ) from None

    config = DatabaseTestConfig(
        pg_host=required(
            "TEST_POSTGRES_SERVER"
            if values.get("TEST_POSTGRES_SERVER")
            else "TEST_POSTGRES_HOST"
        ),
        pg_port=number("TEST_POSTGRES_PORT"),
        pg_database=required("TEST_POSTGRES_DB"),
        pg_username=required("TEST_POSTGRES_USERNAME"),
        pg_password=required("TEST_POSTGRES_PASSWORD"),
        pg_admin_password=required("TEST_POSTGRES_ADMIN_PASSWORD"),
        q_host=required("TEST_QDRANT_HOST"),
        q_port=number("TEST_QDRANT_PORT"),
        q_grpc_port=number("TEST_QDRANT_GRPC_PORT"),
        q_api_key=required("TEST_QDRANT_API_KEY"),
        environment_id=required("TEST_ENVIRONMENT_ID"),
    )
    assert_safe_config(config, dotenv_values(repo_root / ".env"))
    # Also protect development settings exported by the invoking shell. They are
    # never used as test configuration, and a stale export fails closed.
    own_exports = environment.get("TAVANIR_TEST_DATABASES_BOOTSTRAPPED") == "1" and all(
        environment.get(key) == value
        for key, value in config.application_environment().items()
    )
    if not own_exports:
        assert_safe_config(config, environment)
    return config


def assert_application_settings(settings, config: DatabaseTestConfig) -> None:
    expected = config.application_environment()
    for obj, keys in (
        (
            settings.db_settings,
            (
                "POSTGRES_SERVER",
                "POSTGRES_PORT",
                "POSTGRES_DB",
                "POSTGRES_USERNAME",
                "POSTGRES_PASSWORD",
            ),
        ),
        (
            settings.qdrant_settings,
            (
                "QDRANT_HOST",
                "QDRANT_PORT",
                "QDRANT_GRPC_PORT",
                "QDRANT_API_KEY",
                "QDRANT_SUGGESTION_COLLECTION",
                "QDRANT_SUGGESTION_ALIAS",
                "QDRANT_REGULATORY_COLLECTION",
                "QDRANT_PREFER_GRPC",
                "QDRANT_HTTPS",
            ),
        ),
    ):
        for key in keys:
            actual = getattr(obj, key, None)
            target = expected[key]
            if isinstance(actual, bool):
                actual = str(actual).lower()
            if str(actual) != target:
                raise TestDatabaseSafetyError(
                    "Application database settings were loaded before test isolation or changed afterwards"
                )


def bootstrap_test_environment(
    repo_root: Path, environ: MutableMapping | None = None
) -> DatabaseTestConfig:
    environment = os.environ if environ is None else environ
    config = load_test_config(repo_root, environment)
    loaded = sys.modules.get("src.infrastructure.configs.settings")
    if loaded is not None:
        assert_application_settings(loaded, config)
    environment.update(config.application_environment())
    environment["TAVANIR_TEST_DATABASES_BOOTSTRAPPED"] = "1"
    return config


def assert_postgres_identity(identity: Mapping, config: DatabaseTestConfig) -> None:
    expected = {
        "current_database": config.pg_database,
        "current_user": config.pg_username,
        "environment": "test",
        "environment_id": config.environment_id,
    }
    if any(identity.get(key) != value for key, value in expected.items()) or any(
        identity.get(key) is not False
        for key in ("is_superuser", "is_createdb", "is_createrole")
    ):
        raise TestDatabaseSafetyError(
            "Connected Postgres is not the marked test database with the restricted test role"
        )


def assert_qdrant_identity(identity: Mapping, config: DatabaseTestConfig) -> None:
    if (
        identity.get("environment") != "test"
        or identity.get("environment_id") != config.environment_id
    ):
        raise TestDatabaseSafetyError("Connected Qdrant is not the marked test service")


async def verify_postgres_connection(connection, config: DatabaseTestConfig) -> None:
    from sqlalchemy import text

    try:
        identity = dict(
            (
                await connection.execute(
                    text("""
            SELECT current_database() AS current_database, current_user AS current_user,
                   rolsuper AS is_superuser, rolcreatedb AS is_createdb, rolcreaterole AS is_createrole
            FROM pg_roles WHERE rolname = current_user
        """)
                )
            )
            .mappings()
            .one()
        )
        markers = (
            (
                await connection.execute(
                    text(
                        "SELECT environment, environment_id FROM public.test_environment_guard"
                    )
                )
            )
            .mappings()
            .all()
        )
        if len(markers) != 1:
            raise TestDatabaseSafetyError(
                "Postgres test environment marker is missing or ambiguous"
            )
        identity.update(dict(markers[0]))
        assert_postgres_identity(identity, config)
    except TestDatabaseSafetyError:
        raise
    except Exception:
        raise TestDatabaseSafetyError(
            "Cannot verify test Postgres; run python -m scripts.test_databases up"
        ) from None


async def verify_qdrant_client(client, config: DatabaseTestConfig) -> None:
    try:
        points = await client.retrieve(
            GUARD_COLLECTION,
            ids=[GUARD_POINT_ID],
            with_payload=True,
            with_vectors=False,
        )
        if len(points) != 1:
            raise TestDatabaseSafetyError("Qdrant test environment marker is missing")
        assert_qdrant_identity(points[0].payload or {}, config)
    except TestDatabaseSafetyError:
        raise
    except Exception:
        raise TestDatabaseSafetyError(
            "Cannot verify test Qdrant; run python -m scripts.test_databases up"
        ) from None
