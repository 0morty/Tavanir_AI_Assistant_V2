# Next steps: LLM / Generation API

**Updated:** 2026-10-07. This is a Generation-only backlog. The two final-answer pipelines are implemented; the remaining work is validation and the gaps below. Retrieval implementation is outside this document's scope.

## Completed baseline, verified from source

- Analyze injects and awaits `GenerateSuggestionUseCase`, which prepares sections/context, constructs chat messages, invokes the shared LLM client, and parses its JSON output against the fitted citation map.
- The response maps the generated answer to `analysis`, exposes unique `citedSuggestionIds` and `uncertainty`, and keeps existing candidate lists separate. `groundingRatio` measures citation coverage, not calibrated confidence. The no-evidence path deliberately skips Generation and returns diagnostic text.
- `POST /api/v1/suggestions/expand-suggestion` accepts one description of at most 512 model tokens and runs `PromptBuilder/Sections → ContextBuilder → LLMRequestBuilder → LLM → StructuredIdeaOutputParser`, returning five parsed fields in the existing JSON envelope.
- Generation adapters, tokenizer resources, parsers, use-case providers, and HTTP error mappings are wired in the composition root. Static prompts live in configuration dataclasses.

See the [implementation guide](documentation/llm_generation_api.md) and [dated test evidence](documentation/llm_generation_test_summary.md). Do not recreate these abstractions or repeat the completed Analyze handoff.

## 1. Reconcile the expansion output markers

**Observed working-tree issue:** The uncommitted output example now contains Persian markers; `IDEA_OUTPUT_MARKERS` and the parser still expect `{title}`, `{current problem}`, `{solutions}`, `{advantage}`, `{disadvantage}`. A model following the example fails the strict parser.

**Recommendation:** Preserve the original machine-readable English markers and `***` separators while keeping Persian instructions/content. Change Generation source only in a separately authorized implementation task. Verify prompt configuration, parser, and HTTP success together; do not silently accept alternate markers or return raw output.

**Done when:** The model instruction and strict parser agree on the original ordered marker contract, with focused tests passing.

## 2. Verify real API-to-provider behavior

Run controlled Generation tests first, then a black-box request through each real HTTP route with matching provider/model/tokenizer configuration. For Analyze, use prepared evidence at the upstream interface or a provisioned existing environment; do not change retrieval to facilitate testing.

Record the selected model, tokenizer, final message roles, input/completion usage, latency, parsed result, HTTP fields, and failure mappings. Cover expansion's 512/513-token boundary, Persian ideas, essential-section overflow, and malformed output; cover Analyze's cited-ID mapping and deliberate no-evidence outcome. Existing mocked transports and the historical lower-level 0.5B run are not real endpoint-to-model evidence.

**Done when:** Both live request paths produce validated responses, and configuration/capacity limitations are explicitly recorded.

## 3. Account for the full model context window

Current budgets limit rendered context; `LLM_MAX_TOKENS` separately caps output. Add a model-context check for rendered content plus chat-template/special-token overhead and completion reserve at the existing Generation boundary. Keep allocation and overflow processing in ContextBuilder; use the served model's compatible tokenizer.

**Done when:** Every emitted chat request fits the configured model context window including reserved output, with meaningful boundary tests.

## 4. Render and cite supplied regulation evidence

`GenerationInput.regulations` and `RegulationInput` exist, but `SuggestionPromptPreparer` does not render them and `appliedStatuteIds` stays empty. If statutory analysis is required, implement a Generation-owned referenced regulation section with a distinct citation label, retained direct map, and appropriate budget/overflow policy. Derive public statute IDs only from validated cited regulation objects.

Any missing upstream evidence feed is a cross-scope dependency to report, not retrieval work to perform here. An empty statute list does not establish a completed legal review.

**Done when:** Already-supplied regulations appear in fitted context and resolve through validated citations, or the dependency remains explicitly documented.

## 5. Define final-output retry and observability policy

Final parsers currently raise typed failures immediately; OpenAI SDK transport retries, reference-template retries, and batch-helper fallback are separate mechanisms. If malformed-output retries are required, design a bounded injected policy without duplicating provider/context behavior. Keep private input/raw completions out of routine logs. Extend Generation metrics for provider usage, latency, failure type, retries, and cancellation only where required.

**Done when:** The agreed policy has predictable HTTP outcomes and bounded resource use, with tests through existing seams.

## 6. Resolve expansion mock-mode support

The existing mock overrides omit `structure_idea_use_case`; mock lifespan skips real resource initialization. Its dedicated HTTP tests explicitly override the needed resources, which does not prove `IS_MOCK=True` support.

Report the shared mock/lifespan dependency before changing ownership-restricted files, or explicitly authorize the smallest Generation-only override. Do not alter authentication or unrelated mocked use cases.

**Done when:** The advertised mock mode supports expansion through initialized fakes, or its limitation is explicit to callers.

## Change boundaries

Follow [AGENTS.md](../AGENTS.md): define ports, inject required runtime collaborators, compose in `src/containers.py`, and verify their use. Only the Generation tail of mixed Analyze code belongs to this work. Preserve direct `citation_id → original item` mapping and separate Analyze's JSON completion from expansion's marked plain-text completion. Do not change retrieval, reranking, embeddings, storage, ingestion, security, or deployment as part of this backlog.
