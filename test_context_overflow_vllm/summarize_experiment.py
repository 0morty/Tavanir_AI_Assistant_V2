#!/usr/bin/env python3
"""Targeted experiment: does the SUMMARIZE overflow strategy follow the
ContextBuilder-allocated capacity or the LLM output bound?

Composes the REAL production classes (ContextBuilder, CapacityAllocator,
DemandAllocator, RedistributionAllocator, OverflowStrategyDispatcher,
PromptBuilder, ChunksSection, LLMChunkSummarizer) with two injected test-local
doubles:

  - a Tokenizer adapter over the real Qwen2.5 ``tokenizer.json`` via the
    lightweight ``tokenizers`` crate (same BPE, so counts match the HF-based
    production GemmaTokenizer exactly);
  - a deterministic fake ILLMClient returning a summary of an EXACT token count
    (the architecture's own DI seam; the physical vLLM inference is not
    exercised, its length-bounding role ``max_tokens = LLM_MAX_TOKENS`` is a
    source fact in ``openai_llm_client.py``).

Scenario A: budget 400 -> CHUNKS capacity 323, summary 256 (fits)
Scenario B: budget 258 -> CHUNKS capacity 181, summary 256 (over capacity)
Scenario C: budget 480 -> CHUNKS capacity 403, summary 128 (under capacity)

No production code is modified.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_TEST_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TEST_DIR.parent
sys.path.insert(0, str(_REPO_ROOT))

_QWEN_TOKENIZER_JSON = (
    Path("/home/mortkh/Programming/python/mock-llm-generation-api")
    / "models/Qwen2.5-0.5B-Instruct/tokenizer.json"
)

SCENARIOS = {
    "A": {"budget": 400, "fake_summary_tokens": 256},
    "B": {"budget": 258, "fake_summary_tokens": 256},
    "C": {"budget": 480, "fake_summary_tokens": 128},
}


class RawTokenizerAdapter:
    """Adapter for the domain ``Tokenizer`` port over the ``tokenizers`` crate.

    Mirrors GemmaTokenizer (same BPE post-processing), so ``count_tokens`` and
    the ``encode`` offset mapping match the HF fast tokenizer used in the
    real-vLLM test.
    """

    def __init__(self, path: Path) -> None:
        from tokenizers import Tokenizer

        self._tok = Tokenizer.from_file(str(path))

    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        encoding = self._tok.encode(text)
        return list(zip(encoding.ids, encoding.offsets))

    def count_tokens(self, text: str) -> int:
        return len(self.encode(text))


class FakeLLMClient:
    """Deterministic ILLMClient: returns an exact-token-count summary."""

    def __init__(self, tokenizer, token_count: int, chunk_text: str) -> None:
        self._tokenizer = tokenizer
        self._token_count = token_count
        self._chunk_text = chunk_text
        self.calls: list[str] = []
        self.last_summary = ""

    def _summary(self, prompt: str) -> str:
        from src.domain.context.overflow.truncate import TruncateStrategy

        self.calls.append(prompt)
        self.last_summary = TruncateStrategy(self._tokenizer).apply(
            self._chunk_text, self._token_count
        )
        return self.last_summary

    def complete(self, prompt: str) -> str:
        return self._summary(prompt)

    def complete_many(self, prompts: list[str]) -> list[str]:
        return [self._summary(prompt) for prompt in prompts]


def _chunk2_text() -> str:
    text = (_TEST_DIR / "mock_chunks.md").read_text(encoding="utf-8")
    start = text.find("## CHUNK 2")
    end = text.find("## CHUNK 3")
    return text[start:end].split("\n", 1)[1].strip()


def main() -> None:
    from src.application.context.allocation import (
        CapacityAllocator,
        DemandAllocator,
        RedistributionAllocator,
    )
    from src.application.context.context_builder import ContextBuilder
    from src.application.context.overflow_strategy_dispatcher import (
        OverflowStrategyDispatcher,
    )
    from src.application.context.sections.chunks_section import ChunksSection
    from src.application.prompt.prompt_builder import PromptBuilder
    from src.domain.entities import GenerationChunk
    from src.domain.enums import OverflowStrategy
    from src.domain.overflow_strategy_stack import OverflowStrategyStack
    from src.infrastructure.services.summarizers.chunk_prompt_builder import (
        ChunkPromptBuilder,
    )
    from src.infrastructure.services.summarizers.llm_chunk_summarizer import (
        LLMChunkSummarizer,
    )

    tokenizer = RawTokenizerAdapter(_QWEN_TOKENIZER_JSON)
    context_builder = ContextBuilder(
        tokenizer=tokenizer,
        capacity_allocator=CapacityAllocator(
            DemandAllocator(), RedistributionAllocator()
        ),
        dispatcher=OverflowStrategyDispatcher(),
    )

    text = _chunk2_text()
    print(f"chunk-2 raw token count (tokenizers crate): {tokenizer.count_tokens(text)}")
    print(f"separator '\\n\\n' token count: {tokenizer.count_tokens(chr(10)*2)}")
    print()

    results: list[dict] = []
    for scenario, spec in SCENARIOS.items():
        builder = PromptBuilder(seed_defaults=True)
        fake = FakeLLMClient(tokenizer, spec["fake_summary_tokens"], text)
        summarizer = LLMChunkSummarizer(llm_client=fake)
        builder.set_section(
            "CHUNKS",
            ChunksSection(
                [GenerationChunk(chunk_id="chunk-2", content=text, reference=None)],
                overflow_strategies=OverflowStrategyStack(
                    [OverflowStrategy.SUMMARIZE, OverflowStrategy.TRUNCATE]
                ),
                chunk_summarizer=summarizer,
            ),
        )
        builder.set_role(
            "You are a meticulous technical analyst. Use the provided context "
            "chunks to answer the user's question accurately."
        )
        builder.set_history([])
        builder.set_system_input(
            "Answer the user's question strictly based on the context chunks "
            "provided above. Do not invent facts."
        )
        builder.set_user_input(
            "What is the single most important takeaway of the material above? "
            "Answer in one or two sentences."
        )
        builder.set_output_format(
            "Plain text only. No preamble, no bullets, no markdown headers."
        )

        result = context_builder.build(builder, max_tokens=spec["budget"])
        chunk_output = next(
            out for out in result.sections if out.section_type == "CHUNKS"
        )
        raw_summary = fake.last_summary
        summary_used = chunk_output.content.strip() == raw_summary.strip()

        prompt = ChunkPromptBuilder().build(text)
        results.append(
            {
                "scenario": scenario,
                "budget": spec["budget"],
                "requested_chunks_tokens": chunk_output.requested_tokens,
                "allocated_chunks_capacity": chunk_output.capacity_tokens,
                "overflowed": bool(chunk_output.overflowed),
                "llm_summary_tokens_returned": tokenizer.count_tokens(raw_summary),
                "summary_<=_capacity": tokenizer.count_tokens(raw_summary)
                <= chunk_output.capacity_tokens,
                "final_content_is_the_summary": summary_used,
                "final_content_tokens": tokenizer.count_tokens(chunk_output.content),
                "final_content_is_dropped": chunk_output.content == "",
            }
        )
    results.append(
        {
            "scenario": "prompt-inspection",
            "summarization_prompt_result": {
                "contains_max_tokens_instruction": "حداکثر" in prompt,
                "contains_any_capacity_or_token_word": any(
                    w in prompt for w in ("توکن", "token", "capacity")
                ),
                "prompt": prompt,
            },
        }
    )
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()