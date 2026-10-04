"""Guarded existing test stack and optional run-owned disposable Compose stack."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import socket
import subprocess
from dataclasses import replace
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.database_safety import GUARD_COLLECTION, GUARD_POINT_ID, TestDatabaseSafetyError, assert_safe_config, verify_postgres_connection
from tests.e2e.non_analysis.config import E2EConfig
from tests.e2e.non_analysis.oracles import RawStoreOracle, digest


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def ownership_fingerprint(item: dict) -> str:
    """Docker may return mount records in map iteration order; compare their set."""
    mounts = sorted(item.get("Mounts", []), key=lambda mount: (mount.get("Destination", ""), mount.get("Type", ""), mount.get("Source", "")))
    return digest({"labels": item["Config"].get("Labels"), "environment": item["Config"].get("Env"), "mounts": mounts, "bindings": item["HostConfig"].get("PortBindings"), "networks": {key: value.get("NetworkID") for key, value in item["NetworkSettings"].get("Networks", {}).items()}})


def run_command(command: list[str], config: E2EConfig, *, timeout: float = 180, environment: dict | None = None):
    env = {**os.environ, **config.database.compose_environment(), **config.application_environment(), **(environment or {})}
    if command and os.path.normcase(command[0]) == os.path.normcase(config.python_executable):
        from .harness import run_owned_preparation
        arguments = command[1:]
        script_hash = hashlib.sha256(arguments[1].encode("utf-8")).hexdigest() if len(arguments) == 2 and arguments[0] == "-c" else None
        label = "migration" if arguments == ["-m", "alembic", "upgrade", "head"] else "seed"
        return run_owned_preparation(config, arguments, label=label, environment=env, timeout=timeout, expected_script_sha256=script_hash)
    result = subprocess.run(command, cwd=config.repo_root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        safe = (result.stderr or result.stdout)[-6000:]
        for secret in config.secrets():
            safe = safe.replace(secret, "[REDACTED]")
        raise TestDatabaseSafetyError(f"Test infrastructure command failed ({result.returncode}): {safe}")
    return result.stdout


class ManagedTestInfrastructure:
    def __init__(self, config: E2EConfig):
        self.config = config
        self.owner_run_id = config.stack_run_id or config.run_id
        self.project = "tavanir-tests" if config.infrastructure == "existing" else f"tavanir-e2e-{self.owner_run_id.lower()}"
        self.compose_path = config.artifacts_dir / "compose.json"
        self._created = False
        self._container_ids: set[str] | None = None
        self._existing_fingerprints: dict[str, str] | None = None

    def _inspect(self, command):
        return json.loads(run_command(command, self.config))

    def verify(self, *, require_running: bool = True, require_complete: bool = True):
        assert_safe_config(self.config.database)
        if self.config.infrastructure == "existing":
            if self._existing_fingerprints is None:
                from scripts.test_databases import verify_docker_ownership
                verify_docker_ownership({**os.environ, **self.config.database.compose_environment()}, require_running=require_running)
                listing = run_command(["docker", "ps", "-a", "--filter", "label=com.docker.compose.project=tavanir-tests", "--format", "{{.ID}}"], self.config)
                identifiers = listing.splitlines()
                if len(identifiers) != 2:
                    raise TestDatabaseSafetyError("The guarded test stack must own exactly two containers")
                details = self._inspect(["docker", "inspect", *identifiers])
            else:
                # Docker labels, mounts, environment and published bindings cannot be
                # changed in place. Freshly inspect immutable IDs before every write;
                # the initial full volume/network proof stays valid for these IDs.
                details = self._inspect(["docker", "inspect", *self._existing_fingerprints])
            current = {}
            for item in details:
                if require_running and item["State"].get("Running") is not True:
                    raise TestDatabaseSafetyError("A guarded test service is stopped")
                current[item["Id"]] = ownership_fingerprint(item)
            if self._existing_fingerprints is not None and self._existing_fingerprints != current:
                raise TestDatabaseSafetyError("Guarded test container identities or configuration changed")
            self._existing_fingerprints = current
            return
        listing = run_command(["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={self.project}", "--format", "{{.ID}}"], self.config)
        ids, services = set(), set()
        expected_ports = {"postgres": {"5432/tcp": self.config.database.pg_port}, "qdrant": {"6333/tcp": self.config.database.q_port, "6334/tcp": self.config.database.q_grpc_port}}
        for identifier in listing.splitlines():
            details = self._inspect(["docker", "inspect", identifier])[0]
            labels = details["Config"].get("Labels", {})
            service = labels.get("com.docker.compose.service")
            if labels.get("com.docker.compose.project") != self.project or labels.get("tavanir.environment") != "test" or labels.get("tavanir.e2e.run") != self.owner_run_id or service not in expected_ports:
                raise TestDatabaseSafetyError("Run-owned container labels are not verified")
            if require_running and not details["State"]["Running"]:
                raise TestDatabaseSafetyError("Run-owned database service is stopped")
            for inner, outer in expected_ports[service].items():
                bindings = details["NetworkSettings"].get("Ports", {}) if details["State"]["Running"] else details["HostConfig"].get("PortBindings", {})
                if bindings.get(inner) != [{"HostIp": "127.0.0.1", "HostPort": str(outer)}]:
                    raise TestDatabaseSafetyError("Run-owned service has unexpected port bindings")
            for mount in details.get("Mounts", []):
                if mount.get("Type") == "bind" and mount.get("RW"):
                    raise TestDatabaseSafetyError("Run-owned stack has a writable host bind mount")
                if mount.get("Type") == "volume":
                    volume = self._inspect(["docker", "volume", "inspect", mount["Name"]])[0]
                    own = volume.get("Labels") or {}
                    if own.get("com.docker.compose.project") != self.project or own.get("tavanir.e2e.run") != self.owner_run_id or own.get("tavanir.environment") != "test":
                        raise TestDatabaseSafetyError("Run-owned volume labels are not verified")
            ids.add(details["Id"])
            services.add(service)
        if require_complete and (services != {"postgres", "qdrant"} or len(ids) != 2):
            raise TestDatabaseSafetyError("Both run-owned database services are required")
        for resource in ("volume", "network"):
            names = run_command(["docker", resource, "ls", "--filter", f"label=com.docker.compose.project={self.project}", "--format", "{{.Name}}"], self.config)
            for name in names.splitlines():
                labels = self._inspect(["docker", resource, "inspect", name])[0].get("Labels") or {}
                if labels.get("com.docker.compose.project") != self.project or labels.get("tavanir.e2e.run") != self.owner_run_id or labels.get("tavanir.environment") != "test":
                    raise TestDatabaseSafetyError("Run-owned network/storage labels are not verified")
        networks = run_command(["docker", "network", "ls", "--filter", f"label=com.docker.compose.project={self.project}", "--format", "{{.ID}}"], self.config)
        for identifier in networks.splitlines():
            labels = self._inspect(["docker", "network", "inspect", identifier])[0].get("Labels") or {}
            if labels.get("com.docker.compose.project") != self.project or labels.get("tavanir.e2e.run") != self.owner_run_id or labels.get("tavanir.environment") != "test":
                raise TestDatabaseSafetyError("Run-owned network labels are not verified")
        if self._container_ids is not None and self._container_ids != ids and require_complete:
            raise TestDatabaseSafetyError("Run-owned container identities changed during execution")
        self._container_ids = ids

    def _compose(self):
        return ["docker", "compose", "-p", self.project, "-f", str(self.compose_path)]

    def provision(self) -> E2EConfig:
        if self.config.infrastructure == "existing":
            self.verify()
            return self.config
        # Never adopt resources with a matching name; allocation precedes all writes.
        listing = run_command(["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={self.project}", "--format", "{{.ID}}"], self.config)
        if listing.strip():
            raise TestDatabaseSafetyError("Disposable project already exists; refusing adoption")
        for resource in ("volume", "network"):
            existing = run_command(["docker", resource, "ls", "--filter", f"label=com.docker.compose.project={self.project}", "--format", "{{.Name}}"], self.config)
            if existing.strip():
                raise TestDatabaseSafetyError("Disposable project storage/network already exists; refusing adoption")
        forbidden = {7432, 7333, 7334}
        ports = []
        while len(ports) < 3:
            port = free_port()
            if port not in forbidden and port not in ports:
                ports.append(port)
        database = replace(self.config.database, pg_port=ports[0], q_port=ports[1], q_grpc_port=ports[2], pg_password=secrets.token_hex(24), pg_admin_password=secrets.token_hex(24), q_api_key=secrets.token_hex(24), environment_id=f"e2e-{self.owner_run_id}")
        self.config = self.config.with_database(database)
        labels = {"tavanir.environment": "test", "tavanir.e2e.run": self.owner_run_id}
        content = {
            "services": {
                "postgres": {"image": "postgres:16-alpine", "restart": "no", "labels": labels, "ports": [f"127.0.0.1:{database.pg_port}:5432"],
                    "environment": {"POSTGRES_USER": "test_admin", "POSTGRES_PASSWORD": "${TEST_POSTGRES_ADMIN_PASSWORD}", "POSTGRES_DB": database.pg_database, "TEST_POSTGRES_USERNAME": database.pg_username, "TEST_POSTGRES_PASSWORD": "${TEST_POSTGRES_PASSWORD}", "TEST_ENVIRONMENT_ID": database.environment_id},
                    "volumes": ["postgres_data:/var/lib/postgresql/data", {"type": "bind", "source": str(self.config.repo_root / "tests/support/init_test_postgres.sh"), "target": "/docker-entrypoint-initdb.d/10-test-environment.sh", "read_only": True}],
                    "healthcheck": {"test": ["CMD-SHELL", "pg_isready -U test_admin -d tavanir_test_db"], "interval": "2s", "timeout": "3s", "retries": 40}},
                "qdrant": {"image": "qdrant/qdrant:v1.17.1", "restart": "no", "labels": labels, "ports": [f"127.0.0.1:{database.q_port}:6333", f"127.0.0.1:{database.q_grpc_port}:6334"], "environment": {"QDRANT__SERVICE__API_KEY": "${TEST_QDRANT_API_KEY}", "QDRANT__TELEMETRY_DISABLED": "true"}, "volumes": ["qdrant_data:/qdrant/storage"]}},
            "volumes": {"postgres_data": {"labels": labels}, "qdrant_data": {"labels": labels}},
            "networks": {"default": {"labels": labels}},
        }
        self.config.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.compose_path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        self._created = True  # Also owns resources from a partially failed up.
        run_command(self._compose() + ["up", "-d", "--wait", "--wait-timeout", "120", "--pull", "never"], self.config)
        self.verify()
        asyncio.run(self._provision_stores())
        return self.config

    async def _provision_stores(self):
        engine = create_async_engine(self.config.database.postgres_url, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                await verify_postgres_connection(connection, self.config.database)
        finally:
            await engine.dispose()
        run_command([self.config.python_executable, "-m", "alembic", "upgrade", "head"], self.config)
        async with httpx.AsyncClient(base_url=self.config.database.qdrant_url, headers={"api-key": self.config.database.q_api_key}, timeout=60, trust_env=False) as client:
            response = await client.put(f"/collections/{GUARD_COLLECTION}", json={"vectors": {"size": 1, "distance": "Cosine"}})
            response.raise_for_status()
            response = await client.put(f"/collections/{GUARD_COLLECTION}/points?wait=true", json={"points": [{"id": GUARD_POINT_ID, "vector": [1.0], "payload": {"environment": "test", "environment_id": self.config.database.environment_id}}]})
            response.raise_for_status()
            for collection in (self.config.collection, self.config.database.application_environment()["QDRANT_REGULATORY_COLLECTION"]):
                response = await client.put(f"/collections/{collection}", json={"vectors": {self.config.dense_name: {"size": self.config.dense_dimension, "distance": "Cosine"}}, "sparse_vectors": {self.config.sparse_name: {}}})
                response.raise_for_status()
                for field in ("parent_id", "chunk_status", "chunk_type", "status"):
                    response = await client.put(f"/collections/{collection}/index?wait=true", json={"field_name": field, "field_schema": "keyword"})
                    response.raise_for_status()
            response = await client.post("/collections/aliases", json={"actions": [{"create_alias": {"collection_name": self.config.collection, "alias_name": self.config.alias}}]})
            response.raise_for_status()

    def readiness(self) -> dict:
        self.verify()
        oracle = RawStoreOracle(self.config)
        snapshot = oracle.all_snapshot()
        with httpx.Client(base_url=self.config.database.qdrant_url, headers={"api-key": self.config.database.q_api_key}, timeout=self.config.request_timeout, trust_env=False) as client:
            response = client.get(f"/collections/{self.config.collection}")
            response.raise_for_status()
            params = response.json()["result"]["config"]["params"]
            dense = params["vectors"][self.config.dense_name]
            if dense["size"] != self.config.dense_dimension or self.config.sparse_name not in params.get("sparse_vectors", {}):
                raise TestDatabaseSafetyError("Destination vector names or dimension are incompatible")
        identities = sorted(self._existing_fingerprints or self._container_ids or ())
        services = [{"container_id": item["Id"], "image": item["Config"]["Image"], "image_id": item["Image"]} for item in self._inspect(["docker", "inspect", *identities])]
        return {"sql_rows": len(snapshot["sql"]), "points": len(snapshot["points"]), "store_markers": "verified", "docker_ownership": "verified", "alias_dimension": "verified", "services": services}

    def seed_if_empty(self, *, live_embeddings: bool = True) -> dict:
        # Existing seeder truncates both stores: allow only completely empty destination.
        self.verify()
        current = RawStoreOracle(self.config).all_snapshot()
        regulatory = self.config.database.application_environment()["QDRANT_REGULATORY_COLLECTION"]
        with httpx.Client(base_url=self.config.database.qdrant_url, headers={"api-key": self.config.database.q_api_key}, timeout=self.config.request_timeout, trust_env=False) as client:
            response = client.post(f"/collections/{regulatory}/points/count", json={"exact": True})
            response.raise_for_status()
            regulatory_count = response.json()["result"]["count"]
        if current["sql"] or current["points"] or regulatory_count:
            return {"seeded": False, "reason": "Existing test data preserved"}
        bootstrap = (
            "import asyncio; from pathlib import Path; "
            "from tests.database_safety import bootstrap_test_environment; "
            "c=bootstrap_test_environment(Path.cwd()); "
            "from tests.support.seeding.seeder import run_seeder; "
            f"asyncio.run(run_seeder(c, live_embeddings={live_embeddings!r}))"
        )
        run_command([self.config.python_executable, "-c", bootstrap], self.config)
        return {"seeded": True, "live_embeddings": live_embeddings}

    def cleanup(self):
        from .harness import settle_owned_preparations
        preparation = settle_owned_preparations(self.config)
        if self.config.infrastructure == "existing":
            return {"removed": False, "reason": "Existing guarded stack retained", "preparation": preparation}
        if not self._created and self.compose_path.exists():
            self.recover()
        if not self._created:
            return {"removed": False, "reason": "No run-owned stack created"}
        self.verify(require_running=False, require_complete=False)
        run_command(self._compose() + ["down", "--volumes", "--remove-orphans"], self.config)
        self._created = False
        return {"removed": True, "project": self.project, "preparation": preparation}

    def recover(self):
        """Recover generated settings privately from verified run-owned containers."""
        if self.config.infrastructure != "disposable" or not self.compose_path.is_file():
            raise TestDatabaseSafetyError("Only an existing run-owned disposable manifest can be recovered")
        listing = run_command(["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={self.project}", "--format", "{{.ID}}"], self.config)
        found = {}
        for identifier in listing.splitlines():
            details = self._inspect(["docker", "inspect", identifier])[0]
            labels = details["Config"].get("Labels") or {}
            service = labels.get("com.docker.compose.service")
            if labels.get("tavanir.environment") != "test" or labels.get("tavanir.e2e.run") != self.owner_run_id or labels.get("com.docker.compose.project") != self.project or service not in {"postgres", "qdrant"} or service in found:
                raise TestDatabaseSafetyError("Cannot recover a container outside exact run ownership")
            found[service] = details
        if set(found) == {"postgres", "qdrant"}:
            pg = found["postgres"]
            q = found["qdrant"]
            pg_env = dict(item.split("=", 1) for item in pg["Config"]["Env"] if "=" in item)
            q_env = dict(item.split("=", 1) for item in q["Config"]["Env"] if "=" in item)
            pg_ports, q_ports = pg["HostConfig"]["PortBindings"], q["HostConfig"]["PortBindings"]
            database = replace(self.config.database, pg_port=int(pg_ports["5432/tcp"][0]["HostPort"]), q_port=int(q_ports["6333/tcp"][0]["HostPort"]), q_grpc_port=int(q_ports["6334/tcp"][0]["HostPort"]), pg_database=pg_env["POSTGRES_DB"], pg_username=pg_env["TEST_POSTGRES_USERNAME"], pg_password=pg_env["TEST_POSTGRES_PASSWORD"], pg_admin_password=pg_env["POSTGRES_PASSWORD"], q_api_key=q_env["QDRANT__SERVICE__API_KEY"], environment_id=pg_env["TEST_ENVIRONMENT_ID"])
            self.config = self.config.with_database(database)
        elif found:
            # Partial startup cleanup needs exact expected published ports only.
            document = json.loads(self.compose_path.read_text(encoding="utf-8"))
            service_ports = {name: [int(binding.split(":")[1]) for binding in value["ports"]] for name, value in document["services"].items()}
            self.config = self.config.with_database(replace(self.config.database, pg_port=service_ports["postgres"][0], q_port=service_ports["qdrant"][0], q_grpc_port=service_ports["qdrant"][1]))
        self._created = True
        self.verify(require_running=False, require_complete=False)
        return self.config
