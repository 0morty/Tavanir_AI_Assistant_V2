"""Pure harness controls: ordinary collection never starts a host or a store."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import json
import os
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from tests.database_safety import DatabaseTestConfig, TestDatabaseSafetyError
from tests.e2e.non_analysis.config import E2EConfig, resolve_secret
from tests.e2e.non_analysis.harness import AppProcess, LiveHarness, assert_non_analysis_path, sanitize
from tests.e2e.non_analysis.oracles import FixtureRegistry, RawStoreOracle, assert_consistent, assert_unchanged, validate_vectors


@pytest.fixture(autouse=True)
def fake_native_process_inventory(monkeypatch):
    from tests.e2e.non_analysis import harness
    # Offline controls never query real PIDs. Topology controls replace this
    # inventory with their explicit phase/app/unknown-child records.
    monkeypatch.setattr(harness, "_windows_process_rows", lambda query: [])


@pytest.fixture
def config(tmp_path):
    database = DatabaseTestConfig("127.0.0.1", 18442, "tavanir_test_db", "tavanir_test", "independent-test-password", "independent-admin-password", "127.0.0.1", 18343, 18344, "independent-vector-key", "independent-marker")
    return E2EConfig(database, repo_root=tmp_path, run_id="controls", artifacts_dir=tmp_path / "evidence", dense_dimension=2, api_key="independent-api-key")


def example(config):
    parent_id = config.fixture_prefix + "fixture"
    row = {"id": parent_id, "title": "A useful title", "problem": "The current process wastes power.", "solution": "Install a meter and collect data.", "status_id": 3, "context_title": None, "shamsi_date": None, "committee_scrutiny_id": None, "secretariat_scrutiny_id": None, "is_deleted": False, "version": 1}
    points = [{"id": f"00000000-0000-0000-0000-00000000000{index}", "payload": {"parent_id": parent_id, "chunk_status": "active", "chunk_type": kind, "content": row[kind], "status": "مصوب", "context_title": None, "date": None, "committee_scrutiny_id": None, "secretariat_scrutiny_id": None}, "vector": {"dense": [0.3, 0.7], "sparse": {"indices": [1, 7], "values": [0.1, 0.9]}}} for index, kind in enumerate(("title", "problem", "solution"), start=1)]
    return {"sql": row, "points": points}


def test_independent_oracle_accepts_matching_full_snapshot(config):
    assert_consistent(example(config), config, expected_version=1, chunks_count=3)


def test_live_harness_requires_parent_existence_unless_explicitly_overridden(config, monkeypatch):
    from tests.e2e.non_analysis import harness
    observed = []
    subject = object.__new__(LiveHarness)
    subject.config = config
    subject.snapshot = lambda parent_id: {"sql": None, "points": []}
    monkeypatch.setattr(harness, "assert_consistent", lambda snapshot, config, **expected: observed.append(expected))
    subject.assert_consistent("accepted-parent")
    subject.assert_consistent("intentionally-missing", require_exists=False)
    assert observed == [{"parent_id": "accepted-parent", "require_exists": True},
                        {"parent_id": "intentionally-missing", "require_exists": False}]


def test_control_detects_intentionally_removed_vector(config):
    state = example(config)
    state["points"].pop()
    with pytest.raises(AssertionError, match="chunk count"):
        assert_consistent(state, config, chunks_count=3)


@pytest.mark.parametrize("field,value", [("parent_id", "different-parent"), ("status", "رد"), ("chunk_status", "staging"), ("content", "Different title")])
def test_control_detects_wrong_payload(config, field, value):
    state = example(config)
    state["points"][0]["payload"][field] = value
    with pytest.raises(AssertionError):
        assert_consistent(state, config)


def test_control_detects_unrelated_record_or_vector_modification(config):
    before = example(config)
    after = copy.deepcopy(before)
    after["points"][0]["vector"]["dense"][0] += 0.001
    with pytest.raises(AssertionError, match="sentinel"):
        assert_unchanged(before, after)


def test_control_preserves_all_vectors_beyond_one_scroll_page(config):
    requests = []
    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if body.get("offset") is None:
            return httpx.Response(200, json={"result": {"points": [{"id": "a", "payload": {"parent_id": "parent"}, "vector": {"dense": [1, 0]}}], "next_page_offset": "a"}})
        return httpx.Response(200, json={"result": {"points": [{"id": "b", "payload": {"parent_id": "parent"}, "vector": {"dense": [0, 1]}}], "next_page_offset": None}})
    async def exercise():
        async with httpx.AsyncClient(base_url="http://test.invalid", transport=httpx.MockTransport(respond)) as client:
            return await RawStoreOracle(config, page_size=1)._scroll(client, ["parent"])
    points = asyncio.run(exercise())
    assert len(points) == 2
    assert points[1]["vector"]["dense"] == [0, 1]
    assert all(body["with_payload"] is True and body["with_vector"] is True for body in requests)
    assert requests[1]["offset"] == "a"
    assert requests[0]["filter"]["must"][0]["match"]["any"] == ["parent"]


def test_control_rejects_scroll_pagination_cycle(config):
    def respond(request):
        return httpx.Response(200, json={"result": {"points": [], "next_page_offset": "same"}})
    async def exercise():
        async with httpx.AsyncClient(base_url="http://test.invalid", transport=httpx.MockTransport(respond)) as client:
            await RawStoreOracle(config)._scroll(client)
    with pytest.raises(AssertionError, match="repeated pagination"):
        asyncio.run(exercise())


def test_control_rejects_unowned_write_before_network_access(config):
    registry = FixtureRegistry(config)
    parent_id = registry.new_id()
    with pytest.raises(TestDatabaseSafetyError, match="Docker ownership"):
        RawStoreOracle(config).clear_parent_points(parent_id, registry)
    with pytest.raises(TestDatabaseSafetyError, match="unregistered"):
        registry.require("historical-source-id")


def test_control_rejects_source_identity(config):
    with pytest.raises(TestDatabaseSafetyError):
        AppProcess(config, overrides={"POSTGRES_DB": "production"})


@pytest.mark.parametrize("path", ["/api/v1/suggestions/analyze", "/api/v1/suggestions/analyze/", "/api/v1/suggestions/%61nalyze", "/api/v1/suggestions/generate", "http://external.invalid/health", "//external.invalid/health"])
def test_control_prohibits_analysis_and_external_urls(path):
    with pytest.raises(ValueError):
        assert_non_analysis_path(path)


def test_control_keeps_secret_references_out_of_reports(config):
    assert resolve_secret({"env": "SECRET"}, {"SECRET": "private"}) == "private"
    with pytest.raises(ValueError, match="unset"):
        resolve_secret({"env": "SECRET"}, {})
    safe = sanitize({"headers": {config.api_header: config.api_key}, "text": config.database.pg_password}, config)
    assert config.api_key not in json.dumps(safe)
    assert config.database.pg_password not in json.dumps(safe)


def test_control_registry_journal_survives_failed_case(config):
    harness = LiveHarness(config)
    parent_id = harness.new_id("failed-case")
    journal = json.loads((config.artifacts_dir / "fixture-registry.json").read_text(encoding="utf-8"))
    assert journal["ids"] == [parent_id]
    assert journal["run_id"] == config.run_id
    assert config.api_key not in json.dumps(journal)


def test_empty_snapshot_checks_store_identities_without_invalid_in_clause(config, monkeypatch):
    from tests.e2e.non_analysis import oracles
    calls = []
    class Context:
        async def __aenter__(self):
            return object()
        async def __aexit__(self, *args):
            pass
    class Engine:
        def connect(self):
            return Context()
        async def dispose(self):
            calls.append("disposed")
    async def sql_guard(connection, database):
        calls.append("sql-identity")
    async def q_guard(client):
        calls.append("qdrant-identity")
    monkeypatch.setattr(oracles, "create_async_engine", lambda *args, **kwargs: Engine())
    monkeypatch.setattr(oracles, "verify_postgres_connection", sql_guard)
    oracle = RawStoreOracle(config)
    monkeypatch.setattr(oracle, "_client", lambda: Context())
    monkeypatch.setattr(oracle, "_qdrant_identity", q_guard)
    assert oracle.snapshots([]) == {"sql": {}, "points": []}
    assert calls == ["sql-identity", "qdrant-identity", "disposed"]


def test_interrupted_boundary_fixture_journal_requires_recorded_absence(config):
    boundary_id = "x" * 65
    journal = {"run_id": config.run_id, "config": config.redacted(), "ids": [boundary_id], "claims": {boundary_id: {"absent_before": True}}}
    assert FixtureRegistry.from_journal(config, journal).ids == {boundary_id}
    journal["claims"] = {}
    with pytest.raises(TestDatabaseSafetyError, match="absence witness"):
        FixtureRegistry.from_journal(config, journal)


def test_interrupted_cleanup_refuses_a_claim_over_known_sentinels(config):
    source_id = "historical-parent"
    journal = {"run_id": config.run_id, "config": config.redacted(), "ids": [source_id], "claims": {source_id: {"absent_before": True}}}
    with pytest.raises(TestDatabaseSafetyError, match="sentinel"):
        FixtureRegistry.from_journal(config, journal, sentinel_ids=[source_id])


def test_request_can_omit_generated_id_and_preserves_duplicate_auth_headers(config):
    captured = []
    def respond(request):
        captured.append(request)
        return httpx.Response(200, json={"ok": True})
    process = AppProcess(config)
    process.artifacts_dir.mkdir(parents=True)
    process.process = SimpleNamespace(poll=lambda: None)
    process._client = httpx.Client(base_url=process.base_url, transport=httpx.MockTransport(respond))
    try:
        process.request("GET", "/health", request_id=False, auth=False, headers=[("X-API-Key", config.api_key), ("X-API-Key", "second-value")])
    finally:
        process._client.close()
    assert "x-request-id" not in captured[0].headers
    assert captured[0].headers.get_list("X-API-Key") == [config.api_key, "second-value"]
    assert config.api_key not in (config.artifacts_dir / "http.ndjson").read_text(encoding="utf-8")


def test_raw_header_control_reaches_wire_without_client_stripping(config, monkeypatch):
    from tests.e2e.non_analysis import harness
    sent = []
    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def sendall(self, value):
            sent.append(value)
        def makefile(self, mode):
            return io.BytesIO(b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
    monkeypatch.setattr(harness.socket, "create_connection", lambda address, timeout: Connection())
    process = AppProcess(config)
    response = process._raw_request("DELETE", "/api/v1/suggestions/fixture", [("X-API-Key", " padded ")], {})
    assert response.status_code == 401
    assert b"X-API-Key:  padded \r\n" in sent[0]
    with pytest.raises(ValueError, match="injection"):
        process._raw_request("GET", "/health", [("X-API-Key", "valid\r\nInjected: true")], {})
    assert len(sent) == 1


def test_docker_mount_order_and_health_changes_do_not_change_ownership():
    from tests.e2e.non_analysis.infrastructure import ownership_fingerprint
    before = {"Config": {"Labels": {"tavanir.environment": "test"}, "Env": ["ENV=test"]}, "Mounts": [{"Destination": "/data", "Source": "test-volume", "Type": "volume"}, {"Destination": "/init", "Source": "init.sh", "Type": "bind", "RW": False}], "HostConfig": {"PortBindings": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "7442"}]}}, "NetworkSettings": {"Networks": {"test": {"NetworkID": "test-network", "IPAddress": "172.0.0.2"}}}, "State": {"Running": True, "Health": {"Status": "healthy", "Log": [1]}}}
    after = copy.deepcopy(before)
    after["Mounts"].reverse()
    after["State"]["Health"]["Log"].append(2)
    after["NetworkSettings"]["Networks"]["test"]["IPAddress"] = "172.0.0.3"
    assert ownership_fingerprint(before) == ownership_fingerprint(after)
    after["Mounts"][0]["RW"] = True
    assert ownership_fingerprint(before) != ownership_fingerprint(after)


def _owned_record(config, *, child=False):
    directory = config.artifacts_dir
    directory.mkdir(parents=True, exist_ok=True)
    stop_file = directory / "stop-1.signal"
    command = [config.python_executable, "-m", "tests.e2e.non_analysis.harness", "--serve", "src.main:app", "--port", "18000", "--stop-file", str(stop_file)]
    identity = {"pid": 101, "parent_pid": 10, "creation_id": "trusted-creation-101", "executable": config.python_executable, "command_line": subprocess.list2cmdline(command)}
    identities = [identity]
    if child:
        identities.append({**identity, "pid": 102, "parent_pid": 101, "creation_id": "trusted-creation-102"})
    record = {"run_id": config.run_id, "target": config.redacted(), "generation": 1, "base_url": "http://127.0.0.1:18000", "started_utc": "2026-10-03T00:00:00+00:00", "command": command, "stop_file": str(stop_file), "identities": identities, "verified_stopped": False}
    path = directory / "owned-processes.json"
    path.write_text(json.dumps([record]), encoding="utf-8")
    return path, stop_file, identities


def test_interrupted_process_recovery_stops_verified_parent_and_host_child(config, monkeypatch):
    from tests.e2e.non_analysis import harness
    path, stop_file, identities = _owned_record(config, child=True)
    processes = {item["pid"]: item for item in identities}
    monkeypatch.setattr(harness, "_query_process_identity", lambda pid: None if stop_file.exists() else processes.get(pid))
    monkeypatch.setattr(harness, "_terminate_verified_process", lambda *args: pytest.fail("Graceful recovery should not force termination"))
    result = harness.recover_and_stop(config)
    assert result == {"verified": True, "stopped_pids": [101, 102], "generations": 1}
    record = json.loads(path.read_text())[0]
    assert record["verified_stopped"] is True
    assert record["stopped_utc"]
    assert config.api_key not in path.read_text()


def test_interrupted_process_recovery_refuses_pid_reuse_before_any_action(config, monkeypatch):
    from tests.e2e.non_analysis import harness
    path, stop_file, identities = _owned_record(config)
    monkeypatch.setattr(harness, "_query_process_identity", lambda pid: {**identities[0], "creation_id": "new-unrelated-creation"})
    monkeypatch.setattr(harness, "_terminate_verified_process", lambda *args: pytest.fail("Must not kill an unrelated PID"))
    with pytest.raises(TestDatabaseSafetyError, match="uncertain"):
        harness.recover_and_stop(config)
    assert not stop_file.exists()
    assert json.loads(path.read_text())[0]["verified_stopped"] is False


def test_interrupted_process_recovery_forces_verified_children_before_parent(config, monkeypatch):
    from tests.e2e.non_analysis import harness
    config = replace(config, shutdown_timeout=0.001)
    _, _, identities = _owned_record(config, child=True)
    processes = {item["pid"]: item for item in identities}
    stopped = []
    monkeypatch.setattr(harness, "_query_process_identity", lambda pid: processes.get(pid))
    def terminate(identity, timeout):
        stopped.append(identity["pid"])
        processes.pop(identity["pid"])
    monkeypatch.setattr(harness, "_terminate_verified_process", terminate)
    monkeypatch.setattr(harness.time, "sleep", lambda duration: None)
    ticks = iter(range(10))
    monkeypatch.setattr(harness.time, "monotonic", lambda: next(ticks))
    assert harness.recover_and_stop(config)["verified"] is True
    assert stopped == [102, 101]


def test_interrupted_process_recovery_refuses_missing_evidence(config):
    from tests.e2e.non_analysis.harness import recover_and_stop
    with pytest.raises(TestDatabaseSafetyError, match="missing"):
        recover_and_stop(config)


def test_windows_console_child_requires_system_image_parent_creation_and_command(monkeypatch):
    from tests.e2e.non_analysis import harness
    if harness.os.name != "nt":
        pytest.skip("Windows launcher ownership control")
    system_image = r"C:\Windows\System32\conhost.exe"
    monkeypatch.setattr(harness, "_windows_console_path", lambda: system_image)
    parent = {"pid": 101, "creation_id": "100"}
    child = {"pid": 102, "parent_pid": 101, "creation_id": "101", "executable": system_image,
             "command_line": "\\??\\" + system_image + " 0x4"}
    assert harness._is_owned_console_host(child, parent) is True
    for field, value in (("parent_pid", 99), ("creation_id", "99"), ("executable", r"D:\Workspace\conhost.exe"),
                         ("command_line", "\\??\\" + system_image + " 0x4 --unexpected")):
        assert harness._is_owned_console_host({**child, field: value}, parent) is False


def test_recovery_includes_verified_console_helper_without_relaxing_python_command(config, monkeypatch):
    from tests.e2e.non_analysis import harness
    path, stop_file, identities = _owned_record(config)
    parent = identities[0]
    child = {"pid": 102, "parent_pid": parent["pid"], "creation_id": "trusted-console", "executable": "trusted-conhost",
             "command_line": "trusted-console-command"}
    records = json.loads(path.read_text())
    records[0]["identities"].append(child)
    path.write_text(json.dumps(records))
    monkeypatch.setattr(harness, "_query_process_identity", lambda pid: None if stop_file.exists() else {parent["pid"]: parent, child["pid"]: child}.get(pid))
    monkeypatch.setattr(harness, "_is_owned_console_host", lambda current, original_parent: current == child and original_parent == parent)
    assert harness.recover_and_stop(config)["stopped_pids"] == [101, 102]


def test_first_start_recovers_before_spawn_and_preserves_generation_history(config, monkeypatch):
    from tests.e2e.non_analysis import harness
    path, _, _ = _owned_record(config)
    order = []
    captured = []
    def recover(*args):
        order.append("recover")
        records = json.loads(path.read_text())
        records[0]["verified_stopped"] = True
        path.write_text(json.dumps(records))
        return {"verified": True, "stopped_pids": [101], "generations": 1}
    def spawn(command, **kwargs):
        order.append("spawn")
        captured.append(command)
        return SimpleNamespace(pid=201, poll=lambda: None, stdout=io.StringIO(""))
    class Client:
        def __init__(self, **kwargs):
            pass
        def get(self, path, **kwargs):
            return httpx.Response(200, json={"mockMode": False} if path == "/" else {"status": "ok"})
    monkeypatch.setattr(harness, "recover_and_stop", recover)
    monkeypatch.setattr(harness.subprocess, "Popen", spawn)
    monkeypatch.setattr(harness.httpx, "Client", Client)
    monkeypatch.setattr(harness, "_query_process_identity", lambda pid: {"pid": pid, "parent_pid": 10, "creation_id": "new-creation", "executable": config.python_executable, "command_line": subprocess.list2cmdline(captured[0])})
    monkeypatch.setattr(harness, "_query_owned_children", lambda *args: [])
    process = AppProcess(config).start()
    records = json.loads(path.read_text())
    assert order == ["recover", "spawn"]
    assert [item["generation"] for item in records] == [1, 2]
    assert records[0]["verified_stopped"] is True
    assert records[1]["base_url"] == process.base_url
    assert records[1]["started_utc"]
    assert "stop-2.signal" in records[1]["stop_file"]


def test_mutated_identity_overrides_rejected_before_spawn(config, monkeypatch):
    from tests.e2e.non_analysis import harness
    process = AppProcess(config)
    process.overrides["POSTGRES_DB"] = "development"
    monkeypatch.setattr(harness.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Guard must precede process launch"))
    with pytest.raises(TestDatabaseSafetyError, match="guarded test database"):
        process.start()


@pytest.mark.parametrize("key,port", [("QDRANT_PORT", 19991), ("QDRANT_GRPC_PORT", 19992), ("POSTGRES_PORT", 19993)])
def test_qdrant_overrides_reject_configured_development_ports(config, key, port):
    (config.repo_root / ".env").write_text(f"{key}={port}\n", encoding="utf-8")
    with pytest.raises(TestDatabaseSafetyError, match="development service ports"):
        AppProcess(config, overrides={"QDRANT_PORT": str(port)})


def test_changed_qdrant_listener_requires_real_proxy_proof(config):
    spoofed = SimpleNamespace(validate_owned_endpoint=lambda **kwargs: None)
    with pytest.raises(TestDatabaseSafetyError, match="run-owned proxy proof"):
        AppProcess(config, overrides={"QDRANT_PORT": "19994"}, qdrant_proxy_proof=spoofed)


def test_owned_qdrant_route_proof_revalidated_on_start(config, monkeypatch):
    from tests.e2e.non_analysis import harness
    from tests.e2e.non_analysis.proxy import _ProxyOwnershipProof
    calls = []
    proof = _ProxyOwnershipProof(SimpleNamespace(), config.run_id)
    def validate(self, **kwargs):
        calls.append(kwargs)
        if len(calls) > 1:
            raise ValueError("Owned listener is closed")
    monkeypatch.setattr(_ProxyOwnershipProof, "validate_owned_endpoint", validate)
    process = AppProcess(config, overrides={"QDRANT_PORT": "19994"}, qdrant_proxy_proof=proof)
    monkeypatch.setattr(harness.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Closed proof must reject before spawn"))
    with pytest.raises(TestDatabaseSafetyError, match="live run-owned test route"):
        process.start()
    assert calls == [{"run_id": config.run_id, "host": config.database.q_host, "port": 19994, "expected_upstream": config.database.qdrant_url}] * 2


def test_raw_parent_snapshots_are_recorded_without_extra_store_reads(config, monkeypatch):
    harness = LiveHarness(config)
    calls = []
    state = example(config)
    monkeypatch.setattr(harness.oracle, "snapshot", lambda parent: calls.append(parent) or state)
    assert harness.snapshot(state["sql"]["id"]) == state
    assert calls == [state["sql"]["id"]]
    observed = json.loads((config.artifacts_dir / "observations.ndjson").read_text(encoding="utf-8"))
    assert observed["name"] == "raw_parent_snapshot"
    assert observed["data"]["snapshot"] == state


def test_raw_socket_timeout_marks_request_unsettled_for_cleanup(config, monkeypatch):
    process = AppProcess(config)
    process.artifacts_dir.mkdir(parents=True)
    process.process = SimpleNamespace(poll=lambda: None)
    process._client = object()
    def time_out(*args):
        raise TimeoutError("owned socket timed out")
    monkeypatch.setattr(process, "_raw_request", time_out)
    with pytest.raises(TimeoutError):
        process.request("GET", "/health", raw_headers=True)
    assert process.unsettled_request is True


def test_raw_reader_reuses_secure_tls_context_without_network(config, monkeypatch):
    import ssl
    from tests.e2e.non_analysis import oracles
    recorded = []
    monkeypatch.setattr(oracles.httpx, "AsyncClient", lambda **kwargs: recorded.append(kwargs))
    oracle = RawStoreOracle(config)
    oracle._client()
    oracle._client()
    context = recorded[0]["verify"]
    assert recorded[1]["verify"] is context
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert all(item["trust_env"] is False for item in recorded)


def _phase_record(config):
    from tests.e2e.non_analysis import harness
    journal, arguments_file, ready_file = harness._phase_paths(config)
    journal.parent.mkdir(parents=True, exist_ok=True)
    arguments_file.write_text(json.dumps(["tests/e2e/non_analysis/test_harness_controls.py", "-q"]), encoding="utf-8")
    command = harness._phase_command(config, arguments_file, ready_file)
    parent = {"pid": 101, "parent_pid": 10, "creation_id": "100", "executable": config.python_executable, "command_line": subprocess.list2cmdline(command)}
    child = {**parent, "pid": 102, "parent_pid": 101, "creation_id": "101"}
    record = {"run_id": config.run_id, "target": config.redacted(), "command": command, "arguments_sha256": hashlib.sha256(arguments_file.read_bytes()).hexdigest(),
              "identities": [parent, child], "verified_stopped": False, "return_code": None}
    journal.write_text(json.dumps(record), encoding="utf-8")
    return journal, record


def test_pytest_child_does_not_execute_without_durable_ready_ack(config, monkeypatch):
    from tests.e2e.non_analysis import harness
    journal, record = _phase_record(config)
    _, arguments_file, ready_file = harness._phase_paths(config)
    ticks = iter((0, 1))
    monkeypatch.setattr(harness.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(harness.runpy, "run_module", lambda *args, **kwargs: pytest.fail("Unacknowledged pytest must not execute"))
    with pytest.raises(TimeoutError, match="acknowledgement"):
        harness._run_pytest(arguments_file, ready_file, 0.1)


@pytest.mark.parametrize("timeout", [False, True])
def test_owned_pytest_journals_before_execution_and_settles_full_tree(config, monkeypatch, timeout):
    from tests.e2e.non_analysis import harness
    processes, order = {}, []
    class Process:
        pid = 101
        returncode = None
        def wait(self, *, timeout):
            journal, _, ready_file = harness._phase_paths(config)
            assert ready_file.is_file() and journal.is_file()
            record = json.loads(journal.read_text(encoding="utf-8"))
            assert len(record["identities"]) == 2 and record["target"] == config.redacted()
            order.append("wait")
            if len(order) == 1 and should_timeout:
                raise subprocess.TimeoutExpired(record["command"], timeout)
            processes.clear()
            self.returncode = 137 if should_timeout else 7
            return self.returncode
    should_timeout = timeout
    def spawn(command, **kwargs):
        parent = {"pid": 101, "parent_pid": 10, "creation_id": "100", "executable": config.python_executable, "command_line": subprocess.list2cmdline(command)}
        processes.update({101: parent, 102: {**parent, "pid": 102, "parent_pid": 101, "creation_id": "101"}})
        return Process()
    monkeypatch.setattr(harness.subprocess, "Popen", spawn)
    monkeypatch.setattr(harness, "_query_process_identity", lambda pid: processes.get(pid))
    monkeypatch.setattr(harness, "_query_owned_children", lambda *args: [processes[102]])
    monkeypatch.setattr(harness, "_known_application_identities", lambda config: {})
    monkeypatch.setattr(harness, "_assert_phase_descendants", lambda identities, known: None)
    def terminate(identity, seconds):
        order.append(identity["pid"])
        processes.pop(identity["pid"], None)
    monkeypatch.setattr(harness, "_terminate_verified_process", terminate)
    if should_timeout:
        with pytest.raises(subprocess.TimeoutExpired):
            harness.run_owned_pytest(config, ["offline-control"], output=io.StringIO(), environment={}, timeout=0.1)
        assert order == ["wait", 102, 101, "wait"]
    else:
        assert harness.run_owned_pytest(config, ["offline-control"], output=io.StringIO(), environment={}, timeout=0.1) == 7
    journal = json.loads(harness._phase_paths(config)[0].read_text(encoding="utf-8"))
    assert journal["verified_stopped"] is True
    assert journal["return_code"] == (137 if should_timeout else 7)


def test_owned_pytest_recovery_refuses_pid_reuse_before_termination(config, monkeypatch):
    from tests.e2e.non_analysis import harness
    _, record = _phase_record(config)
    monkeypatch.setattr(harness, "_query_process_identity", lambda pid: {**record["identities"][0], "creation_id": "reused"})
    monkeypatch.setattr(harness, "_terminate_verified_process", lambda *args: pytest.fail("Reused PID cannot be terminated"))
    with pytest.raises(TestDatabaseSafetyError, match="uncertain"):
        harness.recover_owned_pytest(config)


def test_owned_pytest_recovery_rejects_unknown_live_descendants(config, monkeypatch):
    from tests.e2e.non_analysis import harness
    if harness.os.name != "nt":
        pytest.skip("Windows descendant topology control")
    _, record = _phase_record(config)
    processes = {item["pid"]: item for item in record["identities"]}
    processes[999] = {**record["identities"][1], "pid": 999, "command_line": "unrelated command"}
    monkeypatch.setattr(harness, "_query_process_identity", lambda pid: processes.get(pid))
    monkeypatch.setattr(harness, "_known_application_identities", lambda config: {})
    monkeypatch.setattr(harness, "_windows_process_rows", lambda query: [{"ProcessId": 999}])
    monkeypatch.setattr(harness, "_terminate_verified_process", lambda *args: pytest.fail("Unknown descendant must refuse cleanup"))
    with pytest.raises(TestDatabaseSafetyError, match="Unexpected owned process descendant"):
        harness.recover_owned_pytest(config)


def test_phase_recovery_checks_unknown_grandchild_below_known_app(config, monkeypatch):
    from tests.e2e.non_analysis import harness
    if harness.os.name != "nt":
        pytest.skip("Windows descendant topology control")
    journal, record = _phase_record(config)
    phase = {item["pid"]: item for item in record["identities"]}
    app = {**phase[102], "pid": 201, "parent_pid": 102, "command_line": "proved application command"}
    unknown = {**app, "pid": 301, "parent_pid": 201, "command_line": "unproved grandchild command"}
    processes = {**phase, 201: app, 301: unknown}
    queried = []
    def children(query):
        parent = int(query.rsplit(" ", 1)[1])
        queried.append(parent)
        return [{"ProcessId": child["pid"]} for child in processes.values() if child["parent_pid"] == parent]
    monkeypatch.setattr(harness, "_query_process_identity", lambda pid: processes.get(pid))
    monkeypatch.setattr(harness, "_windows_process_rows", children)
    monkeypatch.setattr(harness, "_known_application_identities", lambda config: {201: app})
    monkeypatch.setattr(harness, "_terminate_verified_process", lambda *args: pytest.fail("Unknown grandchild must refuse termination and cleanup"))
    with pytest.raises(TestDatabaseSafetyError, match="Unexpected owned process descendant"):
        harness.recover_owned_pytest(config)
    assert 201 in queried
    assert json.loads(journal.read_text())["verified_stopped"] is False


@pytest.mark.parametrize("late", [False, True])
def test_app_recovery_checks_unknown_descendant_before_and_after_shutdown(config, monkeypatch, late):
    from tests.e2e.non_analysis import harness
    if harness.os.name != "nt":
        pytest.skip("Windows descendant topology control")
    journal, stop_file, identities = _owned_record(config, child=True)
    processes = {item["pid"]: item for item in identities}
    unknown = {**identities[1], "pid": 301, "parent_pid": 102, "command_line": "unproved app grandchild"}
    def current(pid):
        if pid == 301:
            return unknown
        return None if stop_file.exists() else processes.get(pid)
    def children(query):
        parent = int(query.rsplit(" ", 1)[1])
        if parent == 102 and (not late or stop_file.exists()):
            return [{"ProcessId": 301}]
        return [] if stop_file.exists() else [{"ProcessId": child["pid"]} for child in processes.values() if child["parent_pid"] == parent]
    monkeypatch.setattr(harness, "_query_process_identity", current)
    monkeypatch.setattr(harness, "_windows_process_rows", children)
    monkeypatch.setattr(harness, "_terminate_verified_process", lambda *args: pytest.fail("Unproved app descendant must not be terminated"))
    with pytest.raises(TestDatabaseSafetyError, match="Unexpected owned process descendant"):
        harness.recover_and_stop(config)
    assert stop_file.exists() is late
    assert json.loads(journal.read_text())[0]["verified_stopped"] is False


def test_sibling_reproduction_manifest_is_recovered_by_exact_stack_labels(config, monkeypatch):
    from tests.e2e.non_analysis import infrastructure, runner
    root = config.artifacts_dir
    phase = root / "phases" / "14-smoke"
    manifest = root / "reproduction" / "compose.json"
    manifest.parent.mkdir(parents=True)
    labels = {"tavanir.environment": "test", "tavanir.e2e.run": "owned-reproduction"}
    manifest.write_text(json.dumps({"services": {"postgres": {"labels": labels}, "qdrant": {"labels": labels}}}), encoding="utf-8")
    class Infrastructure:
        def __init__(self, config):
            self.config = config
        def recover(self):
            return self.config
        def verify(self):
            pass
    monkeypatch.setattr(infrastructure, "ManagedTestInfrastructure", Infrastructure)
    recovered, owned = runner._recovery_infrastructure(replace(config, infrastructure="disposable", stack_run_id="owned-reproduction", artifacts_dir=phase))
    assert owned.config.artifacts_dir == manifest.parent
    assert recovered.artifacts_dir == phase
    manifest.write_text(json.dumps({"services": {"postgres": {"labels": {**labels, "tavanir.e2e.run": "other-run"}}, "qdrant": {"labels": labels}}}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="Exact run-owned Compose"):
        runner._recovery_infrastructure(replace(config, infrastructure="disposable", stack_run_id="owned-reproduction", artifacts_dir=phase))


def test_full_run_exit_requires_readiness_without_claiming_partial_full_coverage():
    from tests.e2e.non_analysis.runner import _run_exit_code
    metadata = {"cleanup_verified": True, "production_source_unchanged": True, "harness_changed_between_phases": False}
    assert _run_exit_code("full", [0], metadata, {"readiness_pass": False}) == 1
    assert _run_exit_code("core", [0], metadata, {"readiness_pass": False}) == 0
    assert _run_exit_code("full", [0], metadata, {"readiness_pass": True}) == 0


def test_owned_pytest_waiting_timeout_probe():
    seconds = os.environ.get("E2E_OWNED_PYTEST_WAIT_SECONDS")
    if seconds is None:
        pytest.skip("Run only for explicit bounded non-DB process-ownership qualification")
    duration = int(seconds)
    assert 1 <= duration <= 60
    time.sleep(duration)


def test_emergency_cleanup_groups_exact_targets_and_settles_all_before_writes(config, monkeypatch):
    from tests.e2e.non_analysis import oracles, runner
    root = config.artifacts_dir
    first = replace(config, run_id="existing-phase", artifacts_dir=root / "phases/01-core")
    database = replace(config.database, pg_port=19442, q_port=19343, q_grpc_port=19344, environment_id="owned-reproduction-marker")
    second = replace(config, database=database, run_id="fresh-smoke", infrastructure="disposable", stack_run_id="owned-reproduction", artifacts_dir=root / "phases/14-smoke")
    third = replace(second, run_id="fresh-core", artifacts_dir=root / "phases/15-core")
    baseline = {"sql": {}, "points": [], "regulatory_points": []}
    for phase in (first, second, third):
        phase.artifacts_dir.mkdir(parents=True)
        (phase.artifacts_dir / "owned-pytest-process.json").write_text(json.dumps({"target": phase.redacted()}), encoding="utf-8")
        registry = FixtureRegistry(phase)
        registry.new_id("interrupted")
        (phase.artifacts_dir / "fixture-registry.json").write_text(json.dumps({"run_id": phase.run_id, "config": phase.redacted(), "ids": sorted(registry.ids), "claims": registry.claims}), encoding="utf-8")
        (phase.artifacts_dir / "sentinel-baseline.json").write_text(json.dumps(baseline), encoding="utf-8")
    events = []
    class Infrastructure:
        def __init__(self, phase):
            self.config = phase
            self.owner_run_id = phase.stack_run_id or phase.run_id
        def verify(self):
            pass
        def cleanup(self):
            events.append(("infrastructure", self.config.infrastructure, self.owner_run_id))
            return {"removed": self.config.infrastructure == "disposable"}
    class Oracle:
        def __init__(self, phase, **kwargs):
            self.config = phase
        def cleanup(self, registry):
            assert len([item for item in events if item[0] == "settled"]) == 3
            events.append(("raw", self.config.run_id, self.config.database.pg_port, sorted(registry.ids)))
        def all_snapshot(self):
            return baseline
    monkeypatch.setattr(runner, "_recovery_infrastructure", lambda phase: (phase, Infrastructure(phase)))
    monkeypatch.setattr(runner, "_settle_phase", lambda phase: events.append(("settled", phase.run_id)) or {"verified": True})
    monkeypatch.setattr(oracles, "RawStoreOracle", Oracle)
    runner.cleanup(config)
    raw = [item for item in events if item[0] == "raw"]
    assert [(item[1], item[2]) for item in raw] == [("existing-phase", 18442), ("fresh-smoke", 19442), ("fresh-core", 19442)]
    assert all(len(item[3]) == 1 for item in raw)
    assert [item for item in events if item[0] == "infrastructure" and item[1] == "disposable"] == [("infrastructure", "disposable", "owned-reproduction")]
    assert all(json.loads((phase.artifacts_dir / "fixture-registry.json").read_text())["cleanup_verified"] is True for phase in (first, second, third))


def test_interrupted_cleanup_refuses_missing_pytest_proof_before_application_actions(config, monkeypatch):
    from tests.e2e.non_analysis import harness, runner
    monkeypatch.setattr(harness, "recover_and_stop", lambda *args: pytest.fail("Missing phase proof must precede all app recovery"))
    with pytest.raises(RuntimeError, match="pytest process proof"):
        runner._settle_phase(config)


def test_recovery_config_refuses_source_host_or_unsupported_alias(config):
    from tests.e2e.non_analysis import runner
    target = {**config.redacted(), "postgres_host": "192.0.2.1"}
    with pytest.raises(TestDatabaseSafetyError):
        runner._recovery_config(config, target, config.artifacts_dir)
    with pytest.raises(ValueError, match="supported guarded"):
        runner._recovery_config(config, {**config.redacted(), "alias": "development_alias"}, config.artifacts_dir)


def test_owned_preparation_requires_exact_module_or_approved_script_hash(config, monkeypatch):
    from tests.e2e.non_analysis import harness
    monkeypatch.setattr(harness.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Unapproved preparation cannot launch"))
    with pytest.raises(TestDatabaseSafetyError, match="approved"):
        harness.run_owned_preparation(config, ["-m", "alembic", "downgrade", "base"], label="migration", environment={}, timeout=1)
    with pytest.raises(TestDatabaseSafetyError, match="approved"):
        harness.run_owned_preparation(config, ["-c", "print('not-approved')"], label="seed", environment={}, timeout=1, expected_script_sha256="wrong")


def test_owned_preparation_uses_acknowledged_host_and_output_capture(config, monkeypatch):
    from tests.e2e.non_analysis import harness
    script = "print('PREPARATION_READY')"
    expected = hashlib.sha256(script.encode("utf-8")).hexdigest()
    def owned(phase, arguments, **kwargs):
        assert phase.artifacts_dir == config.artifacts_dir / "preparation" / "seed"
        assert arguments == ["-c", script]
        assert kwargs["_kind"] == "preparation"
        assert kwargs["_approval"] == {"script_sha256": expected}
        assert kwargs["_capture_output"] is True
        kwargs["output"].write("PREPARATION_READY\n")
        return 0
    monkeypatch.setattr(harness, "run_owned_pytest", owned)
    assert harness.run_owned_preparation(config, ["-c", script], label="seed", environment={}, timeout=1, expected_script_sha256=expected) == "PREPARATION_READY\n"


def test_preparation_teardown_refuses_lost_proof_or_lost_argument_evidence(config, monkeypatch):
    from tests.e2e.non_analysis import harness, infrastructure
    phase = replace(config, artifacts_dir=config.artifacts_dir / "preparation" / "seed")
    journal, record = _phase_record(phase)
    record["kind"] = "preparation"
    journal.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(infrastructure, "run_command", lambda *args, **kwargs: pytest.fail("Lost preparation proof must block Docker teardown"))
    arguments_file = harness._phase_paths(phase)[1]
    arguments_file.unlink()
    with pytest.raises(TestDatabaseSafetyError, match="argument evidence"):
        infrastructure.ManagedTestInfrastructure(config).cleanup()
    arguments_file.write_text("[]", encoding="utf-8")
    journal.unlink()
    with pytest.raises(TestDatabaseSafetyError, match="proof is missing"):
        infrastructure.ManagedTestInfrastructure(config).cleanup()


def test_unacknowledged_phase_cannot_be_restarted_over_lost_ownership_proof(config, monkeypatch):
    from tests.e2e.non_analysis import harness
    _, arguments_file, _ = harness._phase_paths(config)
    arguments_file.parent.mkdir(parents=True)
    arguments_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(harness.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Lost-proof phase cannot relaunch"))
    with pytest.raises(TestDatabaseSafetyError, match="already exist"):
        harness.run_owned_pytest(config, ["offline-control"], output=io.StringIO(), environment={}, timeout=1)


def test_preparation_timeout_preserves_original_expiration_after_settling_host(config, monkeypatch):
    from tests.e2e.non_analysis import harness
    script = "import time; time.sleep(30)"
    def timeout(phase, arguments, **kwargs):
        assert kwargs["_kind"] == "preparation" and kwargs["_capture_output"] is True
        raise subprocess.TimeoutExpired(arguments, kwargs["timeout"])
    monkeypatch.setattr(harness, "run_owned_pytest", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        harness.run_owned_preparation(config, ["-c", script], label="seed", environment={}, timeout=0.1, expected_script_sha256=hashlib.sha256(script.encode("utf-8")).hexdigest())


def test_control_deleted_parent_orphans_fail(config):
    state = example(config)
    state["sql"]["is_deleted"] = True
    with pytest.raises(AssertionError, match="retains vector"):
        assert_consistent(state, config)


@pytest.mark.parametrize("mutation", ["dimension", "nonfinite", "duplicate-sparse"])
def test_control_bad_embedding_vectors_fail(config, mutation):
    state = example(config)
    vector = state["points"][0]["vector"]
    if mutation == "dimension":
        vector["dense"].pop()
    elif mutation == "nonfinite":
        vector["dense"][0] = float("nan")
    else:
        vector["sparse"]["indices"] = [7, 7]
    with pytest.raises(AssertionError):
        validate_vectors(state["points"], config)
