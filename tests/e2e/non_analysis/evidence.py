"""Durable sanitized evidence and truthful readiness/coverage reports."""

from __future__ import annotations

import hashlib
import json
import base64
from collections import Counter
from datetime import date, datetime
from pathlib import Path


def json_default(value):
    if isinstance(value, bytes):
        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"Unsupported evidence type: {type(value).__name__}")


def sanitize(value, secrets=()):
    sensitive = {"authorization", "api-key", "x-api-key", "password", "postgres_password", "qdrant_api_key", "api_key"}
    if isinstance(value, dict):
        return {str(key): "[REDACTED]" if str(key).lower() in sensitive else sanitize(item, secrets) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
    return value


def write_json(path: Path, value, secrets=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(sanitize(value, secrets), ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    temporary.replace(path)


def source_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((root / "src").rglob("*")):
        if path.is_file() and path.suffix in {".py", ".jinja2", ".js"}:
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def reached_call(record: dict) -> bool:
    return any(item.get("phase") == "call" and item.get("outcome") in {"passed", "failed"}
               for item in record.get("phases", []))


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _store_identity(config: dict) -> dict:
    fields = ("environment_id", "postgres_host", "postgres_port", "qdrant_host", "qdrant_port",
              "database", "collection", "alias", "dense_dimension", "dense_name", "sparse_name")
    return {key: config.get(key) for key in fields}


def _canonical_phase(artifacts: Path, name: str, manifest: dict, metadata: dict) -> tuple[str | None, list[str]]:
    """Prove canonical source, guarded identity, and fresh allocation from artifacts."""
    directory = artifacts / "phases" / name
    issues = []
    if "core" not in name.split("-")[1:]:
        return None, ["not a core phase"]
    phase_manifest = _read_json(directory / "suite-manifest.json") or {}
    if not manifest.get("harness_sha256") or phase_manifest.get("harness_sha256") != manifest["harness_sha256"]:
        issues.append("phase harness fingerprint differs from the approved final manifest")
    summary = next((item for item in metadata.get("phases", []) if item.get("phase") == name), {})
    configuration = summary.get("configuration", summary.get("phase_configuration", {}))
    registry = _read_json(directory / "fixture-registry.json") or {}
    private = _read_json(directory / "runner-config.json") or {}
    if not configuration or not configuration.get("environment_id") or _store_identity(registry.get("config", {})) != _store_identity(configuration):
        issues.append("phase configuration and fixture registry do not prove the same test store identity")
    guarded_bindings = ("TEST_POSTGRES_SERVER", "TEST_POSTGRES_PORT", "TEST_POSTGRES_DB", "TEST_QDRANT_HOST", "TEST_QDRANT_PORT", "TEST_ENVIRONMENT_ID")
    if (private.get("infrastructure") != configuration.get("infrastructure") or private.get("stack_run_id") != configuration.get("stack_run_id")
        or private.get("run_id") != registry.get("run_id") or registry.get("run_id") != configuration.get("run_id")
        or any(private.get("database", {}).get(key) != {"env": key} for key in guarded_bindings)):
        issues.append("runner configuration does not agree with phase ownership")
    initial = metadata.get("configuration", {})
    preflight = metadata.get("preflight", {})
    if _store_identity(configuration) == _store_identity(initial) and initial.get("environment_id"):
        if preflight.get("store_markers") != "verified" or preflight.get("docker_ownership") != "verified":
            issues.append("original guarded store preflight is absent")
        return (None if issues else "original"), issues
    owner = configuration.get("stack_run_id")
    fresh = metadata.get("reproduction_preflight", {})
    compose = _read_json(artifacts / "reproduction" / "compose.json") or {}
    labels = {"tavanir.environment": "test", "tavanir.e2e.run": owner}
    services = compose.get("services", {})
    owned = (configuration.get("infrastructure") == "disposable" and bool(owner)
             and configuration.get("environment_id") == f"e2e-{owner}"
             and configuration.get("environment_id") != initial.get("environment_id")
             and set(services) == {"postgres", "qdrant"}
             and all(all(item.get("labels", {}).get(key) == value for key, value in labels.items()) for item in services.values())
             and services.get("postgres", {}).get("environment", {}).get("TEST_ENVIRONMENT_ID") == configuration.get("environment_id")
             and services.get("postgres", {}).get("ports") == [f"127.0.0.1:{configuration.get('postgres_port')}:5432"]
             and f"127.0.0.1:{configuration.get('qdrant_port')}:6333" in services.get("qdrant", {}).get("ports", [])
             and bool(compose.get("volumes")) and bool(compose.get("networks"))
             and all(all(item.get("labels", {}).get(key) == value for key, value in labels.items())
                     for item in [*compose.get("volumes", {}).values(), *compose.get("networks", {}).values()]))
    initial_ids = {item.get("container_id") for item in preflight.get("services", [])}
    fresh_ids = {item.get("container_id") for item in fresh.get("services", [])}
    verified = (fresh.get("store_markers") == fresh.get("docker_ownership") == fresh.get("alias_dimension") == "verified"
                and len(initial_ids) == len(fresh_ids) == 2 and None not in initial_ids | fresh_ids and not fresh_ids.intersection(initial_ids))
    if not owned or not verified:
        issues.append("fresh disposable stack allocation, labels, ports, or independent verified service identities are absent")
    return (None if issues else "fresh"), issues


def execution_evidence(artifacts: Path, manifest: dict, metadata: dict, records: list[dict]) -> dict:
    """Execution is a reached test body plus its required durable evidence."""
    variants = {item["key"]: item for item in manifest["variants"]}
    attempted = {}
    gaps, phase_proofs, canonical = [], {}, {}
    for record in records:
        key = record.get("key")
        if key not in variants or record.get("outcome") not in {"Pass", "Fail"} or not reached_call(record):
            continue
        variant = variants[key]
        phase = record.get("attempt_phase", artifacts.name)
        attempted.setdefault(key, set()).add(phase)
        node = variant.get("pytest_node_id", record.get("node_id", ""))
        real = "test_scenarios.py::" in node or "test_resilience.py::" in node
        issues = []
        if real:
            directory = Path(record.get("evidence_dir") or artifacts / "phases" / phase / "case_evidence" / hashlib.sha256(key.encode()).hexdigest()[:16])
            if not directory.resolve().is_relative_to(artifacts.resolve()):
                issues.append("case evidence directory is outside this run")
            else:
                after, cleanup = _read_json(directory / "after.json"), _read_json(directory / "cleanup.json")
                fixtures = (after or {}).get("fixtures", {})
                if not isinstance(after, dict) or not after.get("sha256") or not isinstance(fixtures.get("sql"), dict) or not isinstance(fixtures.get("points"), list):
                    issues.append("raw final SQL and paginated vector evidence is missing")
                if not isinstance(cleanup, dict) or cleanup.get("verified") is not True:
                    issues.append("exact case cleanup evidence is missing or unverified")
        if "test_resilience.py::" in node:
            fault_dir = artifacts / "phases" / phase / "fault_evidence" / f"{variant.get('case_id')}-{variant.get('variant_id')}"
            if not fault_dir.exists() and artifacts.name == phase:
                fault_dir = artifacts / "fault_evidence" / f"{variant.get('case_id')}-{variant.get('variant_id')}"
            captures = [_read_json(path) for path in fault_dir.glob("*.json")]
            captures = [item for item in captures if isinstance(item, dict)]
            events = [event for item in captures for event in item.get("schedule_events", [])]
            if not captures or not all(isinstance(item.get("stores"), dict) for item in captures):
                issues.append("fault schedule and committed/compensated store captures are missing")
            action, params = variant.get("action"), variant.get("parameters", {})
            exception = action in {"restart", "sql_only_conflict"} or action == "debug" and params.get("category") == "validation" or action == "provider" and params.get("fault") == "unreachable"
            matched = any(event.get("kind") == "fault_matched" for event in events)
            if action == "alias":
                matched = all(any(event.get("kind") == kind and event.get("acknowledged") is True for event in events)
                              for kind in ("alias_fault_installed", "alias_restored")) and any(event.get("kind") == "alias_fault_response" and type(event.get("status")) is int and 100 <= event["status"] <= 599 for event in events)
            elif action == "lock" or action == "bulk_fault" and params.get("fault") == "lock":
                matched = any(event.get("operation") == "sql.lock" and event.get("timing") == "after" and event.get("lock_acquired") is False for event in events)
            elif action in {"delete_no_provider", "delete_no_qdrant"}:
                matched = any(event.get("kind") == "schedule_installed" and event.get("rule_ids") for event in events) and any(event.get("delegate_called") is True for event in events)
            elif action == "debug" and params.get("category") == "provider":
                matched = any(event.get("kind") == "proxy_error" for event in events)
            if not exception and not matched:
                issues.append("required intervention phase was not acknowledged")
            if action == "lost_http" or action == "external_qdrant" and params.get("lost"):
                if not any(event.get("kind") == "upstream_outcome" and event.get("forwarded") is True and event.get("applied") is True for event in events):
                    issues.append("lost acknowledgement lacks actual upstream application proof")
        if issues:
            gaps.append({"key": key, "phase": phase, "issues": issues})
        if metadata.get("profile") == "full" and "test_scenarios.py::" in node:
            if phase not in phase_proofs:
                phase_proofs[phase] = _canonical_phase(artifacts, phase, manifest, metadata)
            kind, proof_issues = phase_proofs[phase]
            if kind and not issues:
                canonical.setdefault(key, {}).setdefault(kind, set()).add(phase)
    not_run = [key for key in variants if key not in attempted]
    repeats = {}
    for key, variant in variants.items():
        if metadata.get("profile") in {"full", "resilience"} and "test_resilience.py::" in variant.get("pytest_node_id", ""):
            required = max(10 if metadata.get("profile") == "full" else 1, metadata.get("resilience_repeats", 10))
            count = len(attempted.get(key, ()))
            if count < required:
                repeats[key] = {"required": required, "executed": count}
    normal_gaps = {}
    if metadata.get("profile") == "full":
        for key, variant in variants.items():
            if "test_scenarios.py::" in variant.get("pytest_node_id", ""):
                proof = canonical.get(key, {})
                if not proof.get("original") or not proof.get("fresh"):
                    normal_gaps[key] = {"required": {"original": 1, "fresh": 1},
                                        "executed": {kind: len(proof.get(kind, ())) for kind in ("original", "fresh")}}
    return {"not_executed_variants": not_run, "missing_required_attempts": repeats,
            "missing_execution_evidence": gaps, "missing_canonical_normal_attempts": normal_gaps,
            "canonical_phase_evidence": {phase: {"kind": kind, "issues": issues} for phase, (kind, issues) in phase_proofs.items()}}


def run_gate_evidence(artifacts: Path, manifest: dict, metadata: dict) -> dict:
    """Trace the 18 run-level requirements separately from executable variants."""
    records = [json.loads(path.read_text(encoding="utf-8")) for path in (artifacts / "cases").glob("*.json")]
    execution = execution_evidence(artifacts, manifest, metadata, records)
    covered = not any(execution[key] for key in ("not_executed_variants", "missing_required_attempts", "missing_execution_evidence", "missing_canonical_normal_attempts"))
    phases = metadata.get("phases", [])
    preflight = metadata.get("preflight", {})
    dependency = metadata.get("dependency_preflight", {})
    config = metadata.get("configuration", {})
    process_files = list((artifacts / "phases").glob("*/process-events.ndjson"))
    events = [json.loads(line) for path in process_files for line in path.read_text(encoding="utf-8").splitlines() if line]
    baseline = list((artifacts / "phases").glob("*/sentinel-baseline.json"))
    http_files = list((artifacts / "phases").glob("*/http.ndjson"))
    from urllib.parse import unquote, urlsplit
    requests = [json.loads(line) for path in http_files for line in path.read_text(encoding="utf-8").splitlines() if line]
    prohibited = False
    for item in requests:
        path = urlsplit(item.get("path", "")).path
        for _ in range(3):
            path = unquote(path)
        prohibited |= path.rstrip("/").lower() in {"/api/v1/suggestions/analyze", "/api/v1/suggestions/generate"}
    cleanup = metadata.get("cleanup_verified") is True
    faults = any(reached_call(item) and "test_resilience.py::" in item.get("node_id", "") for item in records)
    fault_keys = {item["key"] for item in manifest["variants"] if "test_resilience.py::" in item.get("pytest_node_id", "")}
    fault_gaps = [item for item in execution["missing_execution_evidence"] if item["key"] in fault_keys]
    failed = any(item["outcome"] == "Fail" for item in records)
    def phase_index(item):
        value = item.get("attempt_phase", "").split("-", 1)[0]
        return int(value) if value.isdigit() else -1
    last_fault_phase = max((phase_index(item) for item in records if "test_resilience.py::" in item.get("node_id", "")), default=-1)
    recovered = any(item["outcome"] == "Pass" and reached_call(item) and item.get("key", "").startswith("FLOW-15/")
                    and phase_index(item) > last_fault_phase
                    and (metadata.get("profile") != "full" or execution["canonical_phase_evidence"].get(item.get("attempt_phase"), {}).get("kind") == "original")
                    and not any(gap["key"] == item.get("key") and gap["phase"] == item.get("attempt_phase") for gap in execution["missing_execution_evidence"])
                    for item in records)
    gates = {}
    def record(key, condition, detail, links, *, false="Blocked"):
        gates[key] = {"outcome": "Pass" if condition else false, "detail": detail, "evidence": links}
    record("SET-01", bool(metadata.get("commit") and metadata.get("started_utc") and metadata.get("executor") and config and dependency.get("package_versions")), "Commit, executor, dates, source fingerprint, working-tree differences and versions are retained; owned host addresses are in process records.", ["metadata.json", "phases/*/process-events.ndjson"])
    record("SET-02", any(item.get("event") == "ready" and item.get("mock_mode") is False for item in events), "Real hosts verify root metadata and normal lifespan before tests.", ["phases/*/process-events.ndjson", "phases/*/http.ndjson"])
    record("SET-03", preflight.get("store_markers") == "verified" and dependency.get("embedding_dimension") == config.get("dense_dimension"), "Migrated SQL, guarded stores, real embedding dimension and model are checked independently.", ["metadata.json"])
    record("SET-04", bool(config.get("alias") and config.get("collection") and (artifacts / "seed-export.json").exists()), "Raw readers verify the alias target on every capture and seed export detects drift.", ["metadata.json", "seed-export.json"])
    record("SET-05", preflight.get("alias_dimension") == "verified", "Configured dense/sparse names and dimension are checked against Qdrant.", ["metadata.json"])
    record("SET-06", bool(http_files), "Isolated authentication settings are injected before imports; requests and configured secret values are sanitized.", ["phases/*/http.ndjson", "phases/*/runner-config.json"])
    record("SET-07", bool(list((artifacts / "phases").glob("*/fixture-registry.json"))), "Exact IDs and proved-absent boundary claims are journaled before mutations.", ["phases/*/fixture-registry.json", "phases/*/before-cleanup-*.json"])
    record("SET-08", bool(baseline) and cleanup, "All original SQL, suggestion vectors and regulatory vectors are immutable sentinels checked after each case.", ["phases/*/sentinel-baseline.json", "phases/*/case_evidence/*/cleanup.json"], false="Fail")
    record("SET-09", bool(dependency.get("runtime_settings")), "Effective batch sizes, SDK/Qdrant retries, timeouts and cutover delays are recorded without secrets.", ["metadata.json"])
    record("SET-10", dependency.get("local_tokenizer_assets") == "verified", "Local tokenizer assets and normal startup resources are verified without invoking analysis.", ["metadata.json", "phases/*/application-*.log"])
    record("SET-11", faults and not fault_gaps, "Reached fault calls retain action-specific acknowledged schedules, application state and operation outcomes; no-dependency characterizations do not require an invented fault match.", ["phases/*/fault_evidence/", "phases/*/faults/", "phases/*/observations.ndjson"])
    record("SET-12", bool(metadata.get("latency_policy")), "Durations are measured; no endpoint SLA or recovery deadline is invented.", ["metadata.json", "phases/*/http.ndjson"])
    record("DONE-01", covered and manifest["implementation_complete"], "Every mapped variant reaches its test call with durable evidence. Full runs require ten resilience phases and canonical core outcomes on original and independently owned fresh test stores.", ["manifest.json", "results.json", "coverage.csv"])
    record("DONE-02", covered and cleanup and not failed, "Successful mutation invariants are tested independently. Failed probes remain failures and prevent readiness.", ["results.json", "phases/*/case_evidence/*/after.json"], false="Fail")
    record("DONE-03", any(reached_call(item) for item in records) and not execution["missing_execution_evidence"], "Reached real-store attempts retain raw final SQL/vectors, exact cleanup, and required fault application evidence; setup failures remain explicit nonexecuted outcomes.", ["results.json", "phases/*/case_evidence/*/after.json", "phases/*/fault_evidence/", "findings.md"])
    record("DONE-04", cleanup, "Exact registered SQL rows and all vector lifecycle states are removed; shared sentinels and existing test services are preserved.", ["metadata.json", "phases/*/cleanup.json", "phases/*/fixture-registry.json"], false="Fail")
    record("DONE-05", recovered and cleanup and any(item["phase"].endswith("resilience") for item in phases), "Fault finalizers release barriers/locks and restore owned processes; subsequent healthy mutations and persistence are tested.", ["phases/*/process-events.ndjson", "results.json"], false="Blocked")
    record("DONE-06", bool(requests) and not prohibited, "Recorded requests exclude analysis/generation; mock and real-store evidence are separate and only executed cases receive outcomes.", ["phases/*/http.ndjson", "results.json"], false="Fail")
    return {key: gates[key] for key in manifest.get("preparation_and_completion", {})}


def render_report(artifacts: Path, manifest: dict, metadata: dict) -> dict:
    results = []
    for path in sorted((artifacts / "cases").glob("*.json")):
        results.append(json.loads(path.read_text(encoding="utf-8")))
    outcomes = Counter(item["outcome"] for item in results)
    execution = execution_evidence(artifacts, manifest, metadata, results)
    not_run, repeat_gaps = execution["not_executed_variants"], execution["missing_required_attempts"]
    evidence_complete = not execution["missing_execution_evidence"] and not execution["missing_canonical_normal_attempts"]
    gates = metadata.get("run_gate_evidence", {})
    unrecorded_gates = [key for key in manifest.get("preparation_and_completion", {}) if key not in gates or gates[key].get("outcome") == "Blocked"]
    report = {
        "metadata": metadata,
        "outcomes": dict(outcomes),
        "results": results,
        "unimplemented_cases": manifest["unimplemented_cases"],
        **execution,
        "run_gate_evidence": gates,
        "unrecorded_run_gates": unrecorded_gates,
        "implementation_complete": manifest["implementation_complete"],
        "execution_complete": not not_run and not repeat_gaps and evidence_complete and not unrecorded_gates and manifest["implementation_complete"] and metadata.get("cleanup_verified") is True,
        "readiness_pass": not outcomes.get("Fail") and not outcomes.get("Blocked") and not not_run and not repeat_gaps and evidence_complete and not unrecorded_gates and not any(item.get("outcome") == "Fail" for item in gates.values()) and manifest["implementation_complete"] and metadata.get("cleanup_verified") is True and metadata.get("production_source_unchanged") is True and metadata.get("harness_changed_between_phases") is False,
    }
    write_json(artifacts / "results.json", report)
    lines = ["# Non-analysis E2E evidence", "", f"Run: `{metadata.get('run_id')}`", f"Application commit: `{metadata.get('commit')}`", f"Production source fingerprint unchanged: `{metadata.get('production_source_unchanged')}`", "", f"Outcomes: {dict(outcomes)}", f"Implementation complete: {report['implementation_complete']}", f"Execution complete: {report['execution_complete']}", f"Readiness pass: {report['readiness_pass']}", "", "Known failures remain failures. A characterized behavior does not establish consistency.", "", "| Case / variant | Outcome | Evidence |", "| --- | --- | --- |"]
    for item in results:
        lines.append(f"| {item.get('key', item.get('node_id'))} | {item['outcome']} | [record](cases/{item['file']}) |")
    lines.extend(["", "## Preparation and completion evidence", "", "| Case | Outcome | Evidence |", "| --- | --- | --- |"])
    for key in manifest.get("preparation_and_completion", {}):
        gate = gates.get(key, {})
        links = "; ".join(f"`{value}`" for value in gate.get("evidence", []))
        lines.append(f"| {key} | {gate.get('outcome', 'Not recorded')} | {gate.get('detail', '')} {links} |")
    lines.extend(["", "## Unexecuted coverage", "", f"{len(not_run)} mapped variants were not executed.", ""])
    lines.append(f"{len(repeat_gaps)} resilience variants lack required distinct-phase attempts; {len(execution['missing_canonical_normal_attempts'])} normal variants lack canonical original/fresh core outcomes.")
    lines.append(f"{len(execution['missing_execution_evidence'])} reached attempts lack mandatory execution evidence.")
    for gap in execution["missing_execution_evidence"]:
        lines.append(f"- {gap['phase']} / {gap['key']}: {'; '.join(gap['issues'])}")
    for key, requirement in manifest["unimplemented_cases"].items():
        lines.append(f"- **{key}**: no executable scenario. {requirement}")
    for gap in manifest.get("required_variant_gaps", []):
        lines.append(f"- Required variant gap: {gap}")
    (artifacts / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    matrix = ["case_id,variant_id,profile,pytest_node_id,outcome"]
    lookup = {}
    severity = {"Pass": 0, "Blocked": 1, "Fail": 2}
    for item in results:
        key, value = item.get("key"), item["outcome"]
        if key not in lookup or severity.get(value, 1) > severity.get(lookup[key], 1):
            lookup[key] = value
    for item in manifest["variants"]:
        matrix.append(",".join(str(item.get(field, "")) for field in ("case_id", "variant_id", "profile", "pytest_node_id")) + "," + lookup.get(item["key"], "Not run"))
    (artifacts / "coverage.csv").write_text("\n".join(matrix) + "\n", encoding="utf-8")
    return report
