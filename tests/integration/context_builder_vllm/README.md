# ContextBuilder → vLLM audit

Start with [Understanding the test results](../../reports/context_builder_vllm/human_readable_results.md)
for a plain-English explanation of the saved run, actual examples, and remaining
limitations. The full report is the detailed evidence archive.

Run from the repository root, using a Python environment containing the project's
Generation dependencies (`pytest`, `pytest-asyncio`, `openai`, `httpx`,
`pydantic-settings`, `Jinja2==3.1.6`, `transformers==4.57.1`). No retrieval services are needed.

```bash
python -m pytest -q tests/unit/llm/test_context_vllm_trace.py
CONTEXT_VLLM_LIVE=1 python -m pytest -q tests/integration/context_builder_vllm/test_pipeline.py
```

Run serially, without coverage or debugger tracing. Full value tracing takes
longer than ordinary tests and intentionally produces large artifacts. An xdist
worker is rejected to prevent concurrent report writes.

The harness uses the existing `LLMSettings` and `GenerationSettings`, including
the repository `.env` file and process environment. Configure `VLLM_HOST`,
`VLLM_PORT`, `VLLM_API_KEY`, `LLM_MODEL`, `LLM_TIMEOUT`, `TOKENIZER_MODEL` and
`MAX_RETRIES` through those existing settings. No machine-specific alternate
endpoint or model is selected. The local fast tokenizer is loaded exactly as
the production composition root loads it: `use_fast=True`,
`local_files_only=True`, wrapped in `QwenTokenizer`.

Test generation uses temperature `0.0` and a documented 96-token output cap;
chunk summarization uses batches of two and two attempts. These are test-level
configuration values passed through production constructor seams. English
prompt overrides prevent the production summarizers' Persian defaults from
entering this test. No production source is patched or modified.

`CONTEXT_VLLM_LIVE=1` first queries `/v1/models`. A connection failure or missing
configured model still runs all controlled scenarios, writes reports, and marks
the live pytest case **SKIPPED** and the report **PARTIAL**. Controlled HTTP
responses never count as successful real inference. Without that environment
variable, ordinary test-suite runs use controlled provider calls only.

The 19 scenarios cover A–J, including exact/±1 token boundaries, empty sections,
single-character/token content, zero capacity and unusual section order. Failure
probes cover bad configuration, tokenizer exceptions, provider failures,
malformed responses, empty-summary retries and batch-endpoint fallback.

Artifacts default to `tests/reports/context_builder_vllm/`. Override the directory
with `CONTEXT_VLLM_REPORT_DIR` for CI or separate runs:

- `full_pipeline_report.md`: all 17 requested report sections, complete ordered
  function/state/HTTP trace and assertions.
- `execution_trace.json`: metadata, scenario results and every trace event.
- `final_vllm_request.json`, `final_vllm_response.json`: actual successful live
  final calls, or explicit `NOT EXECUTED` documents. Controlled wire calls and
  all summary calls remain available in the trace.

The report explains production contracts that differ from a generic RAG prompt:
collection truncation is a no-op; IGNORE keeps an original prefix; history stays
as separate chat messages; user input is grouped separately from system content;
the context text budget excludes provider chat-template and output tokens.

Read `STATE` as the changed local values immediately before its displayed source
line. CALL and RETURN carry complete arguments and results; `call_id` joins them.
Semantic accounting records point back to their observed operation via
`source_step`. Exceptions raised and caught as part of fallback/reference
generation remain visible. Authorization headers and configured API keys are
redacted; full English evidence and transformations are retained.

## Real request after critical fixes

Read [Critical fixes and the real vLLM attempt](../../reports/context_builder_vllm/critical_fixes/results.md)
for the latest fix verification and actual connection failure. The earlier
human-readable guide describes the original saved run.

To execute a real completion using all configured generation parameters:

```bash
python -m tests.integration.context_builder_vllm.live_request
```

This command always attempts inference and exits with an error if it fails.
It does not skip after a failed preflight or use a controlled provider. Complete
messages, token accounting, transport evidence, response and generated output
are written under `tests/reports/context_builder_vllm/live_validation/`.
