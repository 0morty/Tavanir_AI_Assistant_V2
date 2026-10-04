"""Reproducible guarded non-analysis E2E execution and evidence commands."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import importlib.metadata
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .config import E2EConfig, ROOT
from .evidence import render_report, run_gate_evidence, source_fingerprint, write_json
from .manifest import coverage_manifest


def _recovery_config(config, target, directory):
    """Reconstruct only persisted nonsecret settings; store guards prove them."""
    required = {"run_id", "infrastructure", "stack_run_id", "postgres_port", "qdrant_port", "database", "environment_id", "postgres_host", "qdrant_host", "dense_dimension", "dense_name", "sparse_name", "startup_timeout", "request_timeout", "python_executable"}
    if not isinstance(target, dict) or not required.issubset(target):
        raise ValueError("Interrupted target configuration is incomplete")
    database = replace(config.database, pg_host=target["postgres_host"], pg_port=target["postgres_port"], pg_database=target["database"],
                       q_host=target["qdrant_host"], q_port=target["qdrant_port"], environment_id=target["environment_id"])
    recovered = replace(config, database=database, artifacts_dir=directory,
                        **{key: target[key] for key in ("run_id", "infrastructure", "stack_run_id", "dense_dimension", "dense_name", "sparse_name", "startup_timeout", "request_timeout", "python_executable")})
    if recovered.redacted() != target:
        raise ValueError("Interrupted target configuration does not match supported guarded settings")
    return recovered


def _recovery_infrastructure(config):
    from .infrastructure import ManagedTestInfrastructure
    infrastructure = ManagedTestInfrastructure(config)
    if config.infrastructure == "disposable":
        owner = config.stack_run_id or config.run_id
        for directory in (config.artifacts_dir, *config.artifacts_dir.parents):
            for candidate in (directory / "compose.json", directory / "reproduction" / "compose.json"):
                if candidate.is_file():
                    document = json.loads(candidate.read_text(encoding="utf-8"))
                    labels = [service.get("labels", {}) for service in document.get("services", {}).values()]
                    if len(labels) == 2 and all(item.get("tavanir.e2e.run") == owner and item.get("tavanir.environment") == "test" for item in labels):
                        infrastructure = ManagedTestInfrastructure(replace(config, artifacts_dir=candidate.parent))
                        config = replace(infrastructure.recover(), artifacts_dir=config.artifacts_dir)
                        infrastructure.verify()
                        return config, infrastructure
        raise RuntimeError("Exact run-owned Compose manifest was not found for interrupted cleanup")
    infrastructure.verify()
    return config, infrastructure


def _settle_phase(config):
    from .harness import recover_and_stop, recover_owned_pytest
    phase_proof = config.artifacts_dir / "owned-pytest-process.json"
    if not phase_proof.is_file():
        raise RuntimeError("Verified pytest process proof is required before interrupted cleanup")
    result = {"pytest": recover_owned_pytest(config), "applications": []}
    for path in config.artifacts_dir.rglob("owned-processes.json"):
        result["applications"].append(recover_and_stop(config, path.parent))
    if (config.artifacts_dir / "fixture-registry.json").is_file() and not result["applications"]:
        raise RuntimeError("Verified app process evidence is required before interrupted fixture cleanup")
    return result


def _run_exit_code(profile, codes, metadata, report):
    valid = codes and all(code == 0 for code in codes) and metadata["cleanup_verified"] and metadata["production_source_unchanged"] and not metadata["harness_changed_between_phases"]
    if profile == "full":
        valid = valid and report["readiness_pass"] is True
    return 0 if valid else 1


def _revision(root):
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _environment(config):
    return {**os.environ, **config.database.compose_environment(), **config.application_environment(), "E2E_RUN_API_KEY": config.api_key, "E2E_ENFORCE_MANIFEST": "1"}


def _private_config(config, path):
    data = {
        "database": {key: {"env": key} for key in config.database.compose_environment()},
        "infrastructure": config.infrastructure,
        "stack_run_id": config.stack_run_id,
        "run_id": config.run_id,
        "api_key": {"env": "E2E_RUN_API_KEY"},
        "api_header": config.api_header,
        "dense_dimension": config.dense_dimension,
        "dense_name": config.dense_name,
        "sparse_name": config.sparse_name,
        "embedding": {key: {"env": key} for key in config.embedding_environment},
        "startup_timeout": config.startup_timeout,
        "request_timeout": config.request_timeout,
        "shutdown_timeout": config.shutdown_timeout,
        "artifacts_dir": str(config.artifacts_dir),
        "python_executable": config.python_executable,
    }
    write_json(path, data)


def dependency_preflight(config):
    """Read-only readiness beyond liveness: provider shape and local tokenizer."""
    import httpx
    packages = ("fastapi", "uvicorn", "httpx", "openai", "qdrant-client", "SQLAlchemy", "asyncpg", "transformers", "pytest", "dependency-injector")
    versions = {name: importlib.metadata.version(name) for name in packages}
    installed_versions = dict(sorted((distribution.metadata["Name"], distribution.version) for distribution in importlib.metadata.distributions() if distribution.metadata.get("Name")))
    values = config.embedding_environment
    provider = values.get("EMBEDDING_PROVIDER", "tei").lower().strip()
    if provider not in {"tei", "vllm"}:
        raise ValueError("Unsupported embedding provider in E2E preflight")
    stem = provider.upper()
    host = values.get(stem + "_HOST", "localhost")
    port = int(values.get(stem + "_PORT", "8080" if provider == "tei" else "8000"))
    url = f"http://{host}:{port}/v1/embeddings"
    model = values.get("EMBEDDING_MODEL", "google/embedding-gemma-2b")
    with httpx.Client(timeout=config.request_timeout, trust_env=False) as client:
        response = client.post(url, headers={"Authorization": "Bearer " + values.get(stem + "_API_KEY", "EMPTY")}, json={"model": model, "input": ["بررسی زیرساخت آزمایش پیشنهادهای توانیر"]})
        response.raise_for_status()
        entries = response.json()["data"]
        if len(entries) != 1 or len(entries[0]["embedding"]) != config.dense_dimension:
            raise AssertionError("Live embedding provider dimension is incompatible with destination")
    probe = (
        "import json; "
        "from src.infrastructure.configs.settings import generation_settings, embedding_settings, qdrant_settings, llm_settings, security_settings; "
        "from transformers import AutoTokenizer; "
        "AutoTokenizer.from_pretrained(generation_settings.TOKENIZER_MODEL, use_fast=True, local_files_only=True); "
        "print('LOCAL_TOKENIZER_READY'); "
        "print('E2E_RUNTIME_SETTINGS=' + json.dumps({"
        "'api_header': security_settings.API_KEY_NAME, "
        "'embedding_batch_size': embedding_settings.EMBEDDING_BATCH_SIZE, "
        "'embedding_timeout': embedding_settings.EMBEDDING_TIMEOUT, "
        "'sdk_max_retries': llm_settings.MAX_RETRIES, "
        "'qdrant_batch_size': qdrant_settings.QDRANT_BATCH_SIZE, "
        "'qdrant_max_retries': qdrant_settings.QDRANT_MAX_RETRIES, "
        "'qdrant_retry_base_delay': qdrant_settings.QDRANT_RETRY_BASE_DELAY, "
        "'qdrant_retry_max_delay': qdrant_settings.QDRANT_RETRY_MAX_DELAY, "
        "'update_cutover_attempts': 3, 'update_cutover_delays': [0.2, 0.4]}))"
    )
    from .harness import run_owned_preparation
    output = run_owned_preparation(config, ["-c", probe], label="tokenizer-probe", environment=_environment(config),
                                   timeout=config.startup_timeout, expected_script_sha256=hashlib.sha256(probe.encode("utf-8")).hexdigest())
    if "LOCAL_TOKENIZER_READY" not in output:
        raise RuntimeError("Local tokenizer readiness failed before application startup")
    runtime = next((json.loads(line.split("=", 1)[1]) for line in output.splitlines() if line.startswith("E2E_RUNTIME_SETTINGS=")), None)
    if runtime is None:
        raise RuntimeError("Runtime settings evidence was not captured")
    return {"package_versions": versions, "installed_package_versions": installed_versions, "runtime_settings": runtime, "embedding_provider": provider, "embedding_model": model, "embedding_dimension": config.dense_dimension, "local_tokenizer_assets": "verified", "requirements_sha256": hashlib.sha256((config.repo_root / "requirements.txt").read_bytes()).hexdigest()}


def export_seed(config, *, sample_size=100):
    """Read-only qualified sample of marked test background; never seed live data."""
    from .infrastructure import ManagedTestInfrastructure
    from .oracles import RawStoreOracle, assert_consistent, digest
    from .sample import select_representative_sample

    infrastructure = ManagedTestInfrastructure(config)
    infrastructure.verify()
    oracle = RawStoreOracle(config)
    before = oracle.all_snapshot()
    by_parent = defaultdict(list)
    for point in before["points"]:
        by_parent[point["payload"]["parent_id"]].append(point)
    groups, exclusions = defaultdict(list), []
    rows = before["sql"].values() if isinstance(before["sql"], dict) else before["sql"]
    for row in rows:
        snapshot = {"sql": row, "points": by_parent.get(row["id"], [])}
        try:
            assert_consistent(snapshot, config)
            if row["is_deleted"]:
                exclusions.append({"id": row["id"], "reason": "soft-deleted background record"})
                continue
            groups[row["status_id"]].append(snapshot)
        except AssertionError as exc:
            exclusions.append({"id": row["id"], "reason": str(exc)})
    selection = select_representative_sample((snapshot for records in groups.values() for snapshot in records), sample_size=sample_size)
    after = oracle.all_snapshot()
    if digest(before) != digest(after):
        raise RuntimeError("Seed export drifted between raw cross-store captures")
    report = {**selection, "source": "guarded test databases", "excluded": exclusions, "before_sha256": digest(before), "after_sha256": digest(after), "alias": config.alias}
    write_json(config.artifacts_dir / "seed-export.json", report, config.secrets())
    print(json.dumps({key: value for key, value in report.items() if key != "records"}, ensure_ascii=False))
    return report


def cleanup(config, artifact_root=None):
    from .oracles import FixtureRegistry, RawStoreOracle, assert_unchanged
    root = Path(artifact_root or config.artifacts_dir)
    journals = list(root.rglob("fixture-registry.json"))
    phase_paths = {path.parent for path in root.rglob("owned-pytest-process.json")}
    if any(not (path.parent / "owned-pytest-process.json").is_file() for path in root.rglob("pytest-arguments.json")):
        raise RuntimeError("Pytest ownership proof was lost; refusing interrupted cleanup")
    for journal in journals:
        directory = next((item for item in (journal.parent, *journal.parent.parents) if item in phase_paths), None)
        if directory is None:
            raise RuntimeError("Verified pytest process proof is required before interrupted fixture cleanup")
    phases, stacks = {}, {}
    for directory in sorted(phase_paths):
        proof = json.loads((directory / "owned-pytest-process.json").read_text(encoding="utf-8"))
        phase_config = _recovery_config(config, proof.get("target"), directory)
        phase_config, infrastructure = _recovery_infrastructure(phase_config)
        if phase_config.redacted() != proof["target"]:
            raise RuntimeError("Verified store configuration differs from interrupted pytest target")
        phases[directory] = (phase_config, infrastructure)
        stacks[(phase_config.infrastructure, infrastructure.owner_run_id)] = infrastructure
    # Settle every phase and app host before any raw writes across mixed stacks.
    settled = [_settle_phase(phase_config) for phase_config, _ in phases.values()]
    cleaned = []
    for journal in journals:
        data = json.loads(journal.read_text(encoding="utf-8"))
        ids = data.get("ids", []) if isinstance(data, dict) else data
        if not isinstance(ids, list) or not all(isinstance(value, str) for value in ids):
            raise ValueError("Invalid exact fixture registry")
        directory = next(item for item in (journal.parent, *journal.parent.parents) if item in phases)
        phase_config, infrastructure = phases[directory]
        journal_config = replace(phase_config, artifacts_dir=journal.parent)
        baseline_path = journal.parent / "sentinel-baseline.json"
        if not baseline_path.is_file():
            raise RuntimeError("Sentinel baseline is missing; refusing interrupted fixture cleanup")
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        registry = FixtureRegistry.from_journal(journal_config, data, sentinel_ids=baseline.get("sql", {}))
        oracle = RawStoreOracle(journal_config, verify_ownership=infrastructure.verify)
        oracle.cleanup(registry)
        if baseline:
            assert_unchanged(baseline, oracle.all_snapshot())
        cleaned.extend(ids)
        write_json(journal, {**data, "ids": [], "claims": {}, "cleanup_verified": True})
    if not stacks:
        _, infrastructure = _recovery_infrastructure(config)
        stacks[(config.infrastructure, infrastructure.owner_run_id)] = infrastructure
    removed = [infrastructure.cleanup() for infrastructure in stacks.values()]
    write_json(root / "cleanup.json", {"verified": True, "cleaned_exact_ids": cleaned, "settled_processes": settled, "infrastructure": removed})
    print(f"Verified cleanup of {len(cleaned)} exact registered fixture identifiers.")


def run_suite(config, args):
    from .infrastructure import ManagedTestInfrastructure

    artifacts = config.artifacts_dir
    if artifacts.exists() and any(artifacts.iterdir()):
        raise ValueError("Run artifacts already exist; choose a fresh run ID to preserve every previous attempt")
    artifacts.mkdir(parents=True, exist_ok=True)
    initial_fingerprint = source_fingerprint(config.repo_root)
    manifest = coverage_manifest()
    write_json(artifacts / "manifest.json", manifest)
    write_json(artifacts / "initial-manifest.json", manifest)
    metadata = {"run_id": config.run_id, "commit": _revision(config.repo_root), "started_utc": datetime.now(timezone.utc).isoformat(), "seed": args.seed, "resilience_repeats": args.resilience_repeats, "profile": args.profile, "configuration": config.redacted(), "production_source_before": initial_fingerprint}
    metadata["executor"] = "Codex automated non-analysis E2E harness"
    metadata["application_worktree_changes"] = subprocess.run(["git", "diff", "--name-only", "HEAD", "--", "src"], cwd=config.repo_root, capture_output=True, text=True, check=True).stdout.splitlines()
    metadata["latency_policy"] = "Record measurements; no endpoint SLA or recovery deadline was supplied."
    write_json(artifacts / "metadata.json", metadata)
    infrastructure = ManagedTestInfrastructure(config)
    phase_reports, codes, phase_configs = [], [], []
    owned_infrastructure = [infrastructure]
    try:
        config = infrastructure.provision()
        metadata["preflight"] = infrastructure.readiness()
        metadata["dependency_preflight"] = dependency_preflight(config)
        metadata["seeding"] = infrastructure.seed_if_empty(live_embeddings=False)
        export_seed(config)
        phases = [args.profile]
        if args.profile == "full":
            phases = ["smoke", "core"] + ["resilience"] * args.resilience_repeats + ["mock", "smoke", "core"]
        elif args.profile == "resilience":
            phases = ["resilience"] * args.resilience_repeats
        for index, profile in enumerate(phases, start=1):
            if args.profile == "full" and index == len(phases) - 1:
                reproduction = replace(config, run_id=f"{config.run_id[:24]}-repro", stack_run_id=f"{config.run_id[:24]}-repro", artifacts_dir=artifacts / "reproduction", infrastructure="disposable")
                reproduction_infrastructure = ManagedTestInfrastructure(reproduction)
                owned_infrastructure.append(reproduction_infrastructure)
                config = reproduction_infrastructure.provision()
                metadata["reproduction_preflight"] = reproduction_infrastructure.readiness()
                metadata["reproduction_seeding"] = reproduction_infrastructure.seed_if_empty(live_embeddings=False)
            phase_name = f"{index:02d}-{profile}"
            phase_dir = artifacts / "phases" / phase_name
            phase_config = replace(config, run_id=f"{config.run_id[:27]}-{index:02d}", artifacts_dir=phase_dir)
            phase_configs.append(phase_config)
            phase_dir.mkdir(parents=True, exist_ok=True)
            config_file = phase_dir / "runner-config.json"
            _private_config(phase_config, config_file)
            arguments = ["tests/e2e/non_analysis", "--run-db-tests", "--run-non-analysis-e2e", "--strict-markers", "--e2e-profile", profile, "--e2e-config", str(config_file), "--e2e-run-id", phase_config.run_id, "--e2e-artifacts", str(phase_dir), "--e2e-seed", str(args.seed + index - 1), "--junitxml", str(phase_dir / "junit.xml"), "-q", "-r", "a"]
            print(f"Starting {phase_name}, run {phase_config.run_id}", flush=True)
            with (phase_dir / "pytest.log").open("w", encoding="utf-8") as output:
                try:
                    # Every request/barrier is bounded separately. This protects
                    # against a faulty test/teardown hanging the entire runner.
                    budget = max(600, len(manifest["variants"]) * 180)
                    from .harness import run_owned_pytest
                    code = run_owned_pytest(phase_config, arguments, output=output, environment=_environment(phase_config), timeout=budget)
                except subprocess.TimeoutExpired:
                    code = 2
                    write_json(phase_dir / "deadline.json", {"expired": True, "seconds": budget})
                    _settle_phase(phase_config)
                    cleanup(phase_config, artifact_root=phase_dir)
            codes.append(code)
            phase_metadata = {**metadata, "run_id": phase_config.run_id, "profile": profile, "pytest_exit_code": code}
            phase_metadata["cleanup_verified"] = not list(phase_dir.rglob("fixture-registry.json")) or all(json.loads(path.read_text(encoding="utf-8")).get("cleanup_verified", False) for path in phase_dir.rglob("fixture-registry.json"))
            phase = render_report(phase_dir, manifest, phase_metadata)
            phase_reports.append({"phase": phase_name, "phase_configuration": phase_config.redacted(), "exit_code": code, "outcomes": phase["outcomes"], "cleanup_verified": phase_metadata["cleanup_verified"]})
            print(f"Finished {phase_name}: {phase['outcomes']}; pytest exit {code}", flush=True)
            # Failed product assertions retain evidence and do not stop remaining
            # variants. A broken setup or cleanup stops further shared writes.
            if code in {2, 3, 4, 5} or not phase_metadata["cleanup_verified"]:
                break
    except Exception as exc:
        metadata["blocker"] = sanitize_exception(exc, config)
        print(metadata["blocker"], file=sys.stderr, flush=True)
        codes.append(2)
    finally:
        metadata["production_source_unchanged"] = source_fingerprint(config.repo_root) == initial_fingerprint
        metadata["phases"] = phase_reports
        metadata["cleanup_verified"] = all(item["cleanup_verified"] for item in phase_reports) and bool(phase_reports)
        metadata["finished_utc"] = datetime.now(timezone.utc).isoformat()
        try:
            for phase_config in reversed(phase_configs):
                _settle_phase(phase_config)
            for owned in reversed(owned_infrastructure):
                owned.cleanup()
        except Exception as exc:
            metadata["infrastructure_cleanup_error"] = sanitize_exception(exc, config)
            metadata["cleanup_verified"] = False
            codes.append(2)
        write_json(artifacts / "metadata.json", metadata, config.secrets())
        # Aggregate every attempt; later passes never erase an earlier failure.
        aggregate_cases = artifacts / "cases"
        aggregate_cases.mkdir(exist_ok=True)
        for path in sorted((artifacts / "phases").glob("*/cases/*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            record["attempt_phase"] = path.parents[1].name
            destination = aggregate_cases / f"{path.parents[1].name}-{path.name}"
            record["file"] = destination.name
            write_json(destination, record)
        phase_manifests = sorted((artifacts / "phases").glob("*/suite-manifest.json"))
        if phase_manifests:
            manifest = json.loads(phase_manifests[-1].read_text(encoding="utf-8"))
            write_json(artifacts / "manifest.json", manifest)
        metadata["harness_phase_fingerprints"] = [{"phase": path.parent.name, "sha256": json.loads(path.read_text(encoding="utf-8")).get("harness_sha256")} for path in phase_manifests]
        fingerprints = {item["sha256"] for item in metadata["harness_phase_fingerprints"] if item["sha256"]}
        metadata["harness_changed_between_phases"] = len(fingerprints) > 1
        metadata["run_gate_evidence"] = run_gate_evidence(artifacts, manifest, metadata)
        write_json(artifacts / "run-gate-evidence.json", metadata["run_gate_evidence"])
        write_json(artifacts / "metadata.json", metadata, config.secrets())
        report = render_report(artifacts, manifest, metadata)
        print(f"Evidence: {artifacts / 'report.md'}", flush=True)
    return _run_exit_code(args.profile, codes, metadata, report)


def sanitize_exception(exc, config):
    message = f"{type(exc).__name__}: {exc}"
    for secret in config.secrets():
        message = message.replace(secret, "[REDACTED]")
    return message


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "export-seed", "cleanup", "manifest"))
    parser.add_argument("--config")
    parser.add_argument("--profile", choices=("smoke", "core", "resilience", "mock", "full"), default="full")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--resilience-repeats", type=int, default=10)
    parser.add_argument("--run-id")
    parser.add_argument("--artifacts-dir", type=Path)
    args = parser.parse_args(argv)
    if not 1 <= args.resilience_repeats <= 100:
        parser.error("Resilience repeats must be between 1 and 100")
    config = E2EConfig.load(args.config)
    changes = {key: value for key, value in {"run_id": args.run_id, "artifacts_dir": args.artifacts_dir}.items() if value is not None}
    if args.run_id and args.artifacts_dir is None:
        changes["artifacts_dir"] = config.repo_root / "tests/e2e/reports" / args.run_id
    if changes:
        config = replace(config, **changes)
    if args.command == "run":
        return run_suite(config, args)
    if args.command == "export-seed":
        export_seed(config)
    elif args.command == "cleanup":
        cleanup(config)
    else:
        write_json(config.artifacts_dir / "manifest.json", coverage_manifest())
        print(f"Manifest: {config.artifacts_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
