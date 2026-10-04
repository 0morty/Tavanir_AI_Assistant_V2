"""Deterministic non-analysis fault, concurrency, acknowledgement, crash probes.

HTTP requests execute the real orchestration against the guarded stores. Every
race starts its next participant only after a recorded collaborator phase; no
sleep chooses a winner. Known consistency defects deliberately fail assertions.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .proxy import FaultController, FaultRule, ForwardingProxy, input_fingerprint, provider_vector_values


@dataclass(frozen=True)
class ResilienceScenario:
    case_id: str
    variant_id: str
    action: str
    method: str = "POST"
    profile: str = "instrumented_fault"
    parameters: dict[str, Any] = field(default_factory=dict)
    fixture: str = "fresh run-owned synthetic parents; historical sentinels unchanged"
    expected: str = "HTTP outcome and both raw stores match the declared fault schedule"
    cleanup: str = "Release all gates; restore proxies/app settings; exact registered SQL and vector cleanup"


def _scenario(case, variant, action, *, method="POST", profile="instrumented_fault", **parameters):
    return ResilienceScenario(case, variant, action, method, profile, parameters)


def _descriptors():
    result = []
    for method in ("POST", "PUT", "PATCH"):
        for fault in ("unreachable", "reset", "timeout"):
            result.append(_scenario("DEP-01", f"{method.lower()}_{fault}", "provider", method=method,
                                    profile="external_fault", fault=fault))
        for fault in ("401", "429_retry", "429_plain", "500", "unknown_model", "context_limit"):
            result.append(_scenario("DEP-02", f"{method.lower()}_{fault}", "provider", method=method,
                                    profile="controlled_provider", fault=fault))
        for fault in ("missing", "extra", "reordered", "duplicate_indices", "missing_indices"):
            result.append(_scenario("DEP-03", f"{method.lower()}_{fault}", "provider", method=method,
                                    profile="controlled_provider", fault=fault))
        for fault in ("wrong_dimension", "nonfinite", "decoding"):
            result.append(_scenario("DEP-04", f"{method.lower()}_{fault}", "provider", method=method,
                                    profile="controlled_provider", fault=fault))
        result.append(_scenario("DEP-04", f"{method.lower()}_malformed_sparse", "malformed_sparse", method=method))
        for fault, operation, error, status in (
            ("normalizer", "normalizer.normalize", "normalizer", 422),
            ("sparse", "sparse.embed", "sparse", 500),
            ("chunking_domain", "chunker.chunk", "chunking", 422),
            ("chunking_suggestion", "chunker.chunk", "chunker", 422),
            ("chunker_runtime", "chunker.chunk", "runtime", 500),
            ("zero_chunks", "chunker.chunk", "runtime", 422),
        ):
            result.append(_scenario("DEP-05", f"{method.lower()}_{fault}", "early", method=method,
                                    operation=operation, error=error, status=status, zero=fault == "zero_chunks"))
    for case, operation, timing in (("ING-F01", "sql.read", "before"),
                                    ("ING-F02", "sql.save", "before"),
                                    ("ING-F02", "sql.commit", "before"),
                                    ("ING-F02", "sql.commit", "after")):
        result.append(_scenario(case, operation.replace(".", "_") + "_" + timing, "ingest_sql", operation=operation, timing=timing))
    result.extend([
        _scenario("ING-F03", "residual_purge", "ingest_vector", operation="vector.purge"),
        *[_scenario("ING-F04", name, "ingest_slice", later=later, transient=transient)
          for name, later, transient in (("first_fatal", False, False), ("later_fatal_batch2", True, False),
                                         ("first_exhaustion", False, True), ("later_exhaustion_batch2", True, True))],
        *[_scenario("ING-F05", name, "ingest_vector", operation=op, timing=timing)
          for name, op, timing in (("before_demotion", "vector.promote", "before"),
                                  ("between_payloads", "qdrant.promote", "before"),
                                  ("applied_lost_ack", "qdrant.promote", "after"))],
        _scenario("ING-F06", "vector_compensation_failed", "ingest_compensation", vector_cleanup=True),
        _scenario("ING-F07", "sql_compensation_failed", "ingest_compensation", sql_cleanup=True),
        _scenario("ING-F08", "both_compensations_failed", "ingest_compensation", sql_cleanup=True, vector_cleanup=True),
        *[_scenario("ING-F09", name, "crash", phase=phase, timing="after", workflow="ingest", cancel=cancel)
          for name, phase, cancel in (("kill_after_commit", "sql.commit", False), ("kill_after_staging", "vector.upsert", False),
                                    ("kill_after_promotion", "vector.promote", False), ("cancel_after_commit", "sql.commit", True),
                                    ("cancel_after_staging", "vector.upsert", True), ("cancel_after_promotion", "vector.promote", True))],
        _scenario("ING-F10", "same_id_both_duplicate_checks", "race_ingest"),
        _scenario("ING-F10", "accepted_creation_lost_to_compensation", "race_ingest", fail_second=True),
        _scenario("ING-F11", "recover_before_attempt_limit", "ingest_slice", transient=True, recover=True),
        _scenario("ING-F11", "recovery_one_attempt_too_late", "ingest_slice", transient=True),
        _scenario("ING-F12", "missing_runtime_alias", "alias", alias_mode="missing"),
        _scenario("ING-F12", "incompatible_runtime_schema", "alias", alias_mode="incompatible"),
        _scenario("ING-F13", "retry_fully_compensated", "retry_ingest", orphan=False),
        _scenario("ING-F13", "retry_clears_orphan_points", "retry_ingest", orphan=True),
        _scenario("ING-F14", "orphan_before_early_embedding_failure", "orphan_early"),
        _scenario("ING-F14", "sql_without_points_still_conflicts", "sql_only_conflict"),
    ])
    for method in ("PUT", "PATCH"):
        prefix = method.lower()
        result.extend([
            _scenario("MUT-F01", prefix + "_initial_read", "early", method=method, operation="sql.read", error="runtime", status=500),
            *[_scenario("MUT-F02", prefix + "_" + name, "mutation_slice", method=method, later=later)
              for name, later in (("first_slice", False), ("later_slice_batch2", True))],
            _scenario("MUT-F03", prefix + "_staging_cleanup_failed", "mutation_slice", method=method, cleanup_failure=True, applied=True),
            _scenario("MUT-F04", prefix + "_separate_transaction_lock", "lock", method=method),
            _scenario("MUT-F05", prefix + "_stale_version", "race_stale", method=method),
            *[_scenario("MUT-F06", prefix + "_" + state, "race_missing", method=method, state=state)
              for state in ("hard_deleted", "soft_deleted")],
            *[_scenario("MUT-F07", prefix + "_" + op.replace(".", "_") + "_" + timing, "mutation_sql", method=method, operation=op, timing=timing)
              for op, timing in (("sql.save", "before"), ("sql.commit", "before"), ("sql.commit", "after"))],
            _scenario("MUT-F08", prefix + "_phase2_cleanup_failed", "mutation_sql", method=method, operation="sql.save", cleanup_failure=True),
            *[_scenario("MUT-F09", prefix + "_" + name, "cutover", method=method, operation=op, attempt=1)
              for name, op in (("before_demotion_recovery", "vector.promote"), ("between_payloads_recovery", "qdrant.promote"))],
            _scenario("MUT-F10", prefix + "_promotion_then_purge_retry", "cutover", method=method, operation="vector.superseded", attempt=1),
            _scenario("MUT-F11", prefix + "_cutover_exhaustion", "cutover", method=method, operation="vector.promote", attempt=[1, 2, 3], exhausted=True),
            *[_scenario("MUT-F12", prefix + "_" + name, "cutover", method=method, operation=op, timing="after", attempt=1)
              for name, op in (("promotion_applied_lost_ack", "vector.promote"), ("purge_applied_lost_ack", "vector.superseded"))],
            _scenario("MUT-F13", prefix + "_observed_cutover_blackout", "blackout", method=method),
            *[_scenario("MUT-F14", prefix + "_" + name, "crash", method=method, workflow="mutation", phase=phase, timing="after", cancel=cancel)
              for name, phase, cancel in (("kill_after_staging", "vector.upsert", False), ("kill_after_commit", "sql.commit", False),
                                        ("kill_between_promotion_purge", "vector.promote", False), ("cancel_after_staging", "vector.upsert", True),
                                        ("cancel_after_commit", "sql.commit", True), ("cancel_between_promotion_purge", "vector.promote", True))],
            _scenario("MUT-F15", prefix + "_retry_after_error", "retry_mutation", method=method),
        ])
    result.extend([
        _scenario("DEL-06", "separate_transaction_lock", "lock", method="DELETE"),
        *[_scenario("DEL-07", op.replace(".", "_") + "_" + timing, "delete_sql", method="DELETE", operation=op, timing=timing)
          for op, timing in (("sql.read", "before"), ("sql.soft_delete", "before"), ("sql.commit", "before"), ("sql.commit", "after"))],
        _scenario("DEL-08", "purge_before_apply_restored", "delete_vector", method="DELETE"),
        _scenario("DEL-09", "purge_and_compensation_failed", "delete_vector", method="DELETE", cleanup_failure=True),
        _scenario("DEL-10", "purge_applied_lost_ack", "delete_vector", method="DELETE", timing="after"),
        _scenario("DEL-11", "compensation_ignores_separate_lock", "compensation_lock", method="DELETE"),
        _scenario("DEL-12", "kill_after_soft_delete_commit", "crash", method="DELETE", workflow="delete", phase="sql.commit", timing="after"),
        _scenario("DEL-13", "no_embedding_dependency", "delete_no_provider", method="DELETE"),
        _scenario("DEL-13", "deleted_noop_without_qdrant", "delete_no_qdrant", method="DELETE"),
    ])
    for position in ("first", "middle", "last"):
        result.extend([
            _scenario("BULK-06", position + "_locked", "bulk_fault", fault="lock", position=position),
            _scenario("BULK-07", position + "_vector_failure", "bulk_fault", fault="vector", position=position),
            _scenario("BULK-08", position + "_sql_failure", "bulk_fault", fault="sql", position=position),
        ])
    result.extend([
        _scenario("BULK-06", "all_locked", "bulk_fault", fault="lock", all_items=True),
        _scenario("BULK-08", "all_sql_failed", "bulk_fault", fault="sql", all_items=True),
        _scenario("BULK-09", "mixed_missing_lock_domain_success", "bulk_mixed"),
        _scenario("BULK-15", "all_vector_failed_independent_compensation", "bulk_fault", fault="vector", all_items=True),
        _scenario("BULK-17", "kill_after_first_completed_item", "bulk_crash"),
        *[_scenario("FLOW-04", variant, "race_stale", method=first, second_method=second)
          for variant, first, second in (("put_put", "PUT", "PUT"), ("patch_patch", "PATCH", "PATCH"), ("put_patch", "PUT", "PATCH"))],
        _scenario("FLOW-05", "older_cutover_after_newer_commit", "race_cutover"),
        _scenario("FLOW-06", "stale_staging_after_winner_cutover", "race_stale", method="PUT", hold_phase="vector.upsert"),
        *[_scenario("FLOW-07", variant, "race_delete_update", direction=direction, hold_phase=phase)
          for variant, direction, phase in (("update_staged_then_delete", "update_first", "vector.upsert"),
                                            ("update_committed_then_delete", "update_first", "sql.commit"),
                                            ("delete_committed_then_restore", "delete_first", "sql.commit"),
                                            ("delete_before_purge_then_restore", "delete_first", "vector.purge"))],
        _scenario("FLOW-08", "stale_compensation_overwrites_accepted_put", "race_compensation"),
        _scenario("FLOW-09", "same_id_deletes_lock_then_idempotency", "race_delete"),
        _scenario("FLOW-10", "bulk_and_single_overlap", "race_bulk", single=True),
        _scenario("FLOW-10", "overlapping_bulk_batches", "race_bulk", single=False),
        _scenario("FLOW-11", "independent_ids_scheduled_mutations", "independent"),
        _scenario("FLOW-12", "ingest_commit_then_put", "race_ingest_mutation", second_method="PUT"),
        _scenario("FLOW-12", "ingest_commit_then_delete", "race_ingest_mutation", second_method="DELETE"),
        _scenario("FLOW-13", "slow_embeddings_leave_unrelated_work_usable", "slow_embeddings"),
        *[_scenario("FLOW-14", variant + "_lost_response_retry", "lost_http", method=method, bulk=bulk, profile="external_fault")
          for variant, method, bulk in (("ingest", "POST", False), ("put", "PUT", False), ("patch", "PATCH", False),
                                       ("delete", "DELETE", False), ("bulk", "POST", True))],
        _scenario("FLOW-15", "successful_state_survives_owned_restart", "restart"),
        _scenario("HOST-03", "embedding_unreachable_liveness", "host_liveness", profile="external_fault"),
        *[_scenario("API-09", environment + "_" + category, "debug", environment=environment, category=category)
          for environment in ("production", "development") for category in ("validation", "provider")],
        _scenario("API-10", "fault_internal_omits_source", "error_source"),
        _scenario("API-10", "fault_bulk_internal_indexed_source", "bulk_fault", fault="sql", position="middle", check_source=True),
        _scenario("API-11", "provider_generated_request_id", "correlation", supplied=False),
        _scenario("API-11", "provider_supplied_request_id", "correlation", supplied=True),
        *[_scenario("API-11", f"{method.lower()}_provider_{kind}_request_id", "correlation", method=method, supplied=supplied)
          for method in ("PUT", "PATCH") for kind, supplied in (("generated", False), ("supplied", True))],
        *[_scenario("API-11", f"{endpoint}_qdrant_{kind}_request_id", "correlation", method="POST" if bulk else "DELETE",
                    supplied=supplied, dependency="qdrant", bulk=bulk)
          for endpoint, bulk in (("delete", False), ("bulk", True)) for kind, supplied in (("generated", False), ("supplied", True))],
        _scenario("API-12", "scheduled_concurrent_distinct_request_ids", "independent", check_correlation=True),
        _scenario("API-13", "primary_and_compensation_error_logs", "error_logs"),
        _scenario("API-14", "dependency_recovery_same_process", "recovered"),
        _scenario("BULK-18", "exact100_partial_failure_latency", "bulk_latency"),
        _scenario("ING-F03", "external_residual_purge_rejected", "external_qdrant", profile="external_fault", operation="http.qdrant.delete"),
        _scenario("ING-F04", "external_upsert_retry_exhaustion", "external_qdrant", profile="external_fault", operation="http.qdrant.upsert", attempts=[1, 2, 3], status=503),
        _scenario("ING-F04", "external_later_slice_retry_exhaustion_batch2", "external_qdrant", profile="external_fault", operation="http.qdrant.upsert", attempts=[2, 3, 4], status=503, later=True),
        _scenario("ING-F05", "external_promotion_applied_lost_ack", "external_qdrant", profile="external_fault", operation="http.qdrant.promote", lost=True),
        _scenario("MUT-F12", "put_external_promotion_lost_ack", "external_qdrant", method="PUT", profile="external_fault", operation="http.qdrant.promote", lost=True),
        _scenario("MUT-F12", "patch_external_purge_lost_ack", "external_qdrant", method="PATCH", profile="external_fault", operation="http.qdrant.superseded", lost=True),
        _scenario("DEL-10", "external_purge_applied_lost_ack", "external_qdrant", method="DELETE", profile="external_fault", operation="http.qdrant.delete", lost=True),
    ])
    for deleted in (False, True):
        for phase in ("sql.read", "normalizer.normalize", "chunker.chunk", "sparse.embed", "vector.upsert",
                      "sql.lock", "sql.save", "sql.commit", "vector.promote", "vector.superseded", "vector.delete_ids"):
            result.append(_scenario("PUT-12", ("deleted_" if deleted else "active_") + phase.replace(".", "_"),
                                    "put_failure", method="PUT", deleted=deleted, phase=phase))
    return tuple(result)


RESILIENCE_SCENARIOS = _descriptors()


def _body(parent: str, suffix: str = "الف") -> dict:
    return {"suggestionId": parent, "title": f"بهبود شبکه توزیع برق {suffix}",
            "problem": f"پایش تجهیزات شبکه به صورت دستی انجام می‌شود و زمان بیشتری نیاز دارد {suffix}",
            "solution": f"سامانه پایش برخط برای کاهش تلفات و افزایش کیفیت برق ایجاد شود {suffix}", "status": 3}


def _headers(parent: str, request_id: str) -> dict:
    return {"X-E2E-Operation-Id": request_id, "X-E2E-Parent-Id": parent}


def _request(harness, method: str, parent: str, request_id: str, suffix="ب", *, body=None):
    if method == "DELETE":
        return harness.request(method, f"/api/v1/suggestions/{parent}", headers=_headers(parent, request_id))
    data = body or _body(parent, suffix)
    if method == "PATCH":
        data = {"title": data["title"]}
    return harness.request(method, "/api/v1/suggestions/ingest" if method == "POST" else f"/api/v1/suggestions/{parent}",
                           json=data, headers=_headers(parent, request_id))


def _seed(harness, label="fault") -> str:
    parent = harness.new_id(label)
    response = _request(harness, "POST", parent, uuid.uuid4().hex, suffix="پایه")
    assert response.status_code == 201, response.text
    harness.assert_consistent(parent, expected_version=1, expected_deleted=False)
    return parent


def _prepare(harness, method):
    parent = harness.new_id("fault") if method == "POST" else _seed(harness)
    return parent, harness.snapshot(parent), uuid.uuid4().hex


def _status(response, status: int):
    assert response.status_code == status, response.text


def _unchanged(before, after):
    from .oracles import assert_unchanged
    assert_unchanged(before, after)


def _fault(controller, parent, request_id, *, operation, timing="before", attempt=1, error="vector", action="raise", **kwargs):
    rule = FaultRule("fault", operation, timing=timing, parent_id=parent,
                     request_id=request_id, attempt=attempt, error=error, action=action, **kwargs)
    controller.install([rule])
    return rule


def _rule(rule_id, operation, parent, request_id, **kwargs):
    return FaultRule(rule_id, operation, parent_id=parent, request_id=request_id, **kwargs)


def _barrier(controller, rule_id, epoch):
    return controller.wait(kind="barrier_entered", rule_id=rule_id, epoch=epoch)


def _record(harness, scenario, controller, parents, *, label="settled"):
    from .evidence import write_json
    destination = harness.config.artifacts_dir / "fault_evidence" / f"{scenario.case_id}-{scenario.variant_id}"
    destination.mkdir(parents=True, exist_ok=True)
    write_json(destination / f"{label}.json", {"case_id": scenario.case_id, "variant_id": scenario.variant_id,
                "stores": {parent: harness.snapshot(parent) for parent in parents},
                "fault_schedule": controller._schedule(),
                "schedule_events": controller.events(epoch=controller._schedule()["epoch"])}, harness.config.secrets())


@contextmanager
def _overrides(harness, overrides, *, qdrant_proxy=None):
    old = dict(harness.app.overrides)
    old_proof = harness.app.qdrant_proxy_proof
    harness.app.stop()
    harness.app.overrides.update({key: str(value) for key, value in overrides.items()})
    if qdrant_proxy is not None:
        harness.app.qdrant_proxy_proof = qdrant_proxy.ownership_proof(harness.config.run_id)
    try:
        harness.app.start()
        yield
    finally:
        harness.app.stop()
        harness.app.overrides.clear()
        harness.app.overrides.update(old)
        harness.app.qdrant_proxy_proof = old_proof
        harness.app.start()


class HeldAdvisoryLock:
    """Own a real separate SQL transaction; signal acquisition explicitly."""
    def __init__(self, harness, parents):
        self.harness = harness
        self.parents = list(parents)
        self.ready = threading.Event()
        self.release = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self._thread_main, daemon=True)

    def _thread_main(self):
        try:
            asyncio.run(self._hold())
        except BaseException as error:
            self.error = error
            self.ready.set()

    async def _hold(self):
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool
        from tests.database_safety import verify_postgres_connection
        engine = create_async_engine(self.harness.config.database.postgres_url, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                await verify_postgres_connection(connection, self.harness.config.database)
                # Verification opens a transaction; retain it for transaction-scoped locks.
                for parent in self.parents:
                    self.harness.registry.require(parent)
                    key = int.from_bytes(hashlib.sha256(parent.encode()).digest()[:8], "big", signed=True)
                    result = await connection.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key})
                    if not result.scalar_one():
                        raise AssertionError("Independent SQL lock could not be acquired")
                self.ready.set()
                released = await asyncio.to_thread(self.release.wait, 40)
                if not released:
                    raise TimeoutError("Owned advisory transaction release expired")
                await connection.rollback()
        finally:
            await engine.dispose()

    def __enter__(self):
        self.harness.infrastructure.verify()
        self.thread.start()
        if not self.ready.wait(10):
            self.release.set()
            raise TimeoutError("Owned advisory transaction did not acknowledge acquisition")
        if self.error:
            raise self.error
        return self

    def __exit__(self, *_):
        self.release.set()
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            raise TimeoutError("Owned advisory transaction did not terminate")
        if self.error:
            raise self.error


def _delete_sql_physically(harness, parent):
    harness.infrastructure.verify()
    harness.registry.require(parent)

    async def remove():
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool
        from tests.database_safety import verify_postgres_connection
        engine = create_async_engine(harness.config.database.postgres_url, poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                await verify_postgres_connection(connection, harness.config.database)
                await connection.execute(text("DELETE FROM suggestions WHERE id = :id"), {"id": parent})
        finally:
            await engine.dispose()
    asyncio.run(remove())


def execute_resilience(harness, scenario: ResilienceScenario):
    directory = harness.app.overrides.get("E2E_FAULT_DIR")
    if not directory or not harness.app.factory:
        raise RuntimeError("Resilience requires the test-only instrumented subprocess factory")
    controller = harness.fault_controller or FaultController(directory)
    harness.fault_controller = controller
    controller.release_all()
    controller.install([])
    try:
        handler = globals()["_execute_" + scenario.action]
        return handler(harness, scenario, controller)
    finally:
        original_error = sys.exc_info()[1]
        # Contexts have unwound; release exact gates, recover/settle the owned
        # host, and preserve the active epoch before installing a clean schedule.
        controller.release_all()
        try:
            if not harness.app.running:
                harness.app.start()
            harness.settle_requests()
            _record(harness, scenario, controller, sorted(harness.registered_ids), label="final")
        except Exception as capture_error:
            try:
                controller.record("final_capture_failed", case_id=scenario.case_id, variant_id=scenario.variant_id,
                                  error_type=type(capture_error).__name__)
            except Exception:
                # A failed evidence sink must not replace the product assertion.
                pass
            if original_error is not None:
                original_error.add_note(f"Final fault/state capture failed: {type(capture_error).__name__}")
            else:
                raise
        finally:
            controller.install([])


def _execute_early(h, s, c):
    parent, before, request = _prepare(h, s.method)
    p = s.parameters
    _fault(c, parent, request, operation=p["operation"], error=p["error"], action="zero" if p.get("zero") else "raise")
    response = _request(h, s.method, parent, request)
    _record(h, s, c, [parent])
    c.assert_triggered()
    _status(response, p["status"])
    if p["error"] == "normalizer":
        error = response.json()["errors"][0]
        assert error["code"] == "TEXT_NORMALIZATION_FAILED" and error["source"]["pointer"] == "/data"
    _unchanged(before, h.snapshot(parent))


def _execute_ingest_sql(h, s, c):
    parent, before, request = _prepare(h, "POST")
    p = s.parameters
    _fault(c, parent, request, operation=p["operation"], timing=p.get("timing", "before"), error="runtime")
    response = _request(h, "POST", parent, request)
    _record(h, s, c, [parent])
    c.assert_triggered()
    _status(response, 500)
    after = h.snapshot(parent)
    if p.get("timing") == "after":
        assert after["sql"] and after["sql"]["version"] == 1
        assert not after["points"]
        assert not c.events(epoch=c._schedule()["epoch"], operation="vector.purge")
    else:
        _unchanged(before, after)


def _execute_ingest_vector(h, s, c):
    parent, _, request = _prepare(h, "POST")
    _fault(c, parent, request, operation=s.parameters["operation"], timing=s.parameters.get("timing", "before"))
    response = _request(h, "POST", parent, request)
    _record(h, s, c, [parent])
    c.assert_triggered()
    _status(response, 500)
    after = h.snapshot(parent)
    assert after["sql"] is None and not after["points"], "Compensated ingest left persisted data"


def _execute_ingest_compensation(h, s, c):
    parent, _, request = _prepare(h, "POST")
    rules = [_rule("primary", "vector.promote", parent, request, error="vector")]
    if s.parameters.get("vector_cleanup"):
        rules.append(_rule("vector_cleanup", "vector.purge", parent, request, attempt=2, error="vector"))
    if s.parameters.get("sql_cleanup"):
        rules.append(_rule("sql_cleanup", "sql.delete", parent, request, error="runtime"))
    c.install(rules)
    response = _request(h, "POST", parent, request)
    _record(h, s, c, [parent])
    c.assert_triggered()
    _status(response, 500)
    after = h.snapshot(parent)
    if s.parameters.get("sql_cleanup") and s.parameters.get("vector_cleanup"):
        assert after["sql"] is None and not after["points"], "Both ingestion compensations failed; residual SQL/vector state requires recovery"
        return
    assert (after["sql"] is not None) == bool(s.parameters.get("sql_cleanup"))
    assert bool(after["points"]) == bool(s.parameters.get("vector_cleanup"))
    if s.parameters.get("vector_cleanup"):
        assert all(point["payload"]["chunk_status"] == "staging" for point in after["points"])


def _execute_ingest_slice(h, s, c):
    parent, _, request = _prepare(h, "POST")
    p = s.parameters
    with _overrides(h, {"QDRANT_BATCH_SIZE": 2} if p.get("later") else {}):
        first = 2 if p.get("later") else 1
        attempts = [first, first + 1] if p.get("recover") else [first, first + 1, first + 2] if p.get("transient") else first
        _fault(c, parent, request, operation="qdrant.upsert", attempt=attempts, error="connection" if p.get("transient") else "runtime")
        epoch = c._schedule()["epoch"]
        response = _request(h, "POST", parent, request)
        _record(h, s, c, [parent])
        c.assert_triggered()
        if p.get("recover"):
            _status(response, 201)
            h.assert_consistent(parent, expected_version=1, chunks_count=response.json()["data"]["chunksCount"])
            assert c.events(epoch=epoch, request_id=request, operation="qdrant.upsert", timing="after", applied=True)
        else:
            _status(response, 500)
            after = h.snapshot(parent)
            assert after["sql"] is None and not after["points"]
        if p.get("later"):
            assert c.events(epoch=epoch, request_id=request, operation="qdrant.upsert", timing="after", attempt=1, applied=True), "Earlier slice never applied"


def _execute_mutation_slice(h, s, c):
    parent, before, request = _prepare(h, s.method)
    p = s.parameters
    with _overrides(h, {"QDRANT_BATCH_SIZE": 2} if p.get("later") else {}):
        rules = [_rule("upsert", "qdrant.upsert", parent, request, attempt=2 if p.get("later") else 1,
                       timing="after" if p.get("applied") else "before", error="runtime")]
        if p.get("cleanup_failure"):
            rules.append(_rule("cleanup", "vector.delete_ids", parent, request, error="vector"))
        c.install(rules)
        response = _request(h, s.method, parent, request)
        _record(h, s, c, [parent])
        c.assert_triggered()
        _status(response, 500)
        after = h.snapshot(parent)
        _unchanged(before["sql"], after["sql"])
        old_ids = {point["id"] for point in before["points"]}
        old_after = [point for point in after["points"] if point["id"] in old_ids]
        _unchanged(before["points"], old_after)
        if p.get("cleanup_failure"):
            assert any(point["payload"]["chunk_status"] == "staging" for point in after["points"])
        else:
            _unchanged(before, after)


def _execute_mutation_sql(h, s, c):
    parent, before, request = _prepare(h, s.method)
    p = s.parameters
    rules = [_rule("sql", p["operation"], parent, request, timing=p.get("timing", "before"), error="runtime")]
    if p.get("cleanup_failure"):
        rules.append(_rule("cleanup", "vector.delete_ids", parent, request, error="vector"))
    c.install(rules)
    response = _request(h, s.method, parent, request)
    _record(h, s, c, [parent])
    c.assert_triggered()
    _status(response, 500)
    after = h.snapshot(parent)
    if p.get("timing") == "after":
        assert after["sql"]["version"] == 2
        _unchanged(before["points"], after["points"])
    elif p.get("cleanup_failure"):
        _unchanged(before["sql"], after["sql"])
        assert len(after["points"]) > len(before["points"])
    else:
        _unchanged(before, after)


def _execute_cutover(h, s, c):
    parent, _, request = _prepare(h, s.method)
    p = s.parameters
    _fault(c, parent, request, operation=p["operation"], timing=p.get("timing", "before"), attempt=p["attempt"])
    response = _request(h, s.method, parent, request)
    _record(h, s, c, [parent])
    c.assert_triggered()
    _status(response, 500 if p.get("exhausted") else 200)
    assert h.snapshot(parent)["sql"]["version"] == 2
    if p.get("exhausted"):
        assert any(point["payload"]["chunk_status"] == "staging" for point in h.snapshot(parent)["points"])
        before_restart = h.snapshot(parent)
        h.restart_app()
        _unchanged(before_restart, h.snapshot(parent))
    else:
        # In particular, MUT-F10 must fail when successful promotion is
        # repeated after a purge failure and its replacement becomes deprecated.
        h.assert_consistent(parent, expected_version=2, expected_deleted=False,
                            chunks_count=response.json()["data"]["chunksCount"])


def _execute_lock(h, s, c):
    parent, before, request = _prepare(h, s.method)
    with HeldAdvisoryLock(h, [parent]):
        response = _request(h, s.method, parent, request)
        _record(h, s, c, [parent], label="lock_held")
        _status(response, 409)
        _unchanged(before, h.snapshot(parent))
    response = _request(h, s.method, parent, uuid.uuid4().hex)
    _status(response, 200)
    h.assert_consistent(parent, expected_version=2, expected_deleted=s.method == "DELETE")


def _execute_delete_sql(h, s, c):
    parent, before, request = _prepare(h, "DELETE")
    p = s.parameters
    _fault(c, parent, request, operation=p["operation"], timing=p.get("timing", "before"), error="runtime")
    response = _request(h, "DELETE", parent, request)
    _record(h, s, c, [parent])
    c.assert_triggered()
    _status(response, 500)
    if p.get("timing") == "after":
        after = h.snapshot(parent)
        assert after["sql"]["is_deleted"] and after["sql"]["version"] == 2
        _unchanged(before["points"], after["points"])
    else:
        _unchanged(before, h.snapshot(parent))


def _execute_delete_vector(h, s, c):
    parent, before, request = _prepare(h, "DELETE")
    p = s.parameters
    rules = [_rule("purge", "vector.purge", parent, request, timing=p.get("timing", "before"), error="vector")]
    if p.get("cleanup_failure"):
        rules.append(_rule("compensation", "sql.save", parent, request, error="runtime"))
    c.install(rules)
    response = _request(h, "DELETE", parent, request)
    _record(h, s, c, [parent])
    c.assert_triggered()
    _status(response, 500)
    after = h.snapshot(parent)
    if p.get("cleanup_failure"):
        assert after["sql"]["is_deleted"] and after["sql"]["version"] == 2
        _unchanged(before["points"], after["points"])
    else:
        assert not after["sql"]["is_deleted"] and after["sql"]["version"] == 3
        if p.get("timing") != "after":
            _unchanged(before["points"], after["points"])
        # DEL-10 records actual applied purge before asserting the restoration
        # invariant. An active SQL row without vectors is a product defect.
        h.assert_consistent(parent, expected_version=3, expected_deleted=False)


def _execute_race_ingest(h, s, c):
    parent = h.new_id("duplicate")
    a, b = uuid.uuid4().hex, uuid.uuid4().hex
    rules = [_rule("A_read", "sql.read", parent, a, timing="after", action="barrier"),
             _rule("B_read", "sql.read", parent, b, timing="after", action="barrier")]
    if s.parameters.get("fail_second"):
        rules.append(_rule("B_fail", "vector.upsert", parent, b, error="vector"))
    epoch = c.install(rules)
    with ThreadPoolExecutor(max_workers=2) as executor:
        fa = executor.submit(_request, h, "POST", parent, a, "برنده اول")
        fb = executor.submit(_request, h, "POST", parent, b, "رقیب دوم")
        try:
            a_read, b_read = _barrier(c, "A_read", epoch), _barrier(c, "B_read", epoch)
            assert a_read["found"] is False and b_read["found"] is False
            c.release("A_read")
            ra = fa.result(timeout=h.config.request_timeout)
            _status(ra, 201)
            h.assert_consistent(parent, expected_version=1, chunks_count=ra.json()["data"]["chunksCount"])
            accepted = h.snapshot(parent)
            _record(h, s, c, [parent], label="accepted_first")
            c.release("B_read")
            rb = fb.result(timeout=h.config.request_timeout)
            _record(h, s, c, [parent])
            c.assert_triggered()
            if s.parameters.get("fail_second"):
                _status(rb, 500)
                _unchanged(accepted, h.snapshot(parent))
            else:
                assert rb.status_code == 409, f"Both duplicate checks accepted creation: {ra.status_code}, {rb.status_code}"
                _unchanged(accepted, h.snapshot(parent))
        finally:
            c.release_all()


def _execute_race_stale(h, s, c):
    parent = _seed(h, "stale")
    a, b = uuid.uuid4().hex, uuid.uuid4().hex
    phase = s.parameters.get("hold_phase", "sql.read")
    epoch = c.install([_rule("A_hold", phase, parent, a, timing="after", action="barrier")])
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_request, h, s.method, parent, a, "بازنده کهنه")
        try:
            event = _barrier(c, "A_hold", epoch)
            if phase == "sql.read":
                assert event["version"] == 1
            winner = _request(h, s.parameters.get("second_method", s.method), parent, b, "برنده جدید")
            _status(winner, 200)
            accepted = h.snapshot(parent)
            _record(h, s, c, [parent], label="winner_before_stale_release")
            c.release("A_hold")
            rejected = future.result(timeout=h.config.request_timeout)
            _record(h, s, c, [parent])
            c.assert_triggered()
            _status(rejected, 409)
            _unchanged(accepted, h.snapshot(parent))
            h.assert_consistent(parent, expected_version=2)
        finally:
            c.release_all()


def _execute_race_cutover(h, s, c):
    parent = _seed(h, "cutover")
    a, b = uuid.uuid4().hex, uuid.uuid4().hex
    epoch = c.install([_rule("A_committed", "sql.commit", parent, a, timing="after", action="barrier")])
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_request, h, "PUT", parent, a, "نسخه قدیمی")
        try:
            event = _barrier(c, "A_committed", epoch)
            assert event["applied"]
            assert h.snapshot(parent)["sql"]["version"] == 2
            newer = _request(h, "PUT", parent, b, "نسخه جدید پذیرفته")
            _status(newer, 200)
            accepted = h.snapshot(parent)
            assert accepted["sql"]["version"] == 3
            _record(h, s, c, [parent], label="newer_accepted")
            c.release("A_committed")
            older = future.result(timeout=h.config.request_timeout)
            _status(older, 200)
            _record(h, s, c, [parent])
            c.assert_triggered()
            _unchanged(accepted, h.snapshot(parent))
            h.assert_consistent(parent, expected_version=3)
        finally:
            c.release_all()


def _execute_race_missing(h, s, c):
    parent = _seed(h, "removed")
    request = uuid.uuid4().hex
    epoch = c.install([_rule("initial_read", "sql.read", parent, request, timing="after", action="barrier")])
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_request, h, s.method, parent, request)
        try:
            _barrier(c, "initial_read", epoch)
            if s.parameters["state"] == "hard_deleted":
                _delete_sql_physically(h, parent)
                h.clear_parent_points(parent)
                expected = 404
            else:
                _status(_request(h, "DELETE", parent, uuid.uuid4().hex), 200)
                expected = 409
            state = h.snapshot(parent)
            c.release("initial_read")
            response = future.result(timeout=h.config.request_timeout)
            _record(h, s, c, [parent])
            c.assert_triggered()
            _status(response, expected)
            _unchanged(state, h.snapshot(parent))
        finally:
            c.release_all()


def _execute_race_delete_update(h, s, c):
    parent = _seed(h, "delete-update")
    a, b = uuid.uuid4().hex, uuid.uuid4().hex
    p = s.parameters
    update_first = p["direction"] == "update_first"
    first_method, second_method = ("PUT", "DELETE") if update_first else ("DELETE", "PUT")
    phase = p["hold_phase"]
    timing = "before" if phase == "vector.purge" else "after"
    epoch = c.install([_rule("first_hold", phase, parent, a, action="barrier", timing=timing)])
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_request, h, first_method, parent, a, "ابتدا")
        try:
            _barrier(c, "first_hold", epoch)
            second = _request(h, second_method, parent, b, "بازسازی پذیرفته")
            _status(second, 200)
            accepted = h.snapshot(parent)
            _record(h, s, c, [parent], label="second_accepted")
            c.release("first_hold")
            first = future.result(timeout=h.config.request_timeout)
            _record(h, s, c, [parent])
            c.assert_triggered()
            _status(first, 409 if update_first and phase == "vector.upsert" else 200)
            _unchanged(accepted, h.snapshot(parent))
            h.assert_consistent(parent)
        finally:
            c.release_all()


def _execute_race_delete(h, s, c):
    parent = _seed(h, "two-deletes")
    a, b = uuid.uuid4().hex, uuid.uuid4().hex
    epoch = c.install([_rule("hold_lock", "sql.soft_delete", parent, a, action="barrier", timing="after")])
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_request, h, "DELETE", parent, a)
        try:
            _barrier(c, "hold_lock", epoch)
            contender = _request(h, "DELETE", parent, b)
            _status(contender, 409)
            c.release("hold_lock")
            _status(future.result(timeout=h.config.request_timeout), 200)
            accepted = h.snapshot(parent)
            _status(_request(h, "DELETE", parent, uuid.uuid4().hex), 200)
            _record(h, s, c, [parent])
            c.assert_triggered()
            _unchanged(accepted, h.snapshot(parent))
            h.assert_consistent(parent, expected_version=2, expected_deleted=True)
        finally:
            c.release_all()


def _execute_race_ingest_mutation(h, s, c):
    parent = h.new_id("ingest-race")
    a, b = uuid.uuid4().hex, uuid.uuid4().hex
    epoch = c.install([_rule("ingest_committed", "sql.commit", parent, a, timing="after", action="barrier")])
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_request, h, "POST", parent, a, "ایجاد قدیمی")
        try:
            _barrier(c, "ingest_committed", epoch)
            second = _request(h, s.parameters["second_method"], parent, b, "تغییر پذیرفته جدید")
            _status(second, 200)
            accepted = h.snapshot(parent)
            _record(h, s, c, [parent], label="competing_mutation_accepted")
            c.release("ingest_committed")
            _status(future.result(timeout=h.config.request_timeout), 201)
            _record(h, s, c, [parent])
            c.assert_triggered()
            _unchanged(accepted, h.snapshot(parent))
            h.assert_consistent(parent)
        finally:
            c.release_all()


def _execute_race_compensation(h, s, c):
    parent = _seed(h, "compensation")
    deletion, winner = uuid.uuid4().hex, uuid.uuid4().hex
    rules = [_rule("purge_wait", "vector.purge", parent, deletion, action="barrier"),
             _rule("purge_fail", "vector.purge", parent, deletion, error="vector"),
             _rule("winner_uncommitted", "sql.save", parent, winner, timing="after", action="barrier"),
             _rule("stale_restore", "sql.save", parent, deletion, action="barrier")]
    epoch = c.install(rules)
    with ThreadPoolExecutor(max_workers=2) as executor:
        fd = executor.submit(_request, h, "DELETE", parent, deletion)
        fw = None
        try:
            _barrier(c, "purge_wait", epoch)  # SQL deleted and lock released.
            fw = executor.submit(_request, h, "PUT", parent, winner, "برنده غیرقابل حذف")
            _barrier(c, "winner_uncommitted", epoch)  # Actual row write and advisory lock held.
            c.release("purge_wait")
            _barrier(c, "stale_restore", epoch)  # Compensation read the previous committed row.
            locks = c.events(epoch=epoch, request_id=deletion, operation="sql.lock", timing="after")
            assert locks[-1]["lock_acquired"] is False, "Compensation lock-denial path was not reached"
            c.release("winner_uncommitted")
            _status(fw.result(timeout=h.config.request_timeout), 200)
            accepted = h.snapshot(parent)
            _record(h, s, c, [parent], label="winner_accepted")
            c.release("stale_restore")
            _status(fd.result(timeout=h.config.request_timeout), 500)
            _record(h, s, c, [parent])
            c.assert_triggered()
            _unchanged(accepted, h.snapshot(parent))
            h.assert_consistent(parent)
        finally:
            c.release_all()


def _execute_compensation_lock(h, s, c):
    parent = _seed(h, "restore-lock")
    request = uuid.uuid4().hex
    epoch = c.install([_rule("purge_hold", "vector.purge", parent, request, action="barrier"),
                       _rule("purge_fail", "vector.purge", parent, request, error="vector")])
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_request, h, "DELETE", parent, request)
        try:
            _barrier(c, "purge_hold", epoch)
            with HeldAdvisoryLock(h, [parent]):
                c.release("purge_hold")
                _status(future.result(timeout=h.config.request_timeout), 500)
                _record(h, s, c, [parent])
                locks = c.events(epoch=epoch, request_id=request, operation="sql.lock", timing="after")
                assert locks[-1]["lock_acquired"] is False
                c.assert_triggered()
                restores = c.events(epoch=epoch, request_id=request, operation="sql.save", timing="after")
                assert not restores, "Compensation wrote SQL after its advisory lock was denied"
        finally:
            c.release_all()


def _execute_blackout(h, s, c):
    parent = _seed(h, "blackout")
    request = uuid.uuid4().hex
    epoch = c.install([_rule("between_payloads", "qdrant.promote", parent, request, action="barrier")])
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_request, h, s.method, parent, request)
        try:
            _barrier(c, "between_payloads", epoch)
            intermediate = h.snapshot(parent)
            _record(h, s, c, [parent], label="between_payloads")
            c.release("between_payloads")
            _status(future.result(timeout=h.config.request_timeout), 200)
            _record(h, s, c, [parent])
            c.assert_triggered()
            h.assert_consistent(parent, expected_version=2)
            # Availability is characterized separately; the checklist explicitly
            # leaves a contractual availability guarantee undecided.
            c.record("availability_characterization", parent_id=parent,
                     active_count=sum(point["payload"].get("chunk_status") == "active" for point in intermediate["points"]),
                     contract_gap="two payload operations permit a temporary blackout; no SLA specified")
        finally:
            c.release_all()


def _execute_crash(h, s, c):
    method = "POST" if s.parameters["workflow"] == "ingest" else "DELETE" if s.parameters["workflow"] == "delete" else s.method
    parent, original, request = _prepare(h, method)
    p = s.parameters
    action = "cancel" if p.get("cancel") else "barrier"
    epoch = c.install([_rule("interrupt", p["phase"], parent, request, action=action, timing=p["timing"])])
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_request, h, method, parent, request)
        try:
            if not p.get("cancel"):
                _barrier(c, "interrupt", epoch)
                _record(h, s, c, [parent], label="before_kill")
                h.app.kill()
                c.release_all()
            try:
                response = future.result(timeout=h.config.request_timeout)
                assert response.status_code >= 500, response.text
            except Exception as error:
                # A process kill/disconnected cancellation is expected transport
                # evidence; an assertion error is not swallowed.
                import httpx
                if not isinstance(error, (httpx.TransportError, RuntimeError)):
                    raise
                c.record("interrupted_http", request_id=request, error_type=type(error).__name__)
            _record(h, s, c, [parent], label="interrupted_before_restart")
            state = h.snapshot(parent)
            abandoned_ids = {point["id"] for point in state["points"]} - {point["id"] for point in original["points"]}
            c.assert_triggered()
            c.install([])
            h.restart_app() if h.app.running else h.app.start()
            _unchanged(state, h.snapshot(parent))
            if method == "POST":
                _status(_request(h, "POST", parent, uuid.uuid4().hex), 409)
                # A duplicate retry cannot repair a SQL-only/staging ingestion.
                h.assert_consistent(parent)
            elif method == "DELETE":
                _status(_request(h, "DELETE", parent, uuid.uuid4().hex), 200)
                h.assert_consistent(parent, expected_deleted=True)
            else:
                # Preserve evidence before retrying, then ensure a fresh PUT
                # actually establishes a coherent latest state.
                response = _request(h, "PUT", parent, uuid.uuid4().hex, "پس از راه‌اندازی")
                _status(response, 200)
                h.assert_consistent(parent, expected_version=response.json()["data"]["version"],
                                    chunks_count=response.json()["data"]["chunksCount"])
                assert not abandoned_ids.intersection(point["id"] for point in h.snapshot(parent)["points"]), "Retry retained interrupted operation points"
        finally:
            c.release_all()


def _execute_retry_ingest(h, s, c):
    parent, _, request = _prepare(h, "POST")
    rules = [_rule("primary", "vector.promote", parent, request, error="vector")]
    if s.parameters["orphan"]:
        rules.append(_rule("orphan", "vector.purge", parent, request, attempt=2, error="vector"))
    c.install(rules)
    _status(_request(h, "POST", parent, request), 500)
    failed = h.snapshot(parent)
    abandoned = {point["id"] for point in failed["points"]}
    assert failed["sql"] is None
    _record(h, s, c, [parent], label="before_retry")
    c.assert_triggered()
    c.install([])
    recovered = _request(h, "POST", parent, uuid.uuid4().hex)
    _status(recovered, 201)
    _record(h, s, c, [parent])
    h.assert_consistent(parent, expected_version=1, chunks_count=recovered.json()["data"]["chunksCount"])
    assert not abandoned.intersection(point["id"] for point in h.snapshot(parent)["points"])


def _execute_retry_mutation(h, s, c):
    parent = _seed(h, "retry")
    request = uuid.uuid4().hex
    _fault(c, parent, request, operation="vector.promote", attempt=[1, 2, 3])
    _status(_request(h, s.method, parent, request), 500)
    failed = h.snapshot(parent)
    abandoned = {point["id"] for point in failed["points"] if point["payload"].get("chunk_status") == "staging"}
    assert failed["sql"]["version"] == 2
    _record(h, s, c, [parent], label="before_retry")
    c.assert_triggered()
    c.install([])
    response = _request(h, s.method, parent, uuid.uuid4().hex)
    _status(response, 200)
    _record(h, s, c, [parent])
    h.assert_consistent(parent, expected_version=3, chunks_count=response.json()["data"]["chunksCount"])
    assert not abandoned.intersection(point["id"] for point in h.snapshot(parent)["points"]), "Retry retained failed update's points"


def _execute_orphan_early(h, s, c):
    parent = _seed(h, "orphan")
    _delete_sql_physically(h, parent)
    before = h.snapshot(parent)
    assert before["sql"] is None and before["points"]
    request = uuid.uuid4().hex
    _fault(c, parent, request, operation="sparse.embed", error="sparse")
    _status(_request(h, "POST", parent, request), 500)
    _record(h, s, c, [parent])
    c.assert_triggered()
    _unchanged(before, h.snapshot(parent))


def _execute_sql_only_conflict(h, s, c):
    parent = _seed(h, "sql-only")
    h.clear_parent_points(parent)
    before = h.snapshot(parent)
    _status(_request(h, "POST", parent, uuid.uuid4().hex), 409)
    _record(h, s, c, [parent])
    _unchanged(before, h.snapshot(parent))


def _embedding_route(h):
    environment = h.config.application_environment()
    provider = environment.get("EMBEDDING_PROVIDER", "tei").lower()
    prefix = "TEI" if provider == "tei" else "VLLM"
    host = environment.get(prefix + "_HOST", "localhost")
    port = environment.get(prefix + "_PORT", "8080" if prefix == "TEI" else "8000")
    return prefix, f"http://{host}:{port}"


def _provider_rules(fault):
    if fault == "reset":
        return [FaultRule("provider_reset", "http.embedding", action="reset", attempt=None)]
    if fault == "timeout":
        return [FaultRule("provider_timeout", "http.embedding", action="barrier", barrier_timeout=10, attempt=1)]
    if fault in {"missing", "extra", "reordered", "duplicate_indices", "missing_indices", "wrong_dimension", "nonfinite", "decoding"}:
        return [FaultRule("provider_shape", "http.embedding", action="response", timing="after", attempt=None,
                          status=200, response={"__transform__": fault})]
    if fault == "unreachable":
        return []
    status = 429 if fault.startswith("429") else 400 if fault in {"unknown_model", "context_limit"} else int(fault)
    message = "Unknown model" if fault == "unknown_model" else "Context length exceeded" if fault == "context_limit" else "Controlled provider rejection"
    return [FaultRule("provider_rejection", "http.embedding", action="reject", attempt=None,
                      status=status, response={"error": {"message": message, "type": "invalid_request_error" if status == 400 else "api_error",
                                                          "code": "model_not_found" if fault == "unknown_model" else "context_length_exceeded" if fault == "context_limit" else "controlled_error"}},
                      response_headers={"Retry-After": "0.05"} if fault == "429_retry" else None)]


def _execute_provider(h, s, c):
    import math
    parent, before, request = _prepare(h, s.method)
    fault = s.parameters["fault"]
    prefix, upstream = _embedding_route(h)
    if fault == "unreachable":
        from .infrastructure import free_port
        upstream = f"http://127.0.0.1:{free_port()}"
    with ForwardingProxy(upstream, c, provider="embedding", upstream_timeout=h.config.request_timeout) as proxy:
        overrides = {prefix + "_HOST": "127.0.0.1", prefix + "_PORT": str(urlsplit(proxy.url).port)}
        if fault == "unreachable":
            # A refused provider connection must reach the SDK as a connection
            # error, rather than an invented 502 gateway HTTP response.
            unavailable_port = free_port()
            overrides[prefix + "_PORT"] = str(unavailable_port)
            c.record("provider_unreachable_target", host="127.0.0.1", port=unavailable_port)
        if fault == "timeout":
            overrides.update(MAX_RETRIES="0", EMBEDDING_TIMEOUT="0.2")
        with _overrides(h, overrides):
            epoch = c.install(_provider_rules(fault))
            if fault == "timeout":
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(_request, h, s.method, parent, request)
                    try:
                        _barrier(c, "provider_timeout", epoch)
                        response = future.result(timeout=h.config.request_timeout)
                    finally:
                        c.release_all()
            else:
                response = _request(h, s.method, parent, request)
            _record(h, s, c, [parent])
            c.assert_triggered()
            after = h.snapshot(parent)
            if fault == "reordered":
                _status(response, 201 if s.method == "POST" else 200)
                h.assert_consistent(parent, chunks_count=response.json()["data"]["chunksCount"])
                associations = c.events(kind="provider_association", epoch=epoch)
                assert associations, "Provider vector/index evidence was not recorded"
                input_vectors = {}
                for event in associations:
                    for item in event["vectors"]:
                        input_vectors[event["inputs"][item["index"]]] = item["vector"]
                document_prefix = h.config.application_environment().get("EMBEDDING_DOCUMENT_PREFIX", "")
                for point in after["points"]:
                    source = document_prefix + point["payload"]["content"]
                    expected = provider_vector_values(input_vectors[source])
                    norm = math.sqrt(sum(value * value for value in expected))
                    normalized = [value / norm for value in expected]
                    actual = point["vector"][h.config.dense_name]
                    assert len(actual) == len(normalized)
                    assert all(math.isclose(a, b, rel_tol=1e-5, abs_tol=2e-7) for a, b in zip(actual, normalized, strict=True)), "Reordered indices corrupted chunk/vector association"
            else:
                assert response.status_code >= 400, f"Malformed/unavailable provider falsely accepted: {fault}: {response.text}"
                if fault in {"unreachable", "reset", "timeout"}:
                    _status(response, 503)
                    assert response.json()["errors"][0]["code"] == "EMBEDDER_CONNECTION_FAILED"
                elif fault in {"401", "429_retry", "429_plain", "500", "unknown_model", "context_limit", "decoding"}:
                    _status(response, 500)
                    assert response.json()["errors"][0]["code"] == "EMBEDDING_FAILED"
                elif fault in {"missing", "extra"}:
                    _status(response, 500)
                    assert response.json()["errors"][0]["code"] == "INTERNAL_ERROR"
                elif fault in {"wrong_dimension", "nonfinite"}:
                    _status(response, 500)
                    assert response.json()["errors"][0]["code"] == "RETRIEVAL_FAILED"
                # Upstream failures occur before writes. Wrong dimensions can
                # reach Qdrant and then exercise real workflow compensation.
                _unchanged(before, after)
            _status(h.request("GET", "/health"), 200)


def _execute_malformed_sparse(h, s, c):
    parent, before, request = _prepare(h, s.method)
    c.install([_rule("invalid_sparse", "sparse.embed", parent, request, action="response", timing="after",
                     response={"__transform__": "malformed_sparse"})])
    response = _request(h, s.method, parent, request)
    _record(h, s, c, [parent])
    c.assert_triggered()
    assert response.status_code >= 400, "Malformed sparse indices/values produced a false success"
    _unchanged(before, h.snapshot(parent))


def _execute_alias(h, s, c):
    import httpx
    h.infrastructure.verify()
    parent = h.new_id("alias")
    database = h.config.database
    alias = h.config.alias
    collection = h.config.collection
    wrong = f"test_e2e_{h.config.run_id}_wrong_schema"
    with httpx.Client(base_url=database.qdrant_url, headers={"api-key": database.q_api_key}, trust_env=False, timeout=15) as client:
        response = client.get("/aliases")
        response.raise_for_status()
        aliases = response.json()["result"]["aliases"]
        actual = [item for item in aliases if item["alias_name"] == alias]
        assert len(actual) == 1 and actual[0]["collection_name"] == collection
        original = actual[0]
        created = False
        try:
            actions = [{"delete_alias": {"alias_name": alias}}]
            if s.parameters["alias_mode"] == "incompatible":
                response = client.put(f"/collections/{wrong}", json={"vectors": {h.config.dense_name: {"size": h.config.dense_dimension + 1, "distance": "Cosine"}},
                    "sparse_vectors": {h.config.sparse_name: {}}})
                response.raise_for_status()
                created = True
                c.record("alias_collection_created", epoch=c._schedule()["epoch"], parent_id=parent,
                         collection=wrong, owner_run_id=h.config.run_id, upstream_status=response.status_code,
                         acknowledged=response.json().get("result"))
                actions.append({"create_alias": {"collection_name": wrong, "alias_name": alias}})
            installed = client.post("/collections/aliases", json={"actions": actions})
            installed.raise_for_status()
            c.record("alias_fault_installed", epoch=c._schedule()["epoch"], parent_id=parent, alias=alias, expected_collection=collection,
                     actual_collection=wrong if created else None, upstream_status=installed.status_code,
                     acknowledged=installed.json().get("result"))
            response = _request(h, "POST", parent, uuid.uuid4().hex)
            c.record("alias_fault_response", epoch=c._schedule()["epoch"], parent_id=parent, alias=alias, status=response.status_code,
                     request_id=response.headers.get("X-Request-Id"))
            _status(response, 500)
        finally:
            restore = ([{"delete_alias": {"alias_name": alias}}] if created else [])
            restore.append({"create_alias": original})
            restored = client.post("/collections/aliases", json={"actions": restore})
            restored.raise_for_status()
            c.record("alias_restored", epoch=c._schedule()["epoch"], parent_id=parent, alias=alias, collection=collection, upstream_status=restored.status_code,
                     acknowledged=restored.json().get("result"))
            if created:
                # The unique collection is created by this exact scope after an
                # identity check; no inherited/source target can be deleted.
                removed = client.delete(f"/collections/{wrong}")
                removed.raise_for_status()
                c.record("alias_collection_deleted", epoch=c._schedule()["epoch"], parent_id=parent,
                         collection=wrong, owner_run_id=h.config.run_id, upstream_status=removed.status_code,
                         acknowledged=removed.json().get("result"))
    # The raw oracle deliberately requires the original guarded alias target.
    # Restore that identity before reading the physical collection and SQL.
    _record(h, s, c, [parent])
    assert h.snapshot(parent)["sql"] is None
    assert not h.snapshot(parent)["points"]
    _status(_request(h, "POST", parent, uuid.uuid4().hex), 201)
    h.assert_consistent(parent)


def _execute_delete_no_provider(h, s, c):
    parent = _seed(h, "no-embedding")
    prefix, upstream = _embedding_route(h)
    with ForwardingProxy(upstream, c, provider="embedding") as proxy:
        with _overrides(h, {prefix + "_HOST": "127.0.0.1", prefix + "_PORT": str(urlsplit(proxy.url).port)}):
            epoch = c.install([FaultRule("embedding_offline", "http.embedding", action="reset", attempt=None)])
            response = _request(h, "DELETE", parent, uuid.uuid4().hex)
            _record(h, s, c, [parent])
            _status(response, 200)
            assert not c.events(epoch=epoch, operation="http.embedding"), "DELETE invoked embeddings"
            h.assert_consistent(parent, expected_version=2, expected_deleted=True)


def _execute_delete_no_qdrant(h, s, c):
    parent = _seed(h, "no-qdrant")
    _status(_request(h, "DELETE", parent, uuid.uuid4().hex), 200)
    before = h.snapshot(parent)
    request = uuid.uuid4().hex
    _fault(c, parent, request, operation="vector.purge")
    response = _request(h, "DELETE", parent, request)
    _status(response, 200)
    _record(h, s, c, [parent])
    assert not c.events(kind="fault_matched", epoch=c._schedule()["epoch"]), "Deleted no-op incorrectly contacted Qdrant"
    _unchanged(before, h.snapshot(parent))
    h.assert_consistent(parent, expected_version=2, expected_deleted=True)


def _execute_independent(h, s, c):
    parents = [_seed(h, "independent") for _ in range(2)]
    requests = [uuid.uuid4().hex for _ in parents]
    correlation = [str(uuid.uuid4()) for _ in parents]
    epoch = c.install([_rule(f"hold{i}", "vector.upsert", parent, request, timing="after", action="barrier")
                       for i, (parent, request) in enumerate(zip(parents, requests, strict=True))])
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(h.request, "PUT", f"/api/v1/suggestions/{parent}", json=_body(parent, f"رقم {i}"),
                                   headers={**_headers(parent, request), "X-Request-Id": correlation[i]})
                   for i, (parent, request) in enumerate(zip(parents, requests, strict=True))]
        try:
            for i in range(2):
                _barrier(c, f"hold{i}", epoch)
            c.release_all()
            responses = [future.result(timeout=h.config.request_timeout) for future in futures]
            _record(h, s, c, parents)
            c.assert_triggered()
            for i, response in enumerate(responses):
                _status(response, 200)
                assert response.headers.get("X-Request-Id") == correlation[i], "Concurrent request IDs crossed responses"
                h.assert_consistent(parents[i], expected_version=2)
            assert not {point["id"] for point in h.snapshot(parents[0])["points"]}.intersection(point["id"] for point in h.snapshot(parents[1])["points"])
        finally:
            c.release_all()


def _execute_slow_embeddings(h, s, c):
    parents = [_seed(h, "slow") for _ in range(3)]
    requests = [uuid.uuid4().hex for _ in parents]
    unrelated_delete = _seed(h, "fast-delete")
    unrelated_ingest = h.new_id("fast-ingest")
    epoch = c.install([_rule(f"slow{i}", "sparse.embed", parent, request, action="barrier")
                       for i, (parent, request) in enumerate(zip(parents, requests, strict=True))])
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(_request, h, "PUT", parent, request) for parent, request in zip(parents, requests, strict=True)]
        try:
            for i in range(3):
                _barrier(c, f"slow{i}", epoch)
            start = time.monotonic()
            _status(h.request("GET", "/health"), 200)
            _status(_request(h, "DELETE", unrelated_delete, uuid.uuid4().hex), 200)
            _status(_request(h, "POST", unrelated_ingest, uuid.uuid4().hex), 201)
            c.record("latency", workload="unrelated_ingest_delete_during_three_held_embeddings", elapsed=time.monotonic() - start,
                     sla="none specified")
            c.release_all()
            for future in futures:
                _status(future.result(timeout=h.config.request_timeout), 200)
            _record(h, s, c, [*parents, unrelated_delete, unrelated_ingest])
            c.assert_triggered()
            for parent in parents:
                h.assert_consistent(parent, expected_version=2)
            h.assert_consistent(unrelated_delete, expected_deleted=True)
            h.assert_consistent(unrelated_ingest, expected_version=1)
        finally:
            c.release_all()


def _execute_restart(h, s, c):
    active, deleted = _seed(h, "persistent"), _seed(h, "persistent-deleted")
    _status(_request(h, "PATCH", active, uuid.uuid4().hex), 200)
    _status(_request(h, "DELETE", deleted, uuid.uuid4().hex), 200)
    before = {parent: h.snapshot(parent) for parent in (active, deleted)}
    h.restart_app()
    after = {parent: h.snapshot(parent) for parent in (active, deleted)}
    _unchanged(before, after)
    _status(_request(h, "PATCH", active, uuid.uuid4().hex), 200)
    _status(_request(h, "PUT", deleted, uuid.uuid4().hex), 200)
    _record(h, s, c, [active, deleted])
    h.assert_consistent(active, expected_version=3)
    h.assert_consistent(deleted, expected_version=3, expected_deleted=False)


def _bulk(h, parents, request):
    return h.request("POST", "/api/v1/suggestions/bulk-delete", json={"suggestionIds": parents},
                     headers={"X-E2E-Operation-Id": request})


def _bulk_assert_results(response, parents, failed, fault):
    _status(response, 400 if len(failed) == len(parents) else 207 if failed else 200)
    value = response.json()
    successes = [item["suggestionId"] for item in value.get("data", [])]
    assert successes == [parent for i, parent in enumerate(parents) if i not in failed]
    errors = value.get("errors", [])
    assert len(errors) == len(failed)
    expected = {"lock": (409, "SUGGESTION_IN_PROCESSING"), "vector": (400, "DOMAIN_ERROR"),
                "sql": (400, "INTERNAL_ERROR")}
    status, code = expected[fault]
    for error, index in zip(errors, sorted(failed), strict=True):
        assert str(error["status"]) == str(status)
        assert error["code"] == code
        assert error["source"]["pointer"] == f"/data/suggestionIds/{index}"


def _execute_bulk_fault(h, s, c):
    parents = [_seed(h, "bulk-fault") for _ in range(3)]
    before = {parent: h.snapshot(parent) for parent in parents}
    p = s.parameters
    indexes = {0, 1, 2} if p.get("all_items") else {{"first": 0, "middle": 1, "last": 2}[p.get("position", "middle")]}
    request = uuid.uuid4().hex
    fault = p["fault"]
    if fault == "lock":
        with HeldAdvisoryLock(h, [parents[index] for index in indexes]):
            response = _bulk(h, parents, request)
            _record(h, s, c, parents)
    else:
        operation = "vector.purge" if fault == "vector" else "sql.read"
        epoch = c.install([_rule(f"failure{index}", operation, parents[index], request,
                                error="vector" if fault == "vector" else "runtime") for index in indexes])
        response = _bulk(h, parents, request)
        _record(h, s, c, parents)
        c.assert_triggered()
    _bulk_assert_results(response, parents, indexes, fault)
    for index, parent in enumerate(parents):
        if index not in indexes:
            h.assert_consistent(parent, expected_version=2, expected_deleted=True)
        elif fault == "vector":
            h.assert_consistent(parent, expected_version=3, expected_deleted=False)
            _unchanged(before[parent]["points"], h.snapshot(parent)["points"])
        else:
            _unchanged(before[parent], h.snapshot(parent))


def _execute_bulk_mixed(h, s, c):
    parents = [h.new_id("bulk-missing"), _seed(h, "bulk-lock"), _seed(h, "bulk-domain"), _seed(h, "bulk-success")]
    request = uuid.uuid4().hex
    c.install([_rule("domain", "vector.purge", parents[2], request, error="vector")])
    with HeldAdvisoryLock(h, [parents[1]]):
        response = _bulk(h, parents, request)
        _record(h, s, c, parents)
    c.assert_triggered()
    _status(response, 207)
    value = response.json()
    assert [item["suggestionId"] for item in value["data"]] == [parents[3]]
    assert [item["code"] for item in value["errors"]] == ["SUGGESTION_NOT_FOUND", "SUGGESTION_IN_PROCESSING", "DOMAIN_ERROR"]
    assert [item["source"]["pointer"] for item in value["errors"]] == [f"/data/suggestionIds/{i}" for i in range(3)]
    h.assert_consistent(parents[0], require_exists=False)
    h.assert_consistent(parents[1], expected_version=1, expected_deleted=False)
    h.assert_consistent(parents[2], expected_version=3, expected_deleted=False)
    h.assert_consistent(parents[3], expected_version=2, expected_deleted=True)


def _execute_bulk_crash(h, s, c):
    import httpx
    parents = [_seed(h, "bulk-crash") for _ in range(3)]
    request = uuid.uuid4().hex
    epoch = c.install([_rule("first_complete", "vector.purge", parents[0], request, timing="after", action="barrier")])
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_bulk, h, parents, request)
        try:
            _barrier(c, "first_complete", epoch)
            h.assert_consistent(parents[0], expected_version=2, expected_deleted=True)
            for parent in parents[1:]:
                h.assert_consistent(parent, expected_version=1, expected_deleted=False)
            _record(h, s, c, parents, label="before_kill")
            h.app.kill()
            c.release_all()
            try:
                future.result(timeout=h.config.request_timeout)
            except httpx.TransportError as error:
                c.record("bulk_interrupted_http", request_id=request, error_type=type(error).__name__)
            before = {parent: h.snapshot(parent) for parent in parents}
            _record(h, s, c, parents, label="before_restart")
            c.assert_triggered()
            c.install([])
            h.app.start()
            _unchanged(before, {parent: h.snapshot(parent) for parent in parents})
            _status(_bulk(h, parents, uuid.uuid4().hex), 200)
            for parent in parents:
                h.assert_consistent(parent, expected_version=2, expected_deleted=True)
        finally:
            c.release_all()


def _execute_race_bulk(h, s, c):
    parents = [_seed(h, "bulk-overlap") for _ in range(3)]
    a, b = uuid.uuid4().hex, uuid.uuid4().hex
    epoch = c.install([_rule("first_bulk_complete", "vector.purge", parents[0], a, timing="after", action="barrier")])
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_bulk, h, parents[:2], a)
        try:
            _barrier(c, "first_bulk_complete", epoch)
            if s.parameters["single"]:
                _status(_request(h, "DELETE", parents[1], b), 200)
            else:
                _status(_bulk(h, parents[1:], b), 200)
            c.release("first_bulk_complete")
            _status(future.result(timeout=h.config.request_timeout), 200)
            _record(h, s, c, parents)
            c.assert_triggered()
            for parent in parents[:2]:
                h.assert_consistent(parent, expected_version=2, expected_deleted=True)
            h.assert_consistent(parents[2], expected_version=1 if s.parameters["single"] else 2,
                                expected_deleted=not s.parameters["single"])
        finally:
            c.release_all()


def _execute_bulk_latency(h, s, c):
    parents = [_seed(h, "bulk100-fault") for _ in range(100)]
    request = uuid.uuid4().hex
    _fault(c, parents[49], request, operation="vector.purge")
    start = time.monotonic()
    response = _bulk(h, parents, request)
    c.record("latency", workload="exactly100_bulk_with_middle_vector_failure", elapsed=time.monotonic() - start, sla="none specified")
    _record(h, s, c, parents)
    c.assert_triggered()
    _bulk_assert_results(response, parents, {49}, "vector")
    for i, parent in enumerate(parents):
        h.assert_consistent(parent, expected_version=3 if i == 49 else 2, expected_deleted=i != 49)
    c.install([])
    fresh = _seed(h, "pool-recovered")
    _status(_request(h, "DELETE", fresh, uuid.uuid4().hex), 200)
    h.assert_consistent(fresh, expected_deleted=True)


def _observe_direct_http(h, s, *, method, path, headers, body, url, response=None,
                         transport_error=None, upstream=None):
    """Persist direct transports using the same sanitizer as ordinary requests."""
    return h.observe(f"{s.case_id}/{s.variant_id}:direct_http", {
        "request": {"method": method, "path": path, "url": url, "headers": headers, "json": body},
        "response": None if response is None else {
            "status": response.status_code, "headers": dict(response.headers), "body": response.content,
            "request_id": response.headers.get("X-Request-Id")},
        "transport_failure": transport_error,
        "upstream": upstream,
    })


def _execute_lost_http(h, s, c):
    import httpx
    bulk = s.parameters.get("bulk", False)
    parent, _, request = _prepare(h, "DELETE" if bulk else s.method)
    path = "/api/v1/suggestions/bulk-delete" if bulk else "/api/v1/suggestions/ingest" if s.method == "POST" else f"/api/v1/suggestions/{parent}"
    body = {"suggestionIds": [parent]} if bulk else None if s.method == "DELETE" else {"title": _body(parent)["title"]} if s.method == "PATCH" else _body(parent)
    with ForwardingProxy(h.base_url, c, provider="application") as proxy:
        epoch = c.install([_rule("lost_ack", "http.application", parent, request, timing="after", action="lose_response")])
        headers = {h.config.api_header: h.config.api_key, **_headers(parent, request)}
        wire = {"method": s.method, "path": path, "headers": headers, "body": body, "url": proxy.url + path}
        _observe_direct_http(h, s, **wire)
        with httpx.Client(base_url=proxy.url, timeout=h.config.request_timeout, trust_env=False) as client:
            try:
                client.request(s.method, path, json=body if body is not None else None,
                               headers=headers)
            except httpx.TransportError as error:
                c.record("lost_http_response", request_id=request, error_type=type(error).__name__)
                transport_error = {"error_type": type(error).__name__, "detail": str(error), "response_delivered": False}
            else:
                raise AssertionError("Lost application acknowledgement did not disconnect the client")
        applied = c.events(kind="upstream_outcome", epoch=epoch)
        _observe_direct_http(h, s, **wire, transport_error=transport_error,
                             upstream={"outcomes": applied, "responses": proxy.upstream_responses(request_id=request)})
        assert applied and applied[-1]["applied"] and applied[-1]["upstream_status"] in {200, 201}
        accepted = h.snapshot(parent)
        _record(h, s, c, [parent], label="applied_before_retry")
        c.assert_triggered()
        c.install([])
        retry = _bulk(h, [parent], uuid.uuid4().hex) if bulk else _request(h, s.method, parent, uuid.uuid4().hex, body=body)
        _record(h, s, c, [parent])
        if s.method == "POST" and not bulk:
            _status(retry, 409)
            _unchanged(accepted, h.snapshot(parent))
            h.assert_consistent(parent, expected_version=1)
        elif s.method in {"PUT", "PATCH"}:
            _status(retry, 200)
            h.assert_consistent(parent, expected_version=3)
        else:
            _status(retry, 200)
            _unchanged(accepted, h.snapshot(parent))
            h.assert_consistent(parent, expected_version=2, expected_deleted=True)


def _execute_host_liveness(h, s, c):
    prefix, upstream = _embedding_route(h)
    parent = h.new_id("liveness")
    with ForwardingProxy(upstream, c, provider="embedding") as proxy:
        with _overrides(h, {prefix + "_HOST": "127.0.0.1", prefix + "_PORT": str(urlsplit(proxy.url).port), "MAX_RETRIES": "0"}):
            c.install([FaultRule("offline", "http.embedding", action="reset", attempt=None)])
            response = h.request("GET", "/health")
            _status(response, 200)
            assert response.json()["status"] == "ok"
            failed = _request(h, "POST", parent, uuid.uuid4().hex)
            _status(failed, 503)
            assert failed.json()["errors"][0]["code"] == "EMBEDDER_CONNECTION_FAILED"
            _record(h, s, c, [parent], label="liveness_while_mutation_failed")
            c.assert_triggered()
            assert h.snapshot(parent)["sql"] is None and not h.snapshot(parent)["points"]
            c.install([])
            recovered = _request(h, "POST", parent, uuid.uuid4().hex)
            _status(recovered, 201)
            h.assert_consistent(parent, chunks_count=recovered.json()["data"]["chunksCount"])


def _execute_debug(h, s, c):
    parent = h.new_id("debug")
    request = uuid.uuid4().hex
    with _overrides(h, {"ENVIRONMENT": s.parameters["environment"]}):
        if s.parameters["category"] == "validation":
            response = h.request("POST", "/api/v1/suggestions/ingest", json={"suggestionId": parent}, headers=_headers(parent, request))
            _status(response, 422)
        else:
            # Real dense-provider failure is generated at the network boundary,
            # using a refused loopback upstream and the owned forwarding proxy.
            prefix, _ = _embedding_route(h)
            from .infrastructure import free_port
            with ForwardingProxy(f"http://127.0.0.1:{free_port()}", c, provider="embedding") as proxy:
                with _overrides(h, {"ENVIRONMENT": s.parameters["environment"], prefix + "_HOST": "127.0.0.1",
                                    prefix + "_PORT": str(urlsplit(proxy.url).port), "MAX_RETRIES": "0"}):
                    response = _request(h, "POST", parent, request)
                    _status(response, 500)
        _record(h, s, c, [parent])
        errors = response.json()["errors"]
        if s.parameters["environment"] == "production":
            assert all("debug" not in error for error in errors)
            assert "Injected" not in response.text and "Traceback" not in response.text
        else:
            assert all(error.get("debug", {}).get("exception") for error in errors)
            assert all("cause" in error["debug"] for error in errors)
            if s.parameters["category"] != "validation":
                assert all(error["debug"].get("stackTrace") for error in errors)
        assert h.snapshot(parent)["sql"] is None and not h.snapshot(parent)["points"]


def _execute_error_source(h, s, c):
    parent = h.new_id("source")
    request = uuid.uuid4().hex
    _fault(c, parent, request, operation="sql.read", error="runtime")
    response = _request(h, "POST", parent, request)
    _record(h, s, c, [parent])
    c.assert_triggered()
    _status(response, 500)
    assert all("source" not in error for error in response.json()["errors"])


def _correlation_failure_response(h, s, parent, request):
    bulk = s.parameters.get("bulk", False)
    path = "/api/v1/suggestions/bulk-delete" if bulk else "/api/v1/suggestions/ingest" if s.method == "POST" else f"/api/v1/suggestions/{parent}"
    body = {"suggestionIds": [parent]} if bulk else None if s.method == "DELETE" else {"title": _body(parent)["title"]} if s.method == "PATCH" else _body(parent)
    expected = str(uuid.uuid4()) if s.parameters["supplied"] else None
    headers = _headers(parent, request)
    if expected:
        headers["X-Request-Id"] = expected
        response = h.request(s.method, path, json=body, headers=headers)
    else:
        # Ordinary harness requests supply correlation; direct TCP exercises a
        # genuinely absent caller ID and retains its sanitized wire evidence.
        import httpx
        wire = {"method": s.method, "path": path, "headers": {h.config.api_header: h.config.api_key, **headers},
                "body": body, "url": h.base_url + path}
        _observe_direct_http(h, s, **wire)
        response = httpx.request(s.method, wire["url"], json=body, headers=wire["headers"],
                                 timeout=h.config.request_timeout, trust_env=False)
        _observe_direct_http(h, s, **wire, response=response)
    observed = response.headers.get("X-Request-Id")
    assert observed and (expected is None or observed == expected)
    uuid.UUID(observed)
    return response


def _execute_correlation(h, s, c):
    storage = s.parameters.get("dependency") == "qdrant"
    parent, before, request = _prepare(h, "DELETE" if storage else s.method)
    if storage:
        epoch = c.install([_rule("storage_failure", "qdrant.delete", parent, request, error="runtime")])
        response = _correlation_failure_response(h, s, parent, request)
        _record(h, s, c, [parent])
        c.assert_triggered()
        if s.parameters.get("bulk"):
            _bulk_assert_results(response, [parent], {0}, "vector")
        else:
            _status(response, 500)
            assert response.json()["errors"][0]["code"] == "RETRIEVAL_FAILED"
        assert c.events(epoch=epoch, request_id=request, operation="sql.soft_delete", timing="after", delegate_called=True)
        assert c.events(epoch=epoch, request_id=request, operation="sql.save", timing="after", delegate_called=True), "Real SQL compensation did not run"
        h.assert_consistent(parent, expected_version=3, expected_deleted=False)
        _unchanged(before["points"], h.snapshot(parent)["points"])
    else:
        prefix, upstream = _embedding_route(h)
        with ForwardingProxy(upstream, c, provider="embedding") as proxy:
            with _overrides(h, {prefix + "_HOST": "127.0.0.1", prefix + "_PORT": str(urlsplit(proxy.url).port), "MAX_RETRIES": "0"}):
                c.install([FaultRule("provider_failure", "http.embedding", action="reject", status=500, attempt=None)])
                response = _correlation_failure_response(h, s, parent, request)
                _record(h, s, c, [parent])
                c.assert_triggered()
                _status(response, 500)
                _unchanged(before, h.snapshot(parent))


def _execute_error_logs(h, s, c):
    parent = h.new_id("logs")
    request = uuid.uuid4().hex
    correlation = str(uuid.uuid4())
    c.install([_rule("primary", "vector.promote", parent, request, error="vector"),
               _rule("secondary", "vector.purge", parent, request, attempt=2, error="vector")])
    response = h.request("POST", "/api/v1/suggestions/ingest", json=_body(parent),
                         headers={**_headers(parent, request), "X-Request-Id": correlation})
    _record(h, s, c, [parent])
    c.assert_triggered()
    _status(response, 500)
    # Request completion acknowledgement ensures handlers executed; gracefully
    # stopping drains the real stdout pipe before inspecting logs (no sleeps).
    h.app.stop()
    try:
        content = h.app.log_path.read_text(encoding="utf-8")
        assert parent in content
        assert "primary" in content and "secondary" in content
        assert "compensating" in content.lower() or "compensating" in response.text.lower()
        assert correlation in content, "Fault logs lack useful request correlation"
        assert "/api/v1/suggestions/ingest" in content
    finally:
        h.app.start()


def _execute_recovered(h, s, c):
    parent = h.new_id("recovered")
    request = uuid.uuid4().hex
    original_pid = h.app.process.pid
    _fault(c, parent, request, operation="qdrant.upsert", attempt=[1, 2, 3], error="connection")
    _status(_request(h, "POST", parent, request), 500)
    _record(h, s, c, [parent], label="failed")
    c.assert_triggered()
    c.install([])
    recovered = _request(h, "POST", parent, uuid.uuid4().hex)
    _status(recovered, 201)
    assert h.app.process.pid == original_pid, "Recovery test restarted instead of proving the same process/pool is usable"
    h.assert_consistent(parent, expected_version=1, chunks_count=recovered.json()["data"]["chunksCount"])


def _execute_put_failure(h, s, c):
    parent = _seed(h, "put-failure")
    if s.parameters["deleted"]:
        _status(_request(h, "DELETE", parent, uuid.uuid4().hex), 200)
    before = h.snapshot(parent)
    old_version = before["sql"]["version"]
    phase = s.parameters["phase"]
    request = uuid.uuid4().hex
    rules = []
    if phase == "vector.delete_ids":
        rules = [_rule("primary_sql", "sql.save", parent, request, error="runtime"),
                 _rule("exact_cleanup", "vector.delete_ids", parent, request, error="vector")]
    elif phase == "sql.lock":
        with HeldAdvisoryLock(h, [parent]):
            response = _request(h, "PUT", parent, request)
            _record(h, s, c, [parent])
        _status(response, 409)
        _unchanged(before, h.snapshot(parent))
        return
    else:
        error = "sparse" if phase == "sparse.embed" else "normalizer" if phase.startswith("normalizer") else "chunker" if phase.startswith("chunker") else "vector" if phase.startswith("vector") else "runtime"
        attempts = [1, 2, 3] if phase in {"vector.promote", "vector.superseded"} else 1
        rules = [_rule("phase_failure", phase, parent, request, error=error, attempt=attempts)]
    c.install(rules)
    response = _request(h, "PUT", parent, request)
    _record(h, s, c, [parent])
    c.assert_triggered()
    _status(response, 422 if phase in {"chunker.chunk", "normalizer.normalize"} else 500)
    if phase == "normalizer.normalize":
        error = response.json()["errors"][0]
        assert error["code"] == "TEXT_NORMALIZATION_FAILED" and error["source"]["pointer"] == "/data"
    after = h.snapshot(parent)
    if phase in {"vector.promote", "vector.superseded"}:
        assert after["sql"]["version"] == old_version + 1 and not after["sql"]["is_deleted"]
        assert after["points"], "Committed cutover failure evidence unexpectedly lacks every new point"
    elif phase == "vector.delete_ids":
        _unchanged(before["sql"], after["sql"])
        assert any(point["payload"]["chunk_status"] == "staging" for point in after["points"])
    else:
        _unchanged(before, after)


def _execute_external_qdrant(h, s, c):
    parent, before, request = _prepare(h, s.method)
    p = s.parameters
    with ForwardingProxy(h.config.database.qdrant_url, c, provider="qdrant", upstream_timeout=h.config.request_timeout) as proxy:
        overrides = {"QDRANT_HOST": "127.0.0.1", "QDRANT_PORT": str(urlsplit(proxy.url).port), "QDRANT_PREFER_GRPC": "false"}
        if p.get("later"):
            overrides["QDRANT_BATCH_SIZE"] = "2"
        with _overrides(h, overrides, qdrant_proxy=proxy):
            epoch = c.install([FaultRule("network", p["operation"], parent_id=parent,
                timing="after" if p.get("lost") else "before", action="lose_response" if p.get("lost") else "reject",
                attempt=p.get("attempts", 1), status=p.get("status", 400))])
            response = _request(h, s.method, parent, request)
            _record(h, s, c, [parent])
            c.assert_triggered()
            if p.get("lost"):
                events = c.events(kind="fault_matched", epoch=epoch, rule_id="network")
                assert events[0]["forwarded"] and events[0]["applied"], "Lost acknowledgement was not proven applied upstream"
            if p.get("later"):
                assert c.events(kind="upstream_outcome", epoch=epoch, operation="http.qdrant.upsert", attempt=1, applied=True)
            if s.method == "POST":
                _status(response, 500)
                assert h.snapshot(parent)["sql"] is None and not h.snapshot(parent)["points"]
            elif s.method == "DELETE":
                _status(response, 500)
                assert h.snapshot(parent)["sql"]["version"] == 3
                h.assert_consistent(parent, expected_deleted=False)
            else:
                _status(response, 200)
                h.assert_consistent(parent, expected_version=2, expected_deleted=False)
