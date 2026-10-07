# LLM / Generation API test summary

**Updated:** 2026-10-07. Source now connects both Generation use cases through HTTP routes. Live endpoint-to-model readiness remains unverified. The current expansion prompt example disagrees with the strict parser markers; see the assessment below. The 2026-09-30 live run is retained as historical lower-level evidence, not rerun evidence for the current endpoints.

## Historical real ContextBuilder → vLLM run (2026-09-30)

The existing `tests.integration.context_builder_vllm.live_request` runner composed the production `PromptBuilder`, `ContextBuilder`, `LLMRequestBuilder`, `OpenAILLMClient`, and OpenAI-compatible client factory. It sent one actual `POST /v1/chat/completions` request to the locally running vLLM server. The runner used its artificial Northbridge evidence; it did not call the FastAPI endpoint, `AnalyzeSuggestionUseCase`, `GenerateSuggestionUseCase`, or `GenerationOutputParser`.

| Check | Result |
|---|---|
| Model actually served | `Qwen/Qwen2.5-0.5B-Instruct` from the local Qwen 0.5B assets |
| Endpoint and HTTP result | `http://127.0.0.1:8000/v1/chat/completions`; request body sent; HTTP 200; response ID `chatcmpl-8d34ec1c7008a1a3` |
| Request settings | Temperature 0.2, completion cap 48 tokens, no SDK retries |
| Final message roles | `system`, `user` history, `assistant` history, current `user` |
| Context fitting | 768-token rendered budget; 552 rendered tokens. `CHUNKS` requested 1,811 tokens, received 576, and fitted to 365; only `[chunk 001]` remained. |
| Local chat-template count | 566 input tokens; input plus 48-token completion allowance = 614, below the server's 1,024-token context limit |
| vLLM-reported usage | 566 prompt tokens, 34 completion tokens, 600 total tokens |
| Provider result | `finish_reason=stop`; response content matched the production client's extracted answer |
| Request integrity and latency | Recorded HTTP payload matched `LLMRequestBuilder` output; provider call took 18.197 seconds |

The complete generated answer was:

> The maintenance change that should be prioritized first is the relay calibration at Cedar substation, which has shown a reduction in nuisance trips from twelve to three per quarter.

The 0.5B model and 768/48 budgets were **process-only overrides** for this bounded local run. The project defaults in `src/infrastructure/configs/settings.py` remain Qwen 7B, a 4,096-token prompt budget, and a 4,096-token completion cap. The local server used the pinned `vllm/vllm-openai-cpu:v0.28.0` image with a 1,024-token maximum context, a 64-token batch-prefill limit, one sequence, and a 32 MiB KV cache. Its test-only container was stopped and removed after the run; the local model weights were preserved. The earlier 1.5B CPU attempt froze this host; it was not used for the successful run. Raw test reports, traces, and temporary test caches were removed during cleanup; the test runner and this summary remain.

## Current source and controlled-test assessment

| Scenario | Status / evidence boundary |
|---|---|
| Analyze generator handoff | Implemented: the real use case awaits `generator.execute` and maps answer, original cited IDs, uncertainty, and citation coverage. Unit tests exercise this handoff with an injected generator. |
| Analyze no evidence | Implemented diagnostic short-circuit; deliberately no LLM call. |
| Analyze HTTP contract | Presentation tests override the use case; they do not exercise real retrieval-to-Generation-to-provider wiring. |
| Expansion HTTP pipeline | Real router/use case/sections/ContextBuilder/request builder/parser with local Qwen tokenizer and mocked compatible-provider transport. Production lifespan and a live model are not exercised. |
| Expansion current marker agreement | **Mismatch:** working-tree output example uses Persian labels, while marker constants/parser expect English labels. A model following that example fails with `GENERATION_FAILED`. No source fix is made in this documentation task. |
| Provider adapter | Mock transport tests verify chat serialization/helper connection behavior; not real model quality or deployment availability. |
| Full model-context limit | Rendered prompt fitting exists; complete chat framing plus completion reserve is not automatically enforced against a model-window setting. |
| Regulations | DTO accepted; rendering/citations not connected; `appliedStatuteIds` empty. |
| Expansion mock mode | Existing mock overrides do not cover its use case; dedicated test overrides do not establish `IS_MOCK=True` parity. |
| Real full API and default provider/model | **Unverified.** Historical temporary 0.5B configuration does not validate the default Qwen 7B deployment. |

### Previously recorded controlled regression checks

The earlier expansion implementation/translation check passed **46 tests and 17 subtests** across its parser, use-case, and HTTP files. Adding chat-connection and exception-mapping tests previously passed **54 tests**. These are previous observations, not a fresh pass for the current uncommitted marker changes. A broader prior run reported 582 passes and one unrelated mutation-test failure caused by unavailable Redis; do not describe that run as fully green.

### Fresh focused checks (2026-10-07)

**Result:** 156 passed, 38 subtests passed, 1 failed in 12.78 seconds. The nine existing test files below were run in the isolated environment `/tmp/tavanir-idea-endpoint-venv`, with bytecode/cache generation disabled and a 120-second process limit. Providers were mocked; no live LLM request was made. Source and tests were not modified.

```bash
python -m pytest -p no:cacheprovider -q --tb=short \
  tests/unit/llm/test_structured_idea_output_parser.py \
  tests/unit/llm/test_structure_idea_use_case.py \
  tests/integration/presentation/test_structure_idea_api.py \
  tests/integration/test_generation_chat_connection.py \
  tests/unit/presentation/test_exception_mapping.py \
  tests/unit/application/use_cases/test_analyze_suggestion_use_case.py \
  tests/unit/llm/test_generation_output_parser.py \
  tests/unit/prompt/test_suggestion_prompt_preparer.py \
  tests/unit/llm/test_llm_request_builder_pipeline.py
```

The failure was `test_http_endpoint_invokes_provider_and_returns_five_parsed_fields` at `tests/integration/presentation/test_structure_idea_api.py:129`: its assertion that the provider system message contains `{title}` failed because the working-tree prompt uses `{عنوان}`. The mocked provider returns a fixed valid English-marked completion, so parsing/HTTP success alone does not detect this instruction disagreement. A real model following the translated markers would be rejected by the strict parser. This is an existing source-edit issue, left unchanged in this documentation-only task.

Documentation checks also passed: local Markdown file links resolve, `git diff --check` reports no whitespace errors, protected retrieval/upstream sections match the initial working tree, and all production Python source matches the task baseline.

A deployment readiness claim requires matching model/tokenizer/capacity and a real black-box HTTP request through each configured endpoint. Reuse existing Generation boundaries; do not change retrieval or unrelated services to close these checks. See the [implementation guide](llm_generation_api.md) and [Generation backlog](../next_steps.md).
