"""Offline tests that prevent incomplete or unsafe harness evidence passing."""

from pathlib import Path

import pytest

from .evidence import execution_evidence, render_report, run_gate_evidence, sanitize, write_json
from .manifest import checklist_requirements, validate_collection


def test_authoritative_checklist_has_all_210_stable_cases():
    requirements = checklist_requirements()
    assert len(requirements) == 210
    assert sum(key.startswith(("SET-", "DONE-")) for key in requirements) == 18


def test_missing_manifest_variant_fails_collection_completeness():
    manifest = {"variants": [{"pytest_node_id": "test.py::test_case[a]"}, {"pytest_node_id": "test.py::test_case[b]"}]}
    with pytest.raises(ValueError, match="1 missing"):
        validate_collection(manifest, ["test.py::test_case[a]"])


def test_unmapped_executable_test_fails_collection_completeness():
    with pytest.raises(ValueError, match="1 unexpected"):
        validate_collection({"variants": []}, ["unmapped.py::test_case"])


def test_reports_never_erase_a_failed_attempt_with_a_later_pass(tmp_path):
    write_json(tmp_path / "cases/first.json", {"key": "DEL-05/probe", "outcome": "Fail", "file": "first.json"})
    write_json(tmp_path / "cases/second.json", {"key": "DEL-05/probe", "outcome": "Pass", "file": "second.json"})
    manifest = {"variants": [{"key": "DEL-05/probe"}], "unimplemented_cases": {}, "implementation_complete": True}
    report = render_report(tmp_path, manifest, {"cleanup_verified": True})
    assert report["outcomes"] == {"Fail": 1, "Pass": 1}
    assert report["readiness_pass"] is False


def test_unexecuted_mapped_case_cannot_produce_execution_complete(tmp_path):
    manifest = {"variants": [{"key": "DEL-05/probe"}], "unimplemented_cases": {}, "implementation_complete": True}
    report = render_report(tmp_path, manifest, {"cleanup_verified": True})
    assert report["execution_complete"] is False
    assert report["readiness_pass"] is False


def test_secret_values_and_auth_headers_are_redacted_recursively():
    observed = sanitize({"headers": {"Authorization": "Bearer private", "X-API-Key": "private"}, "trace": "url-password=private"}, ("private",))
    assert "private" not in str(observed)
    assert "[REDACTED]" in str(observed)


def test_non_checklist_document_fails_closed(tmp_path):
    path = tmp_path / "wrong.md"
    path.write_text("- [ ] **SET-01** One item\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Expected 210"):
        checklist_requirements(path)


def test_removed_fault_variant_cannot_hide_behind_other_variants_of_same_case():
    from .manifest import all_scenarios, coverage_manifest, scenario_key
    scenarios = all_scenarios()
    removed = next(item for item in scenarios if scenario_key(item) == "API-11/provider_generated_request_id")
    report = coverage_manifest(item for item in scenarios if item is not removed)
    assert "API-11" not in report["unimplemented_cases"]
    assert report["implementation_complete"] is False
    assert any("API-11/provider_generated_request_id" in gap for gap in report["required_variant_gaps"])


def test_blocked_preparation_prevents_execution_completeness(tmp_path):
    manifest = {"variants": [], "unimplemented_cases": {}, "implementation_complete": True, "preparation_and_completion": {"SET-01": "Record baseline"}}
    report = render_report(tmp_path, manifest, {"cleanup_verified": True, "run_gate_evidence": {"SET-01": {"outcome": "Blocked"}}})
    assert report["execution_complete"] is False
    assert report["unrecorded_run_gates"] == ["SET-01"]


def test_recorded_failed_probe_is_executed_but_cannot_establish_readiness(tmp_path):
    manifest = {"variants": [], "unimplemented_cases": {}, "implementation_complete": True, "preparation_and_completion": {"DONE-02": "Both-store invariants"}}
    report = render_report(tmp_path, manifest, {"cleanup_verified": True, "run_gate_evidence": {"DONE-02": {"outcome": "Fail"}}})
    assert report["execution_complete"] is True
    assert report["readiness_pass"] is False


@pytest.mark.parametrize("provenance", [{"production_source_unchanged": False}, {"harness_changed_between_phases": True}])
def test_changed_source_or_harness_prevents_readiness(tmp_path, provenance):
    manifest = {"variants": [], "unimplemented_cases": {}, "implementation_complete": True}
    report = render_report(tmp_path, manifest, {"cleanup_verified": True, **provenance})
    assert report["readiness_pass"] is False


def test_reusing_run_artifacts_refuses_to_overwrite_an_earlier_failure(tmp_path):
    from types import SimpleNamespace
    from .runner import run_suite
    failed = tmp_path / "failed.json"
    failed.write_text('{"outcome":"Fail"}', encoding="utf-8")
    with pytest.raises(ValueError, match="fresh run ID"):
        run_suite(SimpleNamespace(artifacts_dir=tmp_path), SimpleNamespace())
    assert failed.read_text(encoding="utf-8") == '{"outcome":"Fail"}'


def case_evidence(root, key, phase, *, fault=False, action="early", parameters=None, events=None):
    import hashlib
    case, variant = key.split("/", 1)
    directory = root / "phases" / phase / "case_evidence" / hashlib.sha256(key.encode()).hexdigest()[:16]
    write_json(directory / "after.json", {"sha256": "raw-stores", "fixtures": {"sql": {}, "points": []}})
    write_json(directory / "cleanup.json", {"verified": True})
    module = "test_resilience.py" if fault else "test_scenarios.py"
    descriptor = {"key": key, "case_id": case, "variant_id": variant,
                  "pytest_node_id": f"tests/e2e/non_analysis/{module}::test_manifest_scenario[{key}]",
                  "action": action, "parameters": parameters or {}}
    record = {"key": key, "node_id": descriptor["pytest_node_id"], "outcome": "Pass", "file": phase + ".json",
              "attempt_phase": phase, "evidence_dir": str(directory), "phases": [{"phase": "call", "outcome": "passed"}]}
    if fault:
        write_json(root / "phases" / phase / "fault_evidence" / f"{case}-{variant}" / "settled.json",
                   {"stores": {"fixture": {"sql": None, "points": []}}, "schedule_events": events or []})
    return descriptor, record


def report_manifest(variants):
    return {"variants": variants, "unimplemented_cases": {}, "implementation_complete": True}


def test_setup_failures_remain_failures_but_never_count_as_execution(tmp_path):
    variant = {"key": "DEP-01/setup", "pytest_node_id": "test_resilience.py::case"}
    write_json(tmp_path / "cases/setup.json", {"key": variant["key"], "node_id": variant["pytest_node_id"],
               "outcome": "Fail", "file": "setup.json", "phases": [{"phase": "setup", "outcome": "failed"}]})
    manifest = {**report_manifest([variant]), "preparation_and_completion": {"DONE-01": "Calls", "DONE-03": "State", "SET-11": "Schedule"}}
    metadata = {"cleanup_verified": True, "resilience_repeats": 1}
    gates = run_gate_evidence(tmp_path, manifest, metadata)
    report = render_report(tmp_path, manifest, {**metadata, "run_gate_evidence": gates})
    assert report["outcomes"] == {"Fail": 1}
    assert report["not_executed_variants"] == ["DEP-01/setup"]
    assert report["execution_complete"] is False
    assert all(gate["outcome"] == "Blocked" for gate in gates.values())


def test_reached_real_store_call_requires_raw_final_state_and_exact_cleanup(tmp_path):
    variant, record = case_evidence(tmp_path, "ING-01/fixture", "02-core")
    write_json(tmp_path / "cases/one.json", record)
    metadata = {"profile": "core", "cleanup_verified": True, "production_source_unchanged": True, "harness_changed_between_phases": False}
    manifest = report_manifest([variant])
    assert render_report(tmp_path, manifest, metadata)["readiness_pass"] is True
    (Path(record["evidence_dir"]) / "after.json").unlink()
    write_json(Path(record["evidence_dir"]) / "cleanup.json", {"verified": False})
    report = render_report(tmp_path, manifest, metadata)
    assert report["execution_complete"] is False and report["readiness_pass"] is False
    assert len(report["missing_execution_evidence"][0]["issues"]) == 2


def test_fault_call_requires_its_actual_acknowledged_schedule(tmp_path):
    variant, record = case_evidence(tmp_path, "DEP-05/normalizer", "03-resilience", fault=True)
    manifest, metadata = report_manifest([variant]), {"profile": "resilience", "resilience_repeats": 1}
    missing = execution_evidence(tmp_path, manifest, metadata, [record])
    assert "required intervention phase was not acknowledged" in missing["missing_execution_evidence"][0]["issues"]
    variant, record = case_evidence(tmp_path, variant["key"], "03-resilience", fault=True, events=[{"kind": "fault_matched", "rule_id": "target"}])
    assert not execution_evidence(tmp_path, report_manifest([variant]), metadata, [record])["missing_execution_evidence"]


@pytest.mark.parametrize("action,parameters,events", [
    ("restart", {}, []),
    ("lock", {}, [{"operation": "sql.lock", "timing": "after", "lock_acquired": False}]),
    ("delete_no_qdrant", {}, [{"kind": "schedule_installed", "rule_ids": ["offline"]}, {"delegate_called": True}]),
    ("alias", {}, [{"kind": "alias_fault_installed", "acknowledged": True}, {"kind": "alias_restored", "acknowledged": True}, {"kind": "alias_fault_response", "status": 500}]),
])
def test_characterization_evidence_does_not_require_a_fictitious_matched_fault(tmp_path, action, parameters, events):
    variant, record = case_evidence(tmp_path, "FLOW-15/characterization", "03-resilience", fault=True,
                                    action=action, parameters=parameters, events=events)
    assert not execution_evidence(tmp_path, report_manifest([variant]), {}, [record])["missing_execution_evidence"]


def test_lost_acknowledgement_requires_actual_upstream_application(tmp_path):
    events = [{"kind": "fault_matched"}, {"kind": "upstream_outcome", "forwarded": True, "applied": False}]
    variant, record = case_evidence(tmp_path, "FLOW-14/lost", "03-resilience", fault=True, action="lost_http", events=events)
    assert execution_evidence(tmp_path, report_manifest([variant]), {}, [record])["missing_execution_evidence"]
    events[1]["applied"] = True
    variant, record = case_evidence(tmp_path, variant["key"], "03-resilience", fault=True, action="lost_http", events=events)
    assert not execution_evidence(tmp_path, report_manifest([variant]), {}, [record])["missing_execution_evidence"]


def test_wrong_alias_false_success_is_a_reached_product_failure_with_intervention_evidence(tmp_path):
    events = [{"kind": "alias_fault_installed", "acknowledged": True}, {"kind": "alias_restored", "acknowledged": True},
              {"kind": "alias_fault_response", "status": 201}]
    variant, record = case_evidence(tmp_path, "ING-F12/false-success", "03-resilience", fault=True, action="alias", events=events)
    record.update(outcome="Fail", phases=[{"phase": "call", "outcome": "failed"}])
    write_json(tmp_path / "cases/one.json", record)
    report = render_report(tmp_path, report_manifest([variant]), {"profile": "resilience", "resilience_repeats": 1, "cleanup_verified": True})
    assert report["outcomes"] == {"Fail": 1}
    assert report["execution_complete"] is True and not report["missing_execution_evidence"]
    assert report["readiness_pass"] is False


def test_duplicate_attempt_files_do_not_satisfy_distinct_resilience_repeats(tmp_path):
    variant, record = case_evidence(tmp_path, "DEP-05/repeat", "03-resilience", fault=True, events=[{"kind": "fault_matched"}])
    proof = execution_evidence(tmp_path, report_manifest([variant]), {"profile": "full", "resilience_repeats": 1}, [record] * 10)
    assert proof["missing_required_attempts"][variant["key"]] == {"required": 10, "executed": 1}


def canonical_fixture(root, name, config):
    directory = root / "phases" / name
    write_json(directory / "suite-manifest.json", {"harness_sha256": "approved"})
    write_json(directory / "fixture-registry.json", {"run_id": config["run_id"], "config": config})
    write_json(directory / "runner-config.json", {**{key: config.get(key) for key in ("run_id", "infrastructure", "stack_run_id")},
        "database": {key: {"env": key} for key in ("TEST_POSTGRES_SERVER", "TEST_POSTGRES_PORT", "TEST_POSTGRES_DB", "TEST_QDRANT_HOST", "TEST_QDRANT_PORT", "TEST_ENVIRONMENT_ID")}})
    return {"phase": name, "configuration": config}


def test_full_normal_coverage_needs_two_canonical_cores_and_verified_fresh_ownership(tmp_path):
    initial = {"run_id": "original", "infrastructure": "existing", "stack_run_id": None, "environment_id": "marked-original",
               "postgres_host": "127.0.0.1", "postgres_port": 7442, "qdrant_host": "127.0.0.1", "qdrant_port": 7343,
               "database": "tavanir_test_db", "collection": "test_physical", "alias": "test_active", "dense_dimension": 768,
               "dense_name": "dense", "sparse_name": "sparse"}
    fresh = {**initial, "run_id": "fresh-15", "infrastructure": "disposable", "stack_run_id": "fresh", "environment_id": "e2e-fresh",
             "postgres_port": 19442, "qdrant_port": 19343}
    labels = {"tavanir.environment": "test", "tavanir.e2e.run": "fresh"}
    compose = {"services": {"postgres": {"labels": labels, "ports": ["127.0.0.1:19442:5432"], "environment": {"TEST_ENVIRONMENT_ID": "e2e-fresh"}},
                            "qdrant": {"labels": labels, "ports": ["127.0.0.1:19343:6333"]}},
               "volumes": {"data": {"labels": labels}}, "networks": {"default": {"labels": labels}}}
    write_json(tmp_path / "reproduction/compose.json", compose)
    preflight = {"store_markers": "verified", "docker_ownership": "verified", "alias_dimension": "verified", "services": [{"container_id": "old-pg"}, {"container_id": "old-q"}]}
    metadata = {"profile": "full", "configuration": initial, "preflight": preflight, "cleanup_verified": True,
                "reproduction_preflight": {**preflight, "services": [{"container_id": "fresh-pg"}, {"container_id": "fresh-q"}]},
                "production_source_unchanged": True, "harness_changed_between_phases": False,
                "phases": [canonical_fixture(tmp_path, "15-core", fresh)]}
    variant, first = case_evidence(tmp_path, "API-11/late-added", "15-core")
    manifest = {**report_manifest([variant]), "harness_sha256": "approved"}
    write_json(tmp_path / "cases/first.json", first)
    report = render_report(tmp_path, manifest, metadata)
    assert report["execution_complete"] is False
    assert report["missing_canonical_normal_attempts"][variant["key"]]["executed"] == {"original": 0, "fresh": 1}
    metadata["phases"].append(canonical_fixture(tmp_path, "02-core", {**initial, "run_id": "original-02"}))
    write_json(tmp_path / "phases/02-core/suite-manifest.json", {"harness_sha256": "historical"})
    _, historical = case_evidence(tmp_path, variant["key"], "02-core")
    write_json(tmp_path / "cases/historical.json", historical)
    assert render_report(tmp_path, manifest, metadata)["execution_complete"] is False
    metadata["phases"].append(canonical_fixture(tmp_path, "16-core", {**initial, "run_id": "original-16"}))
    _, second = case_evidence(tmp_path, variant["key"], "16-core")
    write_json(tmp_path / "cases/second.json", second)
    assert render_report(tmp_path, manifest, metadata)["readiness_pass"] is True
    metadata["reproduction_preflight"]["docker_ownership"] = "unverified"
    report = render_report(tmp_path, manifest, metadata)
    assert report["readiness_pass"] is False
    assert report["canonical_phase_evidence"]["15-core"]["issues"]
