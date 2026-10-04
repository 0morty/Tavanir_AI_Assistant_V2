"""Checklist-to-executable traceability, with explicit incomplete coverage gates."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, is_dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CHECKLIST = ROOT / "docs/planning/non_analysis_api_e2e_test_checklist.md"
CASE_PATTERN = re.compile(r"^- \[ \] \*\*([A-Z]+-(?:F)?\d+)\b[^*]*\*\*\s*(.*)$", re.MULTILINE)


def checklist_requirements(path: Path = CHECKLIST) -> dict[str, str]:
    requirements = dict(CASE_PATTERN.findall(path.read_text(encoding="utf-8")))
    if len(requirements) != 210:
        raise ValueError(f"Expected 210 checklist requirements; found {len(requirements)}")
    return requirements


def scenario_key(scenario) -> str:
    return f"{scenario.case_id}/{scenario.variant_id}"


def harness_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.iterdir()):
        if path.is_file() and path.suffix in {".py", ".json"}:
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def all_scenarios():
    from .scenarios import NORMAL_SCENARIOS
    try:
        from .resilience import RESILIENCE_SCENARIOS
    except ImportError:
        RESILIENCE_SCENARIOS = ()
    try:
        from .mock_scenarios import MOCK_SCENARIOS
    except ImportError:
        MOCK_SCENARIOS = ()
    return (*NORMAL_SCENARIOS, *RESILIENCE_SCENARIOS, *MOCK_SCENARIOS)


def coverage_manifest(scenarios=None) -> dict:
    requirements = checklist_requirements()
    scenarios = tuple(all_scenarios() if scenarios is None else scenarios)
    from .scenarios import NORMAL_SCENARIOS
    normal_keys = {scenario_key(item) for item in NORMAL_SCENARIOS}
    variants = []
    seen = set()
    for scenario in scenarios:
        key = scenario_key(scenario)
        if key in seen:
            raise ValueError(f"Duplicate manifest variant: {key}")
        if scenario.case_id not in requirements:
            raise ValueError(f"Unknown checklist case: {scenario.case_id}")
        seen.add(key)
        data = asdict(scenario) if is_dataclass(scenario) else vars(scenario)
        module = "test_scenarios" if key in normal_keys else "test_resilience"
        if str(data.get("profile", "")) == "mock":
            module = "test_mock_scenarios"
        variants.append({
            **data,
            "key": key,
            "requirement": requirements[scenario.case_id],
            "pytest_node_id": f"tests/e2e/non_analysis/{module}.py::test_manifest_scenario[{key}]",
            "evidence_requirements": ["HTTP request/response", "SQL and paginated vectors", "sentinel preservation", "exact fixture cleanup"],
        })
    preparation = [key for key in requirements if key.startswith(("SET-", "DONE-"))]
    mapped = {item["case_id"] for item in variants}
    missing = sorted(set(requirements) - mapped - set(preparation))
    from .test_scenario_controls import validate_required_normal_variants
    required_variant_gaps = list(validate_required_normal_variants(tuple(item for item in scenarios if scenario_key(item) in normal_keys)))
    import json
    approved = json.loads((Path(__file__).parent / "required_fault_variants.json").read_text(encoding="utf-8"))
    expected_fault_keys = set(approved["required_resilience_keys"]) | set(approved["required_mock_keys"])
    required_variant_gaps += [f"Missing approved fault/mock variant: {key}" for key in sorted(expected_fault_keys - seen)]
    return {
        "schema_version": 1,
        "checklist_sha256": hashlib.sha256(CHECKLIST.read_bytes()).hexdigest(),
        "harness_sha256": harness_fingerprint(),
        "case_count": len(requirements),
        "variant_count": len(variants),
        "preparation_and_completion": {key: requirements[key] for key in preparation},
        "variants": variants,
        "unimplemented_cases": {key: requirements[key] for key in missing},
        "required_variant_gaps": required_variant_gaps,
        "implementation_complete": not missing and not required_variant_gaps,
    }


def validate_collection(manifest: dict, node_ids: list[str]) -> None:
    actual = set(node_ids)
    expected = {item["pytest_node_id"] for item in manifest["variants"]}
    missing = expected - actual
    unexpected = actual - expected
    if missing or unexpected:
        raise ValueError(f"Manifest collection mismatch: {len(missing)} missing, {len(unexpected)} unexpected")
