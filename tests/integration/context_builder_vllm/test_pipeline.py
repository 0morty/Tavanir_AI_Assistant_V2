"""Run with CONTEXT_VLLM_LIVE=1 to include the configured real provider."""
import os
from pathlib import Path

import pytest

from .harness import PipelineAudit
from .reporting import write_report
from .scenarios import SCENARIOS
from .trace import ROOT


@pytest.fixture(scope="module")
def audit():
    if os.environ.get("PYTEST_XDIST_WORKER"):
        pytest.fail("Run the audit serially (-n 0): global function tracing and report ownership require one process")
    runner = PipelineAudit(live=os.environ.get("CONTEXT_VLLM_LIVE") == "1")
    directory = Path(os.environ.get("CONTEXT_VLLM_REPORT_DIR", ROOT / "tests/reports/context_builder_vllm"))
    try:
        runner.run()
    finally:
        write_report(runner, directory)
    return runner


@pytest.mark.parametrize("name", SCENARIOS)
def test_controlled_pipeline(audit, name):
    state = audit.results["CONTROLLED/" + name]
    assert state["status"] == "PASS", state.get("error")


def test_expected_failures_are_isolated(audit):
    assert not [f for f in audit.failures if f["scenario"].startswith("NEGATIVE/")]
    expected = {e["scenario"] for e in audit.trace.events if e["event"] == "EXPECTED_FAILURE"}
    assert expected == {"NEGATIVE/" + name for name in
                        ("invalid_section", "impossible_budget", "tokenizer_failure", "unavailable",
                         "invalid_response", "empty_summary", "batch_404_fallback")}


def test_live_vllm_pipeline(audit):
    if not audit.preflight["ready"]:
        pytest.skip(f"vLLM inference NOT EXECUTED: {audit.preflight['reason']}")
    states = [state for key, state in audit.results.items() if key.startswith("LIVE/")]
    assert len(states) == len(SCENARIOS)
    assert all(state["status"] == "PASS" for state in states)
    assert any(state["inference"] == "EXECUTED" for state in states)
    assert audit.status == "PASS"
