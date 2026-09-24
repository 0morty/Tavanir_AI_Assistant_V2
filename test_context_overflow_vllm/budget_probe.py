#!/usr/bin/env python3
"""Probe exact token math for the real-vLLM batch test (no inference).

Computes, for the three mock chunks and the shared builder template:
  - raw and rendered token counts per section;
  - the CHUNKS capacity the real CapacityAllocator assigns for a set of
    candidate budgets (per chunk, since allocation depends on rendered demand);
  - the input token count of the chunk-2 summarization prompt (ChunkPromptBuilder);
  - headroom check: summarization input + LLM_MAX_TOKENS, and final prompt +
    LLM_MAX_TOKENS, against vLLM max_model_len.
"""

from __future__ import annotations

import json

from vllm_test_common import (
    CHUNK_ORDER,
    build_chunk_builder,
    make_context_builder,
    make_tokenizer,
    parse_chunks,
)
from src.domain.enums import OverflowStrategy
from src.domain.overflow_strategy_stack import OverflowStrategyStack

STACKS = {
    "chunk-1": OverflowStrategyStack(
        [OverflowStrategy.TRUNCATE, OverflowStrategy.IGNORE]
    ),
    "chunk-2": OverflowStrategyStack(
        [OverflowStrategy.SUMMARIZE, OverflowStrategy.TRUNCATE]
    ),
    "chunk-3": OverflowStrategyStack(
        [OverflowStrategy.IGNORE, OverflowStrategy.TRUNCATE]
    ),
}

CANDIDATE_BUDGETS = [258, 300, 340, 400, 460, 490, 510, 540, 600]


def main() -> None:
    tokenizer = make_tokenizer()
    context_builder = make_context_builder(tokenizer)
    chunks = parse_chunks()
    llm_max_tokens = 512
    max_model_len = 4096

    rows: list[dict] = []
    for cid in CHUNK_ORDER:
        body = chunks[cid]
        raw = tokenizer.count_tokens(f"Chunk 1:\n{body}")
        builder = build_chunk_builder(cid, body, STACKS[cid])
        rendered = {
            out.section_type: out.requested_tokens
            for out in context_builder.build(builder, max_tokens=1_000_000).sections
        }
        for budget in CANDIDATE_BUDGETS:
            result = context_builder.build(builder, max_tokens=budget)
            chunk_out = next(
                out for out in result.sections if out.section_type == "CHUNKS"
            )
            rows.append(
                {
                    "chunk": cid,
                    "budget": budget,
                    "prompt_total": result.total_tokens,
                    "chunk_requested": chunk_out.requested_tokens,
                    "chunk_capacity": chunk_out.capacity_tokens,
                    "overflowed": bool(chunk_out.overflowed),
                }
            )
        print(f"== {cid} ==")
        print(f"raw body tokens (w/ 'Chunk 1:' prefix): {raw}")
        print(f"rendered section token counts: {rendered}")

    from src.infrastructure.services.summarizers.chunk_prompt_builder import (
        ChunkPromptBuilder,
    )

    summarization_prompt = ChunkPromptBuilder().build(chunks["chunk-2"])
    sum_in = tokenizer.count_tokens(summarization_prompt)
    print("== summarization prompt ==")
    print(f"ChunkPromptBuilder input tokens for chunk-2: {sum_in}")
    print(f"headroom (summarization): input {sum_in} + max_tokens {llm_max_tokens} = "
          f"{sum_in + llm_max_tokens} <= {max_model_len}? "
          f"{sum_in + llm_max_tokens <= max_model_len}")
    final_prompt_total = max(
        next(
            r["prompt_total"]
            for r in rows
            if r["chunk"] == cid and r["budget"] == 600
        )
        for cid in CHUNK_ORDER
    )
    print(f"headroom (final batch, worst prompt ~budget 600): {final_prompt_total} + "
          f"{llm_max_tokens} = {final_prompt_total + llm_max_tokens} <= {max_model_len}? "
          f"{final_prompt_total + llm_max_tokens <= max_model_len}")

    print("\n== capacity matrix ==")
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()