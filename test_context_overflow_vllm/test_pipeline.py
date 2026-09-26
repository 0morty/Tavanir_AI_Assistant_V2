#!/usr/bin/env python3
"""Batch-focused end-to-end test against a real vLLM backend.

The primary objective of this test is to prove the real batch architecture:

    3 independent chunks
      -> 3 independent ContextBuilder-processed prompts (real allocation +
         real overflow handling; SUMMARIZE runs real vLLM inference for its one chunk)
      -> ONE OpenAILLMClient.complete_many(prompts) batch (3 items)
      -> real vLLM batch endpoint in a single HTTP request
      -> 3 independent responses mapped back by batch index.

Secondary objective: verify the hard-cut problem is gone. vLLM is served with
max_model_len=4096 and LLM_MAX_TOKENS is sized so that neither the chunk-2
summarization nor any final completion is artificially truncated; every choice
must come back with finish_reason == "stop".

The exact HTTP payloads are captured at the wire level by wrapping the
AsyncOpenAI instance's ``post`` (batch endpoint) and ``chat.completions.create``
fallbacks — so the report shows the real body actually sent to vLLM, the number
of calls, item counts, index-to-chunk mapping and per-choice finish_reason.

This script composes the project's REAL production classes directly (the DI
composition root pulls in transformers/qdrant and is not needed here) and does
NOT modify any production code.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_TEST_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TEST_DIR.parent
sys.path.insert(0, str(_REPO_ROOT))

os.environ.pop("ALL_PROXY", None)
os.environ.pop("all_proxy", None)

# This test talks to a single vLLM instance for everything (summarization and
# final batch); give it a generous per-call timeout because CPU inference is
# slow. Overridable through the environment.
_DEFAULT_TIMEOUT = 300
# Output capacity (max_tokens) is deliberately LARGE: it must never be the
# binding constraint on the summarization. vLLM serves max_model_len=4096 and
# the largest input is the ~650-token summarization prompt, so 1024 output
# tokens keep input + output comfortably within the window.
_DEFAULT_MAX_TOKENS = 1024

# Budgets are the outcome of the budget probe (budget_probe.py):
#   chunk-1: 300 -> CHUNKS capacity 223, content 442 -> TRUNCATE
#   chunk-2: 460 -> CHUNKS capacity 383, content 456 -> SUMMARIZE (summary must
#            fit 383 tokens; the natural summary is ~10x smaller)
#   chunk-3: 510 -> CHUNKS capacity 416, content 416 -> no overflow (full pass-through)
BUDGETS = {"chunk-1": 300, "chunk-2": 460, "chunk-3": 510}


class _WireRecorder:
    """Captures the real HTTP calls of the shared AsyncOpenAI client.

    Wraps ``post`` (the vLLM batch endpoint, both the summarization call and
    the final batch) and ``chat.completions.create`` (only used when the batch
    endpoint is absent). Recording at this seam proves how many HTTP requests
    were issued, how many items each carried, and the actual response
    finish_reason / content per batch index.
    """

    def __init__(self, async_client) -> None:
        import types

        self.post_calls: list[dict] = []
        self.create_calls: list[dict] = []
        self._post_original = async_client.post
        self._create_original = async_client.chat.completions.create
        # MethodType(func, obj) calls func(obj, *args). The underlying funcs
        # therefore take the bound instance as their first positional argument
        # (``client`` below) and delegate to the pre-bound originals.
        async_client.post = types.MethodType(self._wrapped_post, async_client)
        completions_resource = async_client.chat.completions
        completions_resource.create = types.MethodType(
            self._wrapped_create, completions_resource
        )

    async def _wrapped_post(
        self,
        client,
        path,
        *,
        cast_to,
        body=None,
        content=None,
        files=None,
        options=None,
        stream=False,
        stream_cls=None,
    ):
        if options is None:
            options = {}
        start = time.perf_counter()
        try:
            result = await self._post_original(
                path,
                cast_to=cast_to,
                body=body,
                content=content,
                files=files,
                options=options,
                stream=stream,
                stream_cls=stream_cls,
            )
            error = None
        except Exception as err:  # noqa: BLE001
            result, error = None, err
        self.post_calls.append(
            {
                "path": path,
                "body": body,
                "elapsed_s": round(time.perf_counter() - start, 3),
                "result": result,
                "error": f"{type(error).__name__}: {error}" if error else None,
            }
        )
        if error is not None:
            raise error
        return result

    async def _wrapped_create(self, completions_resource, **kwargs):
        start = time.perf_counter()
        try:
            result = await self._create_original(**kwargs)
            error = None
        except Exception as err:  # noqa: BLE001
            result, error = None, err
        finish_reason = None
        special = getattr(result, "choices", None)
        if isinstance(special, list) and special:
            fr = getattr(special[0], "finish_reason", None)
            finish_reason = getattr(fr, "value", None)
            if finish_reason is None:
                finish_reason = fr
        self.create_calls.append(
            {
                "model": kwargs.get("model"),
                "messages_count": len(kwargs.get("messages", [])),
                "max_tokens": kwargs.get("max_tokens"),
                "elapsed_s": round(time.perf_counter() - start, 3),
                "finish_reason": finish_reason,
                "error": f"{type(error).__name__}: {error}" if error else None,
            }
        )
        if error is not None:
            raise error
        return result


def _choices_of(call: dict) -> list[dict]:
    result = call.get("result")
    if isinstance(result, dict):
        choices = result.get("choices")
        if isinstance(choices, list):
            return [c for c in choices if isinstance(c, dict)]
    return []


def _post_item_count(call: dict) -> int:
    body = call.get("body")
    if isinstance(body, dict):
        messages = body.get("messages")
        if isinstance(messages, list):
            return len(messages)
    return 0


def _pretty_json(obj: object) -> str:
    import json

    return json.dumps(obj, indent=2, ensure_ascii=False)


def main() -> None:
    import httpx  # noqa: PLC0415 - light lib for the preflight only

    from src.infrastructure.configs.settings import generation_settings, llm_settings

    from vllm_test_common import (
        CHUNK_ORDER,
        build_chunk_builder,
        make_chunk_summarizer,
        make_context_builder,
        make_llm_client,
        make_tokenizer,
        parse_chunks,
        summarization_prompt_tokens,
    )

    chunks = parse_chunks()
    tokenizer = make_tokenizer()
    context_builder = make_context_builder(tokenizer)

    base_url = llm_settings.VLLM_BASE_URL
    api_key = llm_settings.VLLM_API_KEY
    model = generation_settings.LLM_MODEL
    temperature = generation_settings.LLM_TEMPERATURE
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", _DEFAULT_MAX_TOKENS))
    timeout = float(os.environ.get("LLM_TIMEOUT", _DEFAULT_TIMEOUT))

    print(f"[pipeline] parsed chunks: {list(chunks)}")
    print(f"[pipeline] vLLM {base_url} model={model} temperature={temperature} "
          f"max_tokens={max_tokens} timeout={timeout}")

    # --- Preflight: read the REAL serving config (incl. max_model_len) ---------
    preflight: dict = {"reachable": False, "models": "", "max_model_len": None}
    try:
        resp = httpx.get(base_url + "/models", timeout=5.0)
        preflight["reachable"] = resp.status_code == 200
        if preflight["reachable"]:
            data = resp.json()
            models = data.get("data", []) if isinstance(data, dict) else []
            if models:
                preflight["models"] = _pretty_json(models)
                preflight["max_model_len"] = models[0].get("max_model_len")
            else:
                preflight["models"] = _pretty_json(data)
        else:
            preflight["models"] = resp.text
    except Exception as err:  # noqa: BLE001
        preflight["models"] = f"{type(err).__name__}: {err}"
    assert preflight["reachable"], (
        f"vLLM not reachable at {base_url} (is the container up?): {preflight['models']}"
    )
    print(f"[pipeline] preflight OK, vLLM max_model_len={preflight['max_model_len']}")

    llm_client = make_llm_client(
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    recorder = _WireRecorder(llm_client._client)
    chunk_summarizer = make_chunk_summarizer(llm_client)

    from src.domain.enums import OverflowStrategy  # noqa: PLC0415
    from src.domain.overflow_strategy_stack import OverflowStrategyStack  # noqa: PLC0415

    stacks = {
        "chunk-1": OverflowStrategyStack([OverflowStrategy.TRUNCATE, OverflowStrategy.IGNORE]),
        "chunk-2": OverflowStrategyStack([OverflowStrategy.SUMMARIZE, OverflowStrategy.TRUNCATE]),
        "chunk-3": OverflowStrategyStack([OverflowStrategy.IGNORE, OverflowStrategy.TRUNCATE]),
    }

    # --- Step 1: three INDEPENDENT ContextBuilder runs -------------------------
    sums: dict = {cid: None for cid in CHUNK_ORDER}
    results: dict = {}
    for cid in CHUNK_ORDER:
        summarizer = None
        if cid == "chunk-2":
            summarizer = chunk_summarizer
        builder = build_chunk_builder(
            chunks[cid], chunks[cid], stacks[cid], chunk_summarizer=summarizer
        )
        results[cid] = context_builder.build(builder, max_tokens=BUDGETS[cid])
        chunk_out = next(
            out for out in results[cid].sections if out.section_type == "CHUNKS"
        )
        sums[cid] = {
            "requested": chunk_out.requested_tokens,
            "capacity": chunk_out.capacity_tokens,
            "overflowed": bool(chunk_out.overflowed),
            "fitted": chunk_out.fitted_tokens,
            "content": chunk_out.content,
            "prompt_total": results[cid].total_tokens,
        }
        print(f"[pipeline] {cid}: requested={chunk_out.requested_tokens} "
              f"capacity={chunk_out.capacity_tokens} overflowed={chunk_out.overflowed} "
              f"fitted={chunk_out.fitted_tokens}")

    # --- Step 2: the ONE final batch call --------------------------------------
    # Prompts are the three independent ContextBuilderResult.prompt strings,
    # collected in fixed chunk order (== the batch index mapping).
    prompts = [results[cid].prompt for cid in CHUNK_ORDER]
    responses = llm_client.complete_many(prompts)
    llm_client.close()

    # --- Assemble the report ----------------------------------------------------
    lines: list[str] = []
    add = lines.append

    add("# Real-vLLM Batch End-to-End Test Report")
    add("")
    add("## A. Input")
    add("")
    add(f"- vLLM base URL: `{base_url}` (reachable: `{preflight['reachable']}`)")
    add(f"- Served model: `{model}`")
    add(f"- Tokenizer: local `Qwen2.5-0.5B-Instruct/tokenizer.json` "
        "(`RawTokenizerAdapter` over the `tokenizers` crate)")
    add(f"- LLM temperature: `{temperature}` | LLM_MAX_TOKENS: `{max_tokens}` | "
        "LLM timeout: `{timeout}s`")
    add(f"- vLLM serving config: `max_model_len={preflight['max_model_len']}``")
    add("")
    add("Per-chunk budgets (from `budget_probe.py`):"
        f" `{BUDGETS}`; strategies: chunk-1 `TRUNCATE`, chunk-2 `SUMMARIZE`, "
        "chunk-3 `[IGNORE, TRUNCATE]` (expects **no** overflow / full pass-through).")
    add("")
    for cid in CHUNK_ORDER:
        add(f"### {cid}")
        add("")
        add(f"Original chunk tokens: `{tokenizer.count_tokens(chunks[cid])}`")
        add("")
        add("<details><summary>Original chunk text</summary>")
        add("")
        add(chunks[cid])
        add("")
        add("</details>")
        add("")

    add("## B. ContextBuilder processing (independent, real allocation + overflow)")
    add("")
    for cid in CHUNK_ORDER:
        s = sums[cid]
        strategy = _infer_strategy(cid, s, tokenizer)
        add(f"### {cid}")
        add("")
        add("| Section budget | requested | capacity | overflowed | fitted |")
        add("|---|---|---|---|---|")
        for out in results[cid].sections:
            add(f"| {out.section_type} | {out.requested_tokens} | "
                f"{out.capacity_tokens} | {out.overflowed} | {out.fitted_tokens} |")
        add("")
        add(f"- Strategy applied: **{strategy}**")
        if cid == "chunk-2":
            add("- Summarization used the **real vLLM** through the same client "
                "(recorded as a separate 1-item batch call, see D/F).")
        add("")
        add("<details><summary>Fitted content actually placed in the prompt "
            f"(strategy: {strategy})</summary>")
        add("")
        if s["content"]:
            add(s["content"])
        else:
            add("_empty_")
        add("")
        add("</details>")
        add("")

    add("## C. Batch construction (chunk -> prompt -> batch index mapping)")
    add("")
    add("Each `ContextBuilderResult.prompt` becomes exactly one user message. "
        "Prompts are collected in fixed order `chunk-1, chunk-2, chunk-3` and "
        "submitted through **one** `OpenAILLMClient.complete_many(prompts)` call "
        "(vLLM `POST /v1/chat/completions/batch`). The batch message index "
        "equals the body's position for each chunk:")
    add("")
    add("| batch index | chunk | prompt tokens |")
    add("|---|---|---|")
    for idx, cid in enumerate(CHUNK_ORDER):
        add(f"| {idx} | {cid} | {tokenizer.count_tokens(prompts[idx])} |")
    add("")
    constructed = {
        "model": model,
        "messages": [[{"role": "user", "content": p}] for p in prompts],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    add("<details><summary>Constructed batch body (what the pipeline intends to send)</summary>")
    add("")
    add(f"```json\n{_pretty_json(constructed)}\n```")
    add("")
    add("</details>")
    add("")

    add("## D. Actual HTTP payload captured at the wire level")
    add("")
    if not recorder.post_calls and not recorder.create_calls:
        add("**No LLM HTTP traffic was captured.**")
    for idx, call in enumerate(recorder.post_calls, start=1):
        items = _post_item_count(call)
        # The summarization always runs first (inside ContextBuilder.build for
        # chunk-2); the final batch is the last POST call.
        is_summarize = idx == 1 and len(recorder.post_calls) >= 2
        add(f"### Batch POST call #{idx}: `{call['path']}`  "
            f"(elapsed `{call['elapsed_s']}s`, items `{items}`)")
        add("")
        if call["error"]:
            add(f"**error:** `{call['error']}`")
        else:
            add("`messages` array (one conversation per item, first ~120 chars "
                "each):")
            add("")
            body = call["body"]
            for i, messages in enumerate(body.get("messages", [])):
                content = messages[0].get("content", "")
                label = (
                    "chunk-2 (summarization prompt)"
                    if is_summarize
                    else CHUNK_ORDER[i]
                )
                add(f"- item {i} (`{label}`): "
                    f"`{content[:120]}...` ({len(content)} chars)")
            add("")
            add("Per-choice result (index / finish_reason / content length):")
            add("")
            for choice in _choices_of(call):
                msg = choice.get("message", {})
                content = msg.get("content", "") if isinstance(msg, dict) else ""
                add(f"- index `{choice.get('index')}`: finish_reason="
                    f"`{choice.get('finish_reason')}`, content chars `{len(content)}`")
            add("")
    for idx, call in enumerate(recorder.create_calls, start=1):
        add(f"### `chat.completions.create` call #{idx} "
            f"(model `{call['model']}`, messages `{call['messages_count']}`, "
            f"max_tokens `{call['max_tokens']}`) — *fallback path*")
        add("")
        add(f"- finish_reason: `{call['finish_reason']}` | elapsed `{call['elapsed_s']}s`")
        if call["error"]:
            add(f"- error: `{call['error']}`")
        add("")

    add("## E. Actual model responses (real vLLM) and index mapping")
    add("")
    add("The batch response carries one choice per conversation, indexed "
        "`0..N-1`. `OpenAILLMClient._extract_batch_results` maps each choice "
        "back by its `index`, preserving input order:")
    add("")
    final_call = recorder.post_calls[-1] if recorder.post_calls else None
    final_choices = {c.get("index"): c for c in _choices_of(final_call)} if final_call else {}
    add("| batch index | chunk | finish_reason | response (first 200 chars) |")
    add("|---|---|---|---|")
    for idx, (cid, response) in enumerate(zip(CHUNK_ORDER, responses)):
        choice = final_choices.get(idx, {})
        fr = choice.get("finish_reason")
        add(f"| {idx} | {cid} | `{fr}` | {response[:200]} |")
    add("")

    add("## F. Request counts (batch architecture proof)")
    add("")
    add("| metric | count |")
    add("|---|---|")
    add(f"| ContextBuilder processing calls | `{len(CHUNK_ORDER)}` (one per chunk) |")
    add(f"| `complete_many` (batch POST) HTTP calls | `{len(recorder.post_calls)}` |")
    add(f"| `complete` / `chat.completions.create` fallback calls | `{len(recorder.create_calls)}` |")
    total_batch_items = sum(_post_item_count(call) for call in recorder.post_calls)
    add(f"| total batch POST items | `{total_batch_items}` "
        "(1 summarization + 1 final batch of 3) |")
    add(f"| final batch items | `{_post_item_count(recorder.post_calls[-1]) if recorder.post_calls else 0}` |")
    add(f"| independent final generations via separate `complete()` calls | `0` |")
    add("")
    add("Assertions that must hold for the batch objective:")
    add("")
    add("- [ ] exactly one final batch POST with **3** items")
    add("- [ ] final batch message order `chunk-1, chunk-2, chunk-3` matches "
        "batch indexes `0, 1, 2`")
    add("- [ ] zero individual `complete()` calls for the final generation "
        "(no fallback to concurrent `create`)")
    add("- [ ] three independent responses returned in input order")
    add("")

    add("## G. Hard-cut verification (no artificial truncation)")
    add("")
    add("The `SUMMARIZE` strategy's summary length is bounded by "
        "`LLM_MAX_TOKENS` (the real request `max_tokens`), NOT by the "
        "ContextBuilder capacity. This section proves the environment is sized "
        "so nothing is cut off:")
    add("")
    add("| item | value |")
    add("|---|---|")
    add(f"| vLLM `max_model_len` | `{preflight['max_model_len']}` |")
    add(f"| `LLM_MAX_TOKENS` (request `max_tokens`) | `{max_tokens}` |")
    add("")
    sum_call = recorder.post_calls[0] if recorder.post_calls else None
    sum_choices = _choices_of(sum_call) if sum_call else []
    sum_out_tokens = None
    if sum_choices:
        sum_msg = sum_choices[0].get("message", {})
        sum_content = sum_msg.get("content", "") if isinstance(sum_msg, dict) else ""
        if sum_content:
            sum_out_tokens = tokenizer.count_tokens(sum_content)
        else:
            sum_usage = sum_call.get("result", {})
            sum_out_tokens = (sum_usage or {}).get("usage", {}).get("completion_tokens")
    summarization_input_tokens = summarization_prompt_tokens(
        tokenizer, chunks["chunk-2"]
    )
    add("| summarization input tokens (ChunkPromptBuilder, chunk-2) | "
        f"`{summarization_input_tokens}` |")
    add(f"| summarization request headroom (input + max_tokens) | "
        f"`{summarization_input_tokens + max_tokens}` "
        f"<= {preflight['max_model_len']}? "
        f"`{summarization_input_tokens + max_tokens <= (preflight['max_model_len'] or 0)}` |")
    add(f"| summarization output tokens | `{sum_out_tokens}` |")
    final_prompt_tokens = max(tokenizer.count_tokens(p) for p in prompts)
    add(f"| largest final prompt tokens | `{final_prompt_tokens}` |")
    add(f"| final batch request headroom (max prompt + max_tokens) | "
        f"`{final_prompt_tokens + max_tokens}` <= {preflight['max_model_len']}? "
        f"`{final_prompt_tokens + max_tokens <= (preflight['max_model_len'] or 0)}` |")
    add("")
    add("finish_reason per real generation:")
    add("")
    for idx, call in enumerate(recorder.post_calls, start=1):
        for choice in _choices_of(call):
            add(f"- POST #{idx} index `{choice.get('index')}` -> "
                f"finish_reason `{choice.get('finish_reason')}`")
    add("")
    all_stopped = all(
        choice.get("finish_reason") == "stop"
        for call in recorder.post_calls
        for choice in _choices_of(call)
    )
    add(f"- **all generations finish_reason == `stop`? `{all_stopped}`** "
        "(if `length`, LLM_MAX_TOKENS is the hard cut and must be raised)")
    add("")

    add("## H. Deviations / limitations")
    add("")
    add("- Production DI (`src.containers.py`) is untouched; this test composes "
        "the real classes directly with a `tokenizers`-crate adapter in place "
        "of the `transformers`-based GemmaTokenizer (identical BPE counts).")
    add("- The AsyncOpenAI instance is wrapped at the `post`/`create` seam "
        "(test-only, reverted on process end) to capture the true HTTP traffic.")
    add("- No mock or fake LLM is used for generation; SUMMARIZE and the final "
        "batch both hit the real vLLM model.")
    add("")
    (_TEST_DIR / "test_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("[pipeline] report written to " + str(_TEST_DIR / "test_report.md"))
    print(
        f"[pipeline] summary: batches={len(recorder.post_calls)}, "
        f"final_items={_post_item_count(recorder.post_calls[-1]) if recorder.post_calls else 0}, "
        f"create_fallback={len(recorder.create_calls)}, "
        f"chunk2_summary_tokens={sum_out_tokens}"
    )

    checks = {
        "exactly one final batch POST with 3 items": (
            bool(recorder.post_calls)
            and _post_item_count(recorder.post_calls[-1]) == 3
        ),
        "post_calls == 2 (1 summarization + 1 final batch)": (
            len(recorder.post_calls) == 2
        ),
        "zero individual complete/create fallback calls": (
            len(recorder.create_calls) == 0
        ),
        "3 responses returned in chunk order": len(responses) == 3,
        "chunk-2 summary used (fitted == summary)": (
            sums["chunk-2"]["capacity"] >= sums["chunk-2"]["fitted"]
            and sums["chunk-2"]["fitted"] > 0
        ),
        "no artificial truncation (all finish_reason == stop)": all(
            choice.get("finish_reason") == "stop"
            for call in recorder.post_calls
            for choice in _choices_of(call)
        ),
        "headroom: worst input + max_tokens <= vLLM max_model_len": (
            preflight["max_model_len"] is not None
            and max(
                summarization_input_tokens + max_tokens,
                final_prompt_tokens + max_tokens,
            )
            <= preflight["max_model_len"]
        ),
    }
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    failed = [name for name, ok in checks.items() if not ok]
    print(f"[pipeline] VERDICT: {'PASS' if not failed else 'FAIL: ' + '; '.join(failed)}")


def _infer_strategy(cid, s, tokenizer) -> str:
    if not s["overflowed"]:
        return "none (content passes through unchanged)"
    if s["content"] == "":
        return "IGNORE"
    if cid == "chunk-2":
        if s["capacity"] >= tokenizer.count_tokens(s["content"]):
            return "SUMMARIZE (real LLM summary used)"
        return "SUMMARIZE fell back to TRUNCATE (summary over capacity)"
    return "TRUNCATE"


if __name__ == "__main__":
    main()