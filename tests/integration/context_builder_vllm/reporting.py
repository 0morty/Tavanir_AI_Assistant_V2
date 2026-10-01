"""Complete Markdown narrative plus directly inspectable JSON evidence."""
from __future__ import annotations

import json
from pathlib import Path

from .trace import json_text


def write_report(audit, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    events = audit.trace.events
    metadata = audit.trace.snapshot(audit.metadata)
    preflight = audit.trace.snapshot(audit.preflight)
    results = audit.trace.snapshot(audit.results)
    failures = audit.trace.snapshot(audit.failures)
    verification_file = directory / "regression_verification.json"
    regression = audit.trace.snapshot(json.loads(verification_file.read_text())) if verification_file.exists() else None
    document = {"regression_verification": regression, "metadata": metadata, "preflight": preflight, "status": audit.status,
                "results": results, "failures": failures, "events": events}
    (directory / "execution_trace.json").write_text(json_text(document) + "\n", encoding="utf-8")
    # Only real final wire calls belong in these artifacts. An unavailable server
    # produces an explicit empty list, never a stale or fabricated response.
    live = [(name, value) for name, value in results.items()
            if name.startswith("LIVE/") and "wire_request" in value]
    for filename, field in (("final_vllm_request.json", "wire_request"), ("final_vllm_response.json", "response")):
        artifact = {"status": ("EXECUTED" if all(value.get("inference") == "EXECUTED" for _, value in live) else "FAILED") if live else "NOT EXECUTED",
                    "reason": None if live else preflight.get("reason"),
                    "scenarios": [{"scenario": name, "status": value.get("inference"), "payload": value.get(field)} for name, value in live]}
        (directory / filename).write_text(json_text(artifact) + "\n", encoding="utf-8")
    with (directory / "full_pipeline_report.md").open("w", encoding="utf-8") as report:
        def write(text=""):
            report.write(text + "\n")

        def block(value):
            write("\n```json\n" + json_text(value) + "\n```\n")

        def selected(title, event_names):
            write("\n## " + title + "\n")
            found = False
            for event in events:
                if event["event"] in event_names:
                    found = True
                    write(f"### [{event['scenario']} — STEP {event['step']}](#step-{event['step']})\n")
                    block(event)
            if not found:
                write("No applicable events executed. See the preflight and scenario states for limitations.")

        write("# ContextBuilder → vLLM execution audit\n")
        write(f"**Overall status: {audit.status}**\n")
        write("## 1. Test Metadata\n")
        block(metadata)
        block(preflight)
        if regression is not None:
            write("Fresh related regression command and complete output (separate from the new audit):\n")
            block(regression)
        write("## 2. Test Objective\n")
        write("Validate deterministic, already-retrieved English evidence through real PromptBuilder, sections, "
              "allocation, fitting, ContextBuilderResult, LLMRequestBuilder and OpenAILLMClient. "
              "Retrieval, embeddings, ingestion, vector search and business decisions are excluded. "
              "CONTROLLED scenarios use an explicitly named HTTP double for reproducible transformations and "
              "wire serialization. LIVE scenarios use only the configured real vLLM provider. "
              "Controlled responses are never evidence of live model success.\n")
        write("## 3. Repository Components Under Test\n")
        functions = sorted({(e["component"], e["function"]) for e in events if e["event"] == "CALL"})
        for component, function in functions:
            write(f"- `{component}.{function}`")
        write("\nDiscovered auxiliary sections: ErrorSection and PropertiesSection support reference-template generation; SimilarSuggestionsSection has hardcoded Persian framing and is outside this English dataset. The exercised production sections are RoleSection, SystemInputSection, UserInputSection, OutputFormatSection, ChunksSection and HistorySection. The existing structlog setup is not used as a substitute for tracing. "
              "Test-only Python call/return tracing covers participating application functions, domain algorithms, "
              "references, tokenizer adapter and provider adapter. HTTP hooks capture the actual serialized payload. "
              "Trivial property accessors and comprehension frames are not separate trace steps; their values appear in the enclosing call/state/result. Third-party connection pools and tokenizer vocabulary internals are identified by type rather than traversed.\n")
        selected("4. Mock Dataset", {"SECTION_CREATED"})
        selected("5. Scenario Definition", {"SCENARIO"})
        write("\n## 6. Full Step-by-Step Execution Trace\n")
        write("Events are globally sequenced under a lock across the calling thread and provider loop. "
              "CALL carries arguments and configuration; RETURN carries output; constructor RETURN also captures initialized state. "
              "STATE contains changed locals before the displayed source line; unchanged variables retain their previous "
              "values in the same call. `call_id` and `parent_call_id` connect nested operations. SUSPEND/RESUME "
              "distinguish coroutine waiting from a completed return. Semantic accounting events include `source_step` "
              "when derived from an earlier observed transformation. Exceptions may be intentionally caught; consult "
              "EXPECTED_FAILURE and final scenario state before interpreting them as test failures.\n")
        for event in events:
            write(f"<a id=\"step-{event['step']}\"></a>\n\n### STEP {event['step']} — {event['event']}\n")
            block(event)
        selected("7. Allocation Trace", {"ALLOCATION_START", "ALLOCATION_DECISION", "TOKEN_ACCOUNTING"})
        selected("8. Overflow Trace", {"STRATEGY_SELECTED", "TRUNCATION_RESULT", "IGNORE_DECISION"})
        selected("9. Summarization Trace", {"SUMMARIZATION_MAPPING"})
        write("Single-text summary calls, chunk prompt construction, batching, retry state, complete input/output "
              "and HTTP envelopes also appear in section 6 under LLMSummarizer and LLMChunkSummarizer.\n")
        selected("10. ContextBuilderResult", {"CONTEXTBUILDER_RESULT"})
        selected("11. LLMRequestBuilder Trace", {"REQUEST_BUILD_START", "REQUEST_BUILT", "HISTORY_PROCESSING"})
        selected("12. vLLM Request", {"VLLM_REQUEST"})
        selected("13. vLLM Response", {"VLLM_RESPONSE", "HTTP_ERROR", "PREFLIGHT"})
        selected("14. Assertions", {"ASSERTION", "EXPECTED_FAILURE"})
        selected("15. Errors and Warnings", {"ERROR", "WARNING", "EXCEPTION", "HTTP_ERROR"})
        write("\n## 16. Detected Anomalies and Developer Findings\n")
        block(failures)
        write("- **Import probe:** see the fresh process output in metadata. At implementation time, importing `src.application.prompt.PromptBuilder` first in a fresh process raises an ImportError through the context package circular import. Importing context first works. The harness uses that existing initialization order; production code was not changed.\n"
              "- **Related regression evidence:** see the saved command and complete output above when available. At implementation time, five older collection tests expect uncited bodies, while current collection rendering adds Unique ID citation markers. The targeted regression run documents this contract mismatch separately from new harness results.\n"
              "- **Expected behavior:** collection TRUNCATE is a no-op; IGNORE retains an original prefix, "
              "including oldest history first. Truncation uses token offsets and never reconstructs text.\n"
              "- **Expected behavior:** ContextBuilder allocates once; redistribution can iterate. "
              "Restarted strategies reuse original prepared content, so unsuccessful summaries are discarded "
              "before the whole-item fallback. Exact inputs and discarded/retained items are in the trace.\n"
              "- **Contract ambiguity:** ContextBuilder's budget covers rendered text, not provider chat framing "
              "or completion tokens. Both counts are shown. A successful text-budget assertion alone does not prove "
              "the provider's context window fits.\n"
              "- **Potential defect:** chunk summarization capacity gates the operation but does not set per-item "
              "generation length. Oversized results may be rejected and original evidence dropped by fallback. "
              "This behavior is exposed rather than changed.\n"
              "- **Test limitation:** live summaries can vary even with temperature zero. Exact deterministic "
              "summary mapping is asserted in controlled runs; live runs assert boundaries and serialization.\n"
              "- **Test limitation:** LLM-generated reference templates are not used here; native/fallback "
              "deterministic references and citation injection are exercised. No unsupported tokenizer is substituted.\n"
              "- **Missing observability addressed:** test-only function/line tracing and HTTP hooks retain complete "
              "meaningful values. No production instrumentation or behavior changes were required.\n")
        write("\n## 17. Final Pipeline State\n")
        block({"status": audit.status, "preflight": preflight, "scenarios": results,
               "failures": failures})
