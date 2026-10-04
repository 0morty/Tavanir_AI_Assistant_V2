"""Private runner configuration; never import eager application settings here."""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values

from tests.database_safety import DatabaseTestConfig, assert_safe_config, load_test_config

ROOT = Path(__file__).resolve().parents[3]
EMBEDDING_KEYS = frozenset({
    "TEI_HOST", "TEI_PORT", "TEI_API_KEY", "VLLM_HOST", "VLLM_PORT", "VLLM_API_KEY",
    "EMBEDDING_PROVIDER", "EMBEDDING_MODEL", "EMBEDDING_DIMENSION", "EMBEDDING_BATCH_SIZE",
    "EMBEDDING_TIMEOUT", "EMBEDDING_QUERY_PREFIX", "EMBEDDING_DOCUMENT_PREFIX", "MAX_RETRIES",
    "TOKENIZER_MODEL", "LLM_PROVIDER", "LLM_MODEL", "LLM_TIMEOUT",
    "QDRANT_BATCH_SIZE", "QDRANT_BULK_UPSERT_BATCH_SIZE", "BM25_TOKEN_MAX_LENGTH",
})


def resolve_secret(value: object, environment: Mapping[str, str] | None = None) -> str:
    """Secret references are data, never Python or shell expressions."""
    if isinstance(value, dict) and set(value) == {"env"}:
        name = value["env"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError("Invalid secret environment reference")
        result = (os.environ if environment is None else environment).get(name)
        if not result:
            raise ValueError(f"Required secret environment reference is unset: {name}")
        return result
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    raise ValueError("Configuration values must be scalars or an env reference")


@dataclass(frozen=True)
class E2EConfig:
    database: DatabaseTestConfig
    repo_root: Path = ROOT
    run_id: str = field(default_factory=lambda: secrets.token_hex(8))
    artifacts_dir: Path | None = None
    api_key: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)
    api_header: str = "X-API-Key"
    dense_name: str = "dense"
    sparse_name: str = "sparse"
    dense_dimension: int = 768
    embedding_environment: dict[str, str] = field(default_factory=dict, repr=False)
    startup_timeout: float = 90.0
    request_timeout: float = 45.0
    shutdown_timeout: float = 15.0
    infrastructure: str = "existing"
    stack_run_id: str | None = None
    python_executable: str = sys.executable
    source: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        assert_safe_config(self.database, dotenv_values(self.repo_root / ".env"))
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}", self.run_id):
            raise ValueError("Run ID must contain at most 40 safe identifier characters")
        if self.infrastructure not in {"existing", "disposable"}:
            raise ValueError("Infrastructure must be existing or disposable")
        if self.infrastructure == "disposable" and self.stack_run_id is None:
            object.__setattr__(self, "stack_run_id", self.run_id)
        if self.stack_run_id is not None and not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}", self.stack_run_id):
            raise ValueError("Stack run ID must be a safe bounded identifier")
        if self.dense_dimension <= 0 or min(self.startup_timeout, self.request_timeout, self.shutdown_timeout) <= 0:
            raise ValueError("Dimensions and timeout budgets must be positive")
        if not self.api_key or not self.api_header:
            raise ValueError("An isolated API key and header are required")
        if set(self.embedding_environment) - EMBEDDING_KEYS:
            raise ValueError("Embedding environment contains unsupported settings")
        destination = self.artifacts_dir or self.repo_root / "tests/e2e/reports" / self.run_id
        object.__setattr__(self, "artifacts_dir", Path(destination).resolve())

    @classmethod
    def load(cls, path: str | Path | None = None, *, repo_root: Path = ROOT) -> E2EConfig:
        data = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
        unknown = set(data) - {"database", "run_id", "artifacts_dir", "api_key", "api_header", "dense_name", "sparse_name", "dense_dimension", "embedding", "startup_timeout", "request_timeout", "shutdown_timeout", "infrastructure", "stack_run_id", "python_executable", "source"}
        if unknown:
            raise ValueError("Unknown E2E configuration fields: " + ", ".join(sorted(unknown)))
        environment = dict(os.environ)
        for key, value in data.get("database", {}).items():
            if not key.startswith("TEST_"):
                raise ValueError("Database overrides require TEST_ names")
            environment[key] = resolve_secret(value)
        database = load_test_config(repo_root, environment)
        inherited = {key: str(value) for key, value in dotenv_values(repo_root / ".env").items() if key in EMBEDDING_KEYS and value}
        inherited.update({key: value for key, value in os.environ.items() if key in EMBEDDING_KEYS})
        inherited.update({key: resolve_secret(value) for key, value in data.get("embedding", {}).items()})
        options = {key: value for key, value in data.items() if key not in {"database", "embedding", "source"}}
        if "api_key" in options:
            options["api_key"] = resolve_secret(options["api_key"])
        if "artifacts_dir" in options:
            options["artifacts_dir"] = Path(options["artifacts_dir"])
        options.setdefault("dense_dimension", int(inherited.get("EMBEDDING_DIMENSION", "768")))
        return cls(database=database, repo_root=repo_root, embedding_environment=inherited, source=data.get("source", {}), **options)

    @property
    def collection(self) -> str:
        return self.database.application_environment()["QDRANT_SUGGESTION_COLLECTION"]

    @property
    def alias(self) -> str:
        return self.database.application_environment()["QDRANT_SUGGESTION_ALIAS"]

    @property
    def fixture_prefix(self) -> str:
        return f"e2e-{self.run_id}-"

    @property
    def max_chunk_chars(self) -> int:
        return 1500

    @property
    def qdrant_batch_size(self) -> int:
        return int(self.embedding_environment.get("QDRANT_BATCH_SIZE", "64"))

    @property
    def embedding_batch_size(self) -> int:
        return int(self.embedding_environment.get("EMBEDDING_BATCH_SIZE", "128"))

    @property
    def bm25_max_token_length(self) -> int:
        return int(self.embedding_environment.get("BM25_TOKEN_MAX_LENGTH", "40"))

    def application_environment(self) -> dict[str, str]:
        return {
            **self.database.application_environment(), **self.embedding_environment,
            "TAVANIR_TEST_DATABASES_BOOTSTRAPPED": "1", "API_KEY": self.api_key,
            "API_KEY_NAME": self.api_header, "IS_MOCK": "false", "ENVIRONMENT": "test",
            "QDRANT_DENSE_VECTOR_NAME": self.dense_name, "QDRANT_SPARSE_VECTOR_NAME": self.sparse_name,
            "EMBEDDING_DIMENSION": str(self.dense_dimension), "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false",
            "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1",
        }

    def secrets(self) -> tuple[str, ...]:
        values = [self.api_key, self.database.pg_password, self.database.pg_admin_password, self.database.q_api_key]
        values.extend(value for key, value in self.embedding_environment.items() if "KEY" in key)
        return tuple(value for value in values if value and value != "EMPTY")

    def redacted(self) -> dict:
        return {"run_id": self.run_id, "infrastructure": self.infrastructure, "stack_run_id": self.stack_run_id, "postgres_port": self.database.pg_port,
                "qdrant_port": self.database.q_port, "database": self.database.pg_database, "collection": self.collection,
                "environment_id": self.database.environment_id, "postgres_host": self.database.pg_host, "qdrant_host": self.database.q_host,
                "alias": self.alias, "dense_dimension": self.dense_dimension, "dense_name": self.dense_name,
                "sparse_name": self.sparse_name, "startup_timeout": self.startup_timeout,
                "request_timeout": self.request_timeout, "python_executable": self.python_executable}

    def with_database(self, database: DatabaseTestConfig) -> E2EConfig:
        return replace(self, database=database)
