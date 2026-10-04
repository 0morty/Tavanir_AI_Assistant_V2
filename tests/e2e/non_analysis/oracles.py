"""Independent raw SQL/REST store evidence and exact fixture administration."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import ssl
import uuid
from collections.abc import Callable, Iterable
from datetime import date, datetime

import httpx
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.database_safety import GUARD_COLLECTION, GUARD_POINT_ID, TestDatabaseSafetyError, assert_qdrant_identity, verify_postgres_connection
from tests.e2e.non_analysis.config import E2EConfig

SQL_FIELDS = "id, title, problem, solution, status_id, committee_scrutiny, description, committee_scrutiny_id, secretariat_scrutiny_id, secretariat_scrutiny, secretariat_comment, shamsi_date, context_title, is_deleted, version, created_at, updated_at"
STATUS_TITLES = {1: "عدم پذیرش", 2: "رد", 3: "مصوب", 4: "در حال اجرا", 5: "اجرا شده"}


def jsonable(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(item) for item in value]
    return value


def canonical(value) -> str:
    return json.dumps(jsonable(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def assert_unchanged(before: dict, after: dict):
    """Include exact point IDs, complete payloads, dense and sparse vectors."""
    if canonical(before) != canonical(after):
        raise AssertionError("Unrelated/sentinel store data changed")


def validate_vectors(points: list[dict], config: E2EConfig):
    for point in points:
        vector = point.get("vector") or {}
        dense = vector.get(config.dense_name) if isinstance(vector, dict) else vector
        if not isinstance(dense, list) or len(dense) != config.dense_dimension:
            raise AssertionError(f"Dense vector dimension mismatch for point {point.get('id')}")
        if any(type(value) not in {int, float} or not math.isfinite(value) for value in dense):
            raise AssertionError("Dense vector contains nonfinite/non-numeric values")
        sparse = vector.get(config.sparse_name) if isinstance(vector, dict) else None
        if sparse is None:
            raise AssertionError("Configured sparse vector is missing")
        indices, values = sparse.get("indices"), sparse.get("values")
        if not isinstance(indices, list) or not isinstance(values, list) or len(indices) != len(values):
            raise AssertionError("Sparse vector index/value lengths differ")
        if any(type(index) is not int or index < 0 for index in indices) or len(indices) != len(set(indices)):
            raise AssertionError("Sparse vector has invalid/duplicate indices")
        if any(type(value) not in {int, float} or not math.isfinite(value) for value in values):
            raise AssertionError("Sparse vector has nonfinite/non-numeric values")


def assert_consistent(snapshot: dict, config: E2EConfig, *, parent_id: str | None = None, expected_version: int | None = None, expected_deleted: bool | None = None, chunks_count: int | None = None, expected_fields: dict | None = None, require_exists: bool = False):
    row, points = snapshot["sql"], snapshot["points"]
    if row is None:
        if require_exists or any(value is not None for value in (expected_version, expected_deleted, chunks_count, expected_fields)):
            raise AssertionError("Expected SQL parent is absent")
        if points:
            raise AssertionError("Vector points exist without a SQL parent")
        return
    parent_id = parent_id or row["id"]
    if expected_version is not None:
        assert row["version"] == expected_version, "Unexpected SQL version"
    if expected_deleted is not None:
        assert row["is_deleted"] is expected_deleted, "Unexpected SQL deletion flag"
    for key, expected in (expected_fields or {}).items():
        assert row.get(key) == expected, f"SQL {key} differs from independent expected field"
    if row["is_deleted"]:
        assert not points, "Soft-deleted parent retains vector points"
        return
    assert points, "Active SQL parent has no vector points"
    if chunks_count is not None:
        assert len(points) == chunks_count, "HTTP chunk count differs from complete stored point count"
    ids = [str(point["id"]) for point in points]
    assert len(ids) == len(set(ids)), "Duplicate point IDs"
    metadata = {"status": STATUS_TITLES[row["status_id"]], "context_title": row["context_title"], "date": row["shamsi_date"], "committee_scrutiny_id": row["committee_scrutiny_id"], "secretariat_scrutiny_id": row["secretariat_scrutiny_id"]}
    by_type = {"title": row["title"], "problem": row["problem"], "solution": row["solution"]}
    for point in points:
        payload = point.get("payload") or {}
        assert payload.get("parent_id") == parent_id, "Vector parent mismatch"
        assert payload.get("chunk_status") == "active", "Final vector lifecycle state is not active"
        for key, expected in metadata.items():
            assert payload.get(key) == expected, f"Vector metadata {key} differs from SQL"
        kind = payload.get("chunk_type")
        assert kind in {"title", "problem", "solution", "evaluation"}, "Unknown chunk type"
        assert isinstance(payload.get("content"), str) and payload["content"].strip(), "Blank vector chunk"
        if kind in by_type and payload.get("parent_content") is not None:
            assert payload["parent_content"] == by_type[kind], "Stored source field differs from SQL"
        if kind == "title":
            context = row["context_title"] or ""
            valid_context = len(context.strip()) >= 5 and any(char.isalnum() for char in context)
            expected_title = f"حوزه: {context.strip()} | عنوان: {row['title'].strip()}" if valid_context else row["title"].strip()
            assert payload["content"] == expected_title, "Title vector does not correspond to current SQL"
        if kind in {"problem", "solution"}:
            assert " ".join(payload["content"].split()) in " ".join(by_type[kind].split()), "Chunk content does not occur in current SQL source field"
    validate_vectors(points, config)


class FixtureRegistry:
    def __init__(self, config: E2EConfig):
        self.config = config
        self.ids: set[str] = set()
        self.claims: dict[str, dict] = {}

    def register(self, parent_id: str) -> str:
        if not isinstance(parent_id, str) or not parent_id.startswith(self.config.fixture_prefix) or len(parent_id) > 64 or any(char in parent_id for char in "\r\n\x00"):
            raise TestDatabaseSafetyError("Fixture administration requires an exact run-owned parent ID")
        self.ids.add(parent_id)
        self.claims[parent_id] = {"run_namespace": True}
        return parent_id

    def require(self, parent_id: str):
        if parent_id not in self.ids:
            raise TestDatabaseSafetyError("Refusing to mutate an unregistered parent or source/sentinel record")

    def claim_absent(self, parent_id: str):
        """Called only after the harness proves a boundary-test ID is absent."""
        if not isinstance(parent_id, str) or not parent_id or len(parent_id) > 4096 or any(char in parent_id for char in "\r\n\x00"):
            raise TestDatabaseSafetyError("Explicit fixture IDs must be bounded strings without controls")
        self.ids.add(parent_id)
        self.claims[parent_id] = {"absent_before": True}
        return parent_id

    @classmethod
    def from_journal(cls, config: E2EConfig, journal: dict, *, sentinel_ids: Iterable[str] = ()):
        if journal.get("run_id") != config.run_id or journal.get("config") != config.redacted():
            raise TestDatabaseSafetyError("Interrupted cleanup journal belongs to another run or target")
        registry = cls(config)
        ids, claims = journal.get("ids"), journal.get("claims", {})
        if not isinstance(ids, list) or not isinstance(claims, dict):
            raise TestDatabaseSafetyError("Interrupted cleanup journal has invalid ownership claims")
        sentinels = set(sentinel_ids)
        for parent_id in ids:
            if not isinstance(parent_id, str) or parent_id in sentinels:
                raise TestDatabaseSafetyError("Interrupted cleanup cannot claim source or sentinel data")
            claim = claims.get(parent_id, {})
            if claim.get("absent_before") is True:
                registry.claim_absent(parent_id)
            elif claim.get("run_namespace") is True or parent_id.startswith(config.fixture_prefix):
                registry.register(parent_id)
            else:
                raise TestDatabaseSafetyError("Boundary fixture cleanup needs its recorded absence witness")
        return registry

    def new_id(self, label: str = "fixture") -> str:
        clean = "".join(char if char.isalnum() else "-" for char in label)[:max(1, 64 - len(self.config.fixture_prefix) - 9)]
        return self.register(self.config.fixture_prefix + clean + "-" + uuid.uuid4().hex[:8])


class RawStoreOracle:
    """Loop-independent sync facade; raw readers bypass application fault proxies."""

    def __init__(self, config: E2EConfig, *, verify_ownership: Callable[[], None] | None = None, page_size: int = 100):
        if page_size <= 0:
            raise ValueError("Qdrant page size must be positive")
        self.config = config
        self.verify_ownership = verify_ownership
        self.page_size = page_size
        # Each facade serves thousands of independent HTTP captures. Reuse its
        # verified TLS configuration while keeping connections/event loops local.
        self._tls_context = ssl.create_default_context()

    def _client(self):
        return httpx.AsyncClient(base_url=self.config.database.qdrant_url, headers={"api-key": self.config.database.q_api_key}, timeout=self.config.request_timeout, trust_env=False, verify=self._tls_context)

    async def _qdrant_identity(self, client):
        response = await client.post(f"/collections/{GUARD_COLLECTION}/points", json={"ids": [GUARD_POINT_ID], "with_payload": True, "with_vector": False})
        response.raise_for_status()
        points = response.json().get("result")
        if not isinstance(points, list) or len(points) != 1:
            raise TestDatabaseSafetyError("Qdrant test marker missing or ambiguous")
        assert_qdrant_identity(points[0].get("payload") or {}, self.config.database)
        aliases = await client.get("/aliases")
        aliases.raise_for_status()
        matches = [item for item in aliases.json()["result"]["aliases"] if item["alias_name"] == self.config.alias]
        if len(matches) != 1 or matches[0]["collection_name"] != self.config.collection:
            raise TestDatabaseSafetyError("Test alias points outside the verified destination collection")

    async def _scroll(self, client, parent_ids: Iterable[str] | None = None, *, collection: str | None = None):
        ids = list(parent_ids) if parent_ids is not None else None
        if ids == []:
            return []
        offset = None
        seen_offsets = set()
        points = []
        while True:
            body = {"limit": self.page_size, "with_payload": True, "with_vector": True}
            if ids is not None:
                body["filter"] = {"must": [{"key": "parent_id", "match": {"any": ids}}]}
            if offset is not None:
                body["offset"] = offset
            response = await client.post(f"/collections/{collection or self.config.collection}/points/scroll", json=body)
            response.raise_for_status()
            result = response.json()["result"]
            points.extend(result["points"])
            offset = result.get("next_page_offset")
            if offset is None:
                break
            key = str(offset)
            if key in seen_offsets:
                raise AssertionError("Qdrant scroll returned a repeated pagination offset")
            seen_offsets.add(key)
        ids_seen = [str(point["id"]) for point in points]
        if len(ids_seen) != len(set(ids_seen)):
            raise AssertionError("Qdrant scroll repeated a point between pages")
        return sorted(points, key=lambda point: str(point["id"]))

    async def _snapshot(self, parent_ids: Iterable[str] | None = None):
        ids = list(parent_ids) if parent_ids is not None else None
        engine = create_async_engine(self.config.database.postgres_url, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                await verify_postgres_connection(connection, self.config.database)
                rows = []
                if ids != []:
                    statement = text(f"SELECT {SQL_FIELDS} FROM public.suggestions" + (" WHERE id IN :ids" if ids is not None else "") + " ORDER BY id")
                    if ids is not None:
                        statement = statement.bindparams(bindparam("ids", expanding=True))
                    rows = [jsonable(dict(row)) for row in (await connection.execute(statement, {"ids": ids} if ids is not None else {})).mappings().all()]
            async with self._client() as client:
                await self._qdrant_identity(client)
                points = await self._scroll(client, ids)
                regulatory = await self._scroll(client, collection=self.config.database.application_environment()["QDRANT_REGULATORY_COLLECTION"]) if ids is None else None
            result = {"sql": {row["id"]: row for row in rows}, "points": points}
            if regulatory is not None:
                result["regulatory_points"] = regulatory
            return result
        finally:
            await engine.dispose()

    def snapshot(self, parent_id: str) -> dict:
        result = asyncio.run(self._snapshot([parent_id]))
        return {"sql": result["sql"].get(parent_id), "points": result["points"]}

    def all_snapshot(self) -> dict:
        return asyncio.run(self._snapshot())

    def snapshots(self, parent_ids: Iterable[str]) -> dict:
        return asyncio.run(self._snapshot(parent_ids))

    def _assert_write_target(self):
        if self.verify_ownership is None:
            raise TestDatabaseSafetyError("Writes require independently verified Docker ownership")
        self.verify_ownership()

    async def _clear_points(self, parent_ids):
        async with self._client() as client:
            await self._qdrant_identity(client)
            response = await client.post(f"/collections/{self.config.collection}/points/delete?wait=true", json={"filter": {"must": [{"key": "parent_id", "match": {"any": list(parent_ids)}}]}})
            response.raise_for_status()

    def clear_parent_points(self, parent_id: str, registry: FixtureRegistry):
        registry.require(parent_id)
        self._assert_write_target()
        asyncio.run(self._clear_points([parent_id]))

    async def _append_clones(self, parent_id, lifecycle_states, templates=None):
        async with self._client() as client:
            await self._qdrant_identity(client)
            originals = await self._scroll(client, [parent_id])
            if not originals and templates:
                originals = templates
                if any((point.get("payload") or {}).get("parent_id") != parent_id for point in originals):
                    raise TestDatabaseSafetyError("Orphan templates must belong to the exact registered parent")
            if not originals:
                raise ValueError("Cannot clone an absent parent point set")
            clones = []
            for state in lifecycle_states:
                if state not in {"active", "staging", "deprecated"}:
                    raise ValueError("Invalid lifecycle state")
                point = copy.deepcopy(originals[0])
                point["id"] = str(uuid.uuid4())
                point["payload"]["chunk_id"] = str(point["id"])
                point["payload"]["chunk_status"] = state
                clones.append(point)
            response = await client.put(f"/collections/{self.config.collection}/points?wait=true", json={"points": clones})
            response.raise_for_status()
            return [point["id"] for point in clones]

    def append_cloned_points(self, parent_id: str, lifecycle_states: Iterable[str], registry: FixtureRegistry, *, templates=None):
        registry.require(parent_id)
        self._assert_write_target()
        return asyncio.run(self._append_clones(parent_id, lifecycle_states, templates))

    async def _remove_sql_row(self, parent_id):
        engine = create_async_engine(self.config.database.postgres_url, poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                await verify_postgres_connection(connection, self.config.database)
                await connection.execute(text("DELETE FROM public.suggestions WHERE id = :id"), {"id": parent_id})
        finally:
            await engine.dispose()

    def remove_sql_row(self, parent_id: str, registry: FixtureRegistry):
        registry.require(parent_id)
        self._assert_write_target()
        asyncio.run(self._remove_sql_row(parent_id))

    async def _cleanup(self, parent_ids):
        if not parent_ids:
            return {"parents": [], "sql_absent": True, "points_absent": True}
        await self._clear_points(parent_ids)
        engine = create_async_engine(self.config.database.postgres_url, poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                await verify_postgres_connection(connection, self.config.database)
                statement = text("DELETE FROM public.suggestions WHERE id IN :ids").bindparams(bindparam("ids", expanding=True))
                await connection.execute(statement, {"ids": parent_ids})
        finally:
            await engine.dispose()
        remaining = await self._snapshot(parent_ids)
        if remaining["sql"] or remaining["points"]:
            raise AssertionError("Exact fixture cleanup left SQL rows or vector points")
        return {"parents": parent_ids, "sql_absent": True, "points_absent": True}

    def cleanup(self, registry: FixtureRegistry):
        self._assert_write_target()
        for parent_id in registry.ids:
            registry.require(parent_id)
        return asyncio.run(self._cleanup(sorted(registry.ids)))

    @staticmethod
    def exclude(snapshot: dict, parent_ids: Iterable[str]) -> dict:
        own = set(parent_ids)
        result = {"sql": {key: value for key, value in snapshot["sql"].items() if key not in own},
                  "points": [point for point in snapshot["points"] if (point.get("payload") or {}).get("parent_id") not in own]}
        if "regulatory_points" in snapshot:
            result["regulatory_points"] = snapshot["regulatory_points"]
        return result
