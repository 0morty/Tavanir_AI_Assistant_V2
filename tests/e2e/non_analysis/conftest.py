"""E2E opt-in, manifest collection, isolated processes, and per-case evidence."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import pytest

from .evidence import sanitize, write_json
from .manifest import scenario_key


def pytest_addoption(parser):
    group = parser.getgroup("non-analysis-e2e")
    group.addoption("--run-non-analysis-e2e", action="store_true", default=False)
    group.addoption("--e2e-config", default=None)
    group.addoption("--e2e-profile", choices=("smoke", "core", "resilience", "mock", "full"), default="core")
    group.addoption("--e2e-run-id", default=None)
    group.addoption("--e2e-artifacts", default=None)
    group.addoption("--e2e-repeats", type=int, default=1)
    group.addoption("--e2e-seed", type=int, default=42)


def pytest_configure(config):
    config.addinivalue_line("markers", "non_analysis_e2e: real TCP application and guarded test stores, requires explicit opt-in")
    config.addinivalue_line("markers", "resilience: acknowledged fault/race/crash schedules")
    config.addinivalue_line("markers", "mock_presentation: actual mock HTTP host, not real store evidence")
    workers = config.getoption("numprocesses", default=None)
    if config.getoption("run_non_analysis_e2e"):
        if config.getoption("e2e_profile") == "full":
            raise pytest.UsageError("Use the non-analysis runner for full execution; it isolates real, fault, and mock processes")
        if not config.getoption("run_db_tests"):
            raise pytest.UsageError("Non-analysis E2E requires both --run-non-analysis-e2e and --run-db-tests")
        if workers not in (None, 0, "0"):
            raise pytest.UsageError("E2E database execution is serial; races are scheduled inside scenarios")


def pytest_collection_modifyitems(config, items):
    enabled = config.getoption("run_non_analysis_e2e")
    profile = config.getoption("e2e_profile")
    selected = []
    deselected = []
    keys = set()
    smoke = {"HOST-01", "HOST-02", "ING-01", "ING-02", "FLOW-01", "FLOW-02", "FLOW-15"}
    for item in items:
        if "/non_analysis/" not in item.nodeid.replace("\\", "/"):
            selected.append(item)
            continue
        if not item.get_closest_marker("non_analysis_e2e"):
            selected.append(item)
            continue
        scenario = getattr(item, "callspec", None)
        scenario = scenario.params.get("scenario") if scenario is not None else None
        if scenario is None:
            raise pytest.UsageError(f"Unmapped E2E item: {item.nodeid}")
        key = scenario_key(scenario)
        if key in keys:
            raise pytest.UsageError(f"Duplicate collected E2E variant: {key}")
        keys.add(key)
        item._e2e_key = key
        is_fault = item.get_closest_marker("resilience") is not None
        is_mock = item.get_closest_marker("mock_presentation") is not None
        matches = (profile == "full" or profile == "mock" and is_mock or profile == "resilience" and is_fault or profile == "core" and not is_mock and not is_fault or profile == "smoke" and not is_mock and not is_fault and scenario.case_id in smoke)
        if not matches:
            deselected.append(item)
            continue
        if not enabled:
            item.add_marker(pytest.mark.skip(reason="Real E2E requires explicit --run-non-analysis-e2e --run-db-tests"))
        selected.append(item)
    items[:] = selected
    if deselected:
        config.hook.pytest_deselected(items=deselected)


def pytest_collection_finish(session):
    config = session.config
    if not config.getoption("run_non_analysis_e2e"):
        return
    from .manifest import coverage_manifest, validate_collection
    profile = config.getoption("e2e_profile")
    manifest = coverage_manifest()
    smoke = {"HOST-01", "HOST-02", "ING-01", "ING-02", "FLOW-01", "FLOW-02", "FLOW-15"}
    def selected(item):
        module = item["pytest_node_id"].split("::")[0]
        if profile == "mock":
            return module.endswith("test_mock_scenarios.py")
        if profile == "resilience":
            return module.endswith("test_resilience.py")
        return module.endswith("test_scenarios.py") and (profile == "core" or item["case_id"] in smoke)
    filtered = {"variants": [item for item in manifest["variants"] if selected(item)]}
    actual = [item.nodeid for item in session.items if getattr(item, "_e2e_key", None)]
    artifacts = config.getoption("e2e_artifacts")
    if artifacts:
        write_json(Path(artifacts) / "suite-manifest.json", manifest)
        write_json(Path(artifacts) / "collection.json", {"profile": profile, "collected": actual, "required": [item["pytest_node_id"] for item in filtered["variants"]]})
    if os.environ.get("E2E_ENFORCE_MANIFEST") == "1":
        try:
            validate_collection(filtered, actual)
        except ValueError as exc:
            raise pytest.UsageError(str(exc)) from None


@pytest.fixture(scope="session")
def e2e_session_config(request):
    from dataclasses import replace
    from .config import E2EConfig

    config = E2EConfig.load(request.config.getoption("e2e_config"))
    changes = {}
    if request.config.getoption("e2e_run_id"):
        changes["run_id"] = request.config.getoption("e2e_run_id")
    if request.config.getoption("e2e_artifacts"):
        changes["artifacts_dir"] = Path(request.config.getoption("e2e_artifacts"))
    return replace(config, **changes)


@pytest.fixture(scope="session")
def live_e2e_session(e2e_session_config, request):
    from .harness import LiveHarness

    profile = request.config.getoption("e2e_profile")
    app = "tests.e2e.non_analysis.bootstrap:create_app" if profile == "resilience" else "tests.e2e.non_analysis.mock_bootstrap:create_app" if profile == "mock" else "src.main:app"
    overrides = {"E2E_FAULT_DIR": str(e2e_session_config.artifacts_dir / "faults")} if profile == "resilience" else {}
    if profile == "mock":
        overrides = {"IS_MOCK": "true", "E2E_MOCK_EVIDENCE": str(e2e_session_config.artifacts_dir / "mock-state.json")}
    with LiveHarness(e2e_session_config, app=app, overrides=overrides, factory=profile in {"resilience", "mock"}) as harness:
        yield harness


@pytest.fixture
def e2e_harness(live_e2e_session, request):
    harness = live_e2e_session
    key = request.node._e2e_key
    case_dir = harness.config.artifacts_dir / "case_evidence" / hashlib.sha256(key.encode()).hexdigest()[:16]
    case_dir.mkdir(parents=True, exist_ok=True)
    request.node._e2e_evidence_dir = case_dir
    request.node._e2e_secrets = harness.config.secrets()
    # Never derive expected fields/chunks from the application implementation.
    from .oracles import digest
    before = harness.all_snapshot()
    baseline_path = harness.config.artifacts_dir / "sentinel-baseline.json"
    if not baseline_path.exists():
        write_json(baseline_path, before)
    write_json(case_dir / "before.json", {"sha256": digest(before), "baseline": str(baseline_path)})
    started = time.monotonic()
    try:
        yield harness
    finally:
        errors = []
        try:
            harness.settle_requests()
            after = harness.all_snapshot()
            write_json(case_dir / "after.json", {"sha256": digest(after), "fixtures": harness.oracle.snapshots(harness.registered_ids)})
            # All baseline sentinel parents must remain byte-for-byte equivalent.
            harness.assert_sentinels_unchanged(observed=after)
        except Exception as exc:
            errors.append(f"Snapshot/sentinel verification: {type(exc).__name__}: {exc}")
        try:
            harness.cleanup(observed=after if "after" in locals() else None)
            write_json(case_dir / "cleanup.json", {"verified": True})
        except Exception as exc:
            errors.append(f"Exact fixture cleanup: {type(exc).__name__}: {exc}")
            write_json(case_dir / "cleanup.json", {"verified": False, "errors": errors})
        request.node._e2e_duration = time.monotonic() - started
        if errors:
            request.session.shouldstop = "E2E verification/cleanup failed; stop further database writes"
            pytest.fail("; ".join(errors))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    key = getattr(item, "_e2e_key", None)
    if key is None:
        return
    records = getattr(item, "_e2e_phase_records", [])
    records.append({"phase": report.when, "outcome": report.outcome, "duration": report.duration, "detail": str(report.longrepr) if report.longrepr else None})
    item._e2e_phase_records = records
    if report.when != "teardown":
        return
    if any(entry["outcome"] == "failed" for entry in records):
        verdict = "Fail"
    elif any(entry["outcome"] == "skipped" for entry in records):
        verdict = "Blocked"
    else:
        verdict = "Pass"
    artifacts = item.config.getoption("e2e_artifacts")
    if artifacts is None:
        return
    filename = hashlib.sha256(key.encode()).hexdigest()[:16] + ".json"
    write_json(Path(artifacts) / "cases" / filename, {"key": key, "node_id": item.nodeid, "outcome": verdict, "phases": records, "file": filename, "evidence_dir": str(getattr(item, "_e2e_evidence_dir", ""))}, getattr(item, "_e2e_secrets", ()))
