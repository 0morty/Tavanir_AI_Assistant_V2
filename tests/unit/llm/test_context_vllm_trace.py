"""Guard the audit itself against misleading, lossy or secret-bearing output."""
import json
import sys
import threading

import pytest

from tests.integration.context_builder_vllm.trace import TraceCollector
from src.application.context.sections import UserInputSection
from src.application.prompt import PromptBuilder


def test_trace_redacts_nested_secrets_and_preserves_full_content():
    trace = TraceCollector(secrets=("secret-value",))
    content = "English evidence with meaningful detail. " * 100
    event = trace.emit("TEST", body={"authorization": "Bearer secret-value", "nested": {"api_key": "secret-value"},
                                  "content": content, "error": "token secret-value rejected"})
    encoded = json.dumps(event)
    assert "secret-value" not in encoded
    assert event["body"]["content"] == content
    assert event["body"]["nested"]["api_key"] == "[REDACTED]"


def test_instrumentation_observes_actual_calls_and_restores_hooks_after_failure():
    trace = TraceCollector()
    old_sys, old_thread = sys.gettrace(), threading.gettrace()
    with pytest.raises(ValueError, match="probe"):
        with trace.instrument():
            builder = PromptBuilder([UserInputSection("Complete evidence")], seed_defaults=False)
            assert builder.render() == "Complete evidence"
            raise ValueError("probe")
    assert sys.gettrace() is old_sys
    assert threading.gettrace() is old_thread
    assert any(e["event"] == "CALL" and e["function"] == "PromptBuilder.render" for e in trace.events)
    assert any(e["event"] == "RETURN" and e.get("result") == "Complete evidence" for e in trace.events)
    assert [e["step"] for e in trace.events] == list(range(1, len(trace.events)+1))


def test_trace_snapshot_does_not_change_when_source_mutates():
    trace = TraceCollector()
    value = {"chunks": ["Evidence A"]}
    trace.emit("INPUT", value=value)
    value["chunks"].append("Evidence B")
    assert trace.events[0]["value"] == {"chunks": ["Evidence A"]}


def test_failed_assertion_is_recorded_before_raising():
    trace = TraceCollector()
    with pytest.raises(AssertionError):
        trace.check("capacity", 11, 10)
    assert trace.events[-1]["status"] == "FAIL"
    assert trace.events[-1]["expected"] == 10
    assert trace.events[-1]["actual"] == 11


def test_thread_events_have_unique_ordered_sequences():
    trace = TraceCollector()
    threads = [threading.Thread(target=lambda: [trace.emit("THREAD") for _ in range(25)]) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [e["step"] for e in trace.events] == list(range(1, 101))


def test_report_clears_stale_live_artifacts_and_keeps_all_sections(tmp_path):
    from types import SimpleNamespace
    from tests.integration.context_builder_vllm.reporting import write_report

    trace = TraceCollector()
    trace.emit("WARNING", reason="Provider unavailable")
    audit = SimpleNamespace(trace=trace, metadata={}, preflight={"ready": False, "reason": "Connection refused"},
                            results={}, failures=[], status="PARTIAL: live inference NOT EXECUTED")
    (tmp_path / "final_vllm_response.json").write_text('{"stale": "old response"}')
    write_report(audit, tmp_path)
    response = json.loads((tmp_path / "final_vllm_response.json").read_text())
    assert response["status"] == "NOT EXECUTED"
    assert response["scenarios"] == []
    assert "stale" not in response
    report = (tmp_path / "full_pipeline_report.md").read_text()
    assert report.count("\n## ") == 17
    assert "STEP 1" in report
    assert "Provider unavailable" in report
    assert json.loads((tmp_path / "execution_trace.json").read_text())["events"] == trace.events


def test_report_retains_failed_real_wire_attempts(tmp_path):
    from types import SimpleNamespace
    from tests.integration.context_builder_vllm.reporting import write_report

    audit = SimpleNamespace(trace=TraceCollector(), metadata={}, preflight={"ready": True},
                            results={"LIVE/A": {"inference": "FAILED", "wire_request": {"messages": []}}},
                            failures=[{"error": "Timeout"}], status="FAILED")
    write_report(audit, tmp_path)
    request = json.loads((tmp_path / "final_vllm_request.json").read_text())
    assert request["status"] == "FAILED"
    assert request["scenarios"][0]["payload"] == {"messages": []}
    response = json.loads((tmp_path / "final_vllm_response.json").read_text())
    assert response["scenarios"][0]["payload"] is None


def test_report_redacts_secrets_in_live_response_artifacts(tmp_path):
    from types import SimpleNamespace
    from tests.integration.context_builder_vllm.reporting import write_report

    audit = SimpleNamespace(trace=TraceCollector(secrets=("private-key-value",)), metadata={},
                            preflight={"ready": True}, failures=[], status="PASS",
                            results={"LIVE/A": {"inference": "EXECUTED", "wire_request": {"messages": []},
                                                "response": {"content": "Echo private-key-value", "api_key": "private-key-value"}}})
    write_report(audit, tmp_path)
    for path in tmp_path.iterdir():
        assert "private-key-value" not in path.read_text()
