# Real-vLLM Batch End-to-End Test

Primary objective: prove the **real batch architecture** end to end.

```text
chunk-1 ─┐    build ─┐
chunk-2 ─┼─► (independent) ─┼─► 3 final prompts ─► ONE complete_many batch ─► vLLM
chunk-3 ─┘    build ─┘                                              (batch POST, 3 items)
                                                                         │
                                                         3 responses ←───┘
                                                         (mapped by batch index)
```

Secondary objective: prove the **hard-cut problem is gone** — vLLM is served
with `max_model_len=4096` and `LLM_MAX_TOKENS` is generous enough that neither
the chunk-2 summarization nor any final completion is artificially truncated
(every choice returns `finish_reason == "stop"`).

The whole experiment lives in this one directory. Delete it when you are done.

## Files

| File | Purpose |
|---|---|
| `mock_chunks.md` | The three long English mock chunks, unmodified (source of truth) |
| `vllm_test_common.py` | Shared compose helpers (tokenizer adapter, builder construction, real-class composition) — no production code is touched |
| `budget_probe.py` | Token-math probe that derives the per-chunk budgets and headroom checks |
| `test_pipeline.py` | The pipeline runner + wire-level HTTP recorder (AsyncOpenAI `post`/`create`) + report |
| `summarize_experiment.py` | Deterministic capacity-investigation experiment (no inference) |
| `summarize_investigation_report.md` | Findings: `SUMMARIZE` length is bounded by `LLM_MAX_TOKENS`, capacity only gates |
| `test_report.md` | Generated batch-focused report (sections A–H) |
| `README.md` | This file |

## Pipeline

- Each chunk gets its **own** independent `PromptBuilder` and its own
  `ContextBuilder.build` (never merged).
- Per-chunk token budgets (derived in `budget_probe.py`, refined on the real
  run): `chunk-1=300` (capacity ~217 → **TRUNCATE**), `chunk-2=460`
  (capacity ~377 → **SUMMARIZE** via real vLLM), `chunk-3=510`
  (capacity 416 → **no overflow**, full pass-through). The pipeline prints the
  exact capacities for each run (they shift slightly with the prompt templates).
- The three final prompts become `[{"role": "user", "content": <prompt>}]`
  conversations and are submitted through **one**
  `OpenAILLMClient.complete_many(prompts)` call → `POST /v1/chat/completions/batch`
  with exactly **3 items**; the response maps each choice by its `index`.
- The shared AsyncOpenAI instance is wrapped at the `post` / `chat.completions.create`
  seam to capture the *actual* HTTP payload, item counts, elapsed time and
  per-choice `finish_reason` (the summarization call shows up as a separate
  1-item batch).

## Environment knobs for the real run

- `LLM_MODEL` — must equal the vLLM-served model id (e.g. `/models/LLM`).
- `LLM_MAX_TOKENS` — output cap per completion (default `1024`; deliberately
  large and never the binding constraint). Must satisfy
  `max input + max_tokens <= vLLM max_model_len`, with vLLM served at
  `max_model_len <= 4096` so nothing is cut.
- `LLM_TIMEOUT` — per-request timeout (default `300`); CPU inference can be slow.
- `VLLM_HOST` / `VLLM_PORT` — vLLM endpoint (defaults `localhost:8000`).

## How to run

```bash
export LLM_MODEL="/models/LLM"                 # the model served by vLLM
export LLM_MAX_TOKENS="${LLM_MAX_TOKENS:-1024}"
export LLM_TIMEOUT=300
ALL_PROXY= all_proxy= python test_context_overflow_vllm/test_pipeline.py
```

Requirements for the real run (test environment only, not production code):
- A running real vLLM instance serving an OpenAI-compatible `/v1` endpoint,
  started with `--max-model-len 4096` (see `How to start vLLM` below).
- Python deps: `openai`, `pydantic-settings`, `tokenizers` (no `transformers`,
  no `src.containers` import needed): `pip install openai pydantic-settings tokenizers`.

## How to start vLLM (CPU, persistent compile cache)

```bash
docker run -d --name vllm-batch -p 8000:8000 --shm-size=1g \
  -v "$HOME/Programming/python/mock-llm-generation-api/models/Qwen2.5-0.5B-Instruct:/models/LLM:ro" \
  -v "$HOME/.cache/vllm-aot:/root/.cache/vllm" \
  vllm/vllm-openai-cpu:v0.28.0 /models/LLM \
  --gpu-memory-utilization 0.3 --kv-cache-memory-bytes 268435456 --max-model-len 4096
```

The AOT compile cache is mounted (`/root/.cache/vllm`) so restarts reuse compiled
kernels instead of recompiling for ~10 minutes. Use a **durable path** such as
`~/.cache/vllm-aot` (a `/tmp` path is wiped on reboot, which also kills the
container and the venv that live there).

## Notes / deviations

- This test composes the real production classes directly instead of going
  through `src.containers.py` (which pulls in `transformers`/`qdrant-client`);
  the tokenizer is a `tokenizers`-crate adapter over the local Qwen
  `tokenizer.json` (identical BPE counts).
- The HTTP recorder is test-only (instance-level monkeypatch, process ends with
  the script).
- No mock or fake LLM is used for generation; SUMMARIZE and the final batch
  both hit the real vLLM model.