#!/usr/bin/env python3
"""Shared compose helpers for the real-vLLM batch end-to-end test.

Composes the REAL production classes (ContextBuilder, CapacityAllocator,
DemandAllocator, RedistributionAllocator, OverflowStrategyDispatcher,
PromptBuilder, ChunksSection, LLMChunkSummarizer, OpenAILLMClient) with a
lightweight Tokenizer adapter over the local Qwen tokenizer.json. The full
DI composition root (src.containers.py) is intentionally NOT used here: it
pulls in transformers/qdrant/dependency-injector, none of which the batch
test needs. No production code is modified.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_TEST_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TEST_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.environ.pop("ALL_PROXY", None)
os.environ.pop("all_proxy", None)

QWEN_TOKENIZER_JSON = (
    Path("/home/mortkh/Programming/python/mock-llm-generation-api")
    / "models/Qwen2.5-0.5B-Instruct/tokenizer.json"
)

ROLE = (
    "You are a meticulous technical analyst. Use the provided context "
    "chunks to answer the user's question accurately."
)
SYSTEM_INPUT = (
    "Answer the user's question strictly based on the context chunks "
    "provided above. Do not invent facts."
)
USER_INPUT = (
    "What is the single most important takeaway of the material above? "
    "Answer in one short sentence (at most 30 words)."
)
OUTPUT_FORMAT = (
    "Plain text only. No preamble, no bullets, no markdown headers."
)

# Test-level override of the documented ``ChunkSummarizationPrompts`` override
# seam: provides an ENGLISH version of the summarization instructions (the
# production defaults are Persian) with exactly the same semantics, and NO
# length constraint at all. The summary length is therefore whatever the real
# LLM naturally produces, which is why the real run sets LLM_MAX_TOKENS so high
# that it can never be the binding constraint. This does not modify production
# code; the summarizer still runs through the real pipeline and the real LLM.
CONCISE_ROLE = (
    "You are a text summarization expert. You summarize the given text "
    "separately and faithfully, preserving its core content."
)
CONCISE_SYSTEM_INPUT = (
    "Summarize the text below faithfully. The summary must be self-contained: "
    "do not compare, combine or merge this text with anything else. Preserve the "
    "core meaning, numbers and references, and keep the output language the same "
    "as the input. Return only the summary text."
)
CONCISE_OUTPUT_FORMAT = "Return only the summary text; no preamble or extra explanation."

CHUNK_ORDER = ("chunk-1", "chunk-2", "chunk-3")


class RawTokenizerAdapter:
    """Adapter for the domain ``Tokenizer`` port over the ``tokenizers`` crate.

    Mirrors the production HF fast tokenizer (same BPE post-processing), so
    ``count_tokens``/``encode`` offsets match the Qwen2.5 tokenizer used when
    this test talks to the real vLLM model.
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


def make_tokenizer() -> RawTokenizerAdapter:
    return RawTokenizerAdapter(QWEN_TOKENIZER_JSON)


def parse_chunks(md_path: Path | None = None) -> dict[str, str]:
    """Return {chunk_id: original text} from mock_chunks.md."""
    path = md_path or (_TEST_DIR / "mock_chunks.md")
    text = path.read_text(encoding="utf-8")
    markers = list(
        re.finditer(r"^##\s+CHUNK\s+(\d+)[ ]*-[ ]*.*$", text, re.MULTILINE)
    )
    chunks: dict[str, str] = {}
    for idx, marker in enumerate(markers):
        start = marker.end()
        end = markers[idx + 1].start() if idx + 1 < len(markers) else len(text)
        chunks[f"chunk-{marker.group(1)}"] = text[start:end].strip()
    return chunks


def make_context_builder(tokenizer):
    from src.application.context.allocation import (
        CapacityAllocator,
        DemandAllocator,
        RedistributionAllocator,
    )
    from src.application.context.context_builder import ContextBuilder
    from src.application.context.overflow_strategy_dispatcher import (
        OverflowStrategyDispatcher,
    )

    return ContextBuilder(
        tokenizer=tokenizer,
        capacity_allocator=CapacityAllocator(
            DemandAllocator(), RedistributionAllocator()
        ),
        dispatcher=OverflowStrategyDispatcher(),
    )


def make_chunk_summarizer(llm_client):
    from src.infrastructure.services.summarizers.chunk_prompt_builder import (
        ChunkPromptBuilder,
        ChunkSummarizationPrompts,
    )
    from src.infrastructure.services.summarizers.llm_chunk_summarizer import (
        LLMChunkSummarizer,
    )

    prompts = ChunkSummarizationPrompts(
        role=CONCISE_ROLE,
        system_input=CONCISE_SYSTEM_INPUT,
        output_format=CONCISE_OUTPUT_FORMAT,
    )
    return LLMChunkSummarizer(
        llm_client=llm_client, builder=ChunkPromptBuilder(prompts=prompts)
    )


def summarization_prompt_tokens(tokenizer, chunk_text: str) -> int:
    """Token count of the exact chunk-summarization prompt used by the pipeline."""
    from src.infrastructure.services.summarizers.chunk_prompt_builder import (
        ChunkPromptBuilder,
        ChunkSummarizationPrompts,
    )

    prompts = ChunkSummarizationPrompts(
        role=CONCISE_ROLE,
        system_input=CONCISE_SYSTEM_INPUT,
        output_format=CONCISE_OUTPUT_FORMAT,
    )
    prompt = ChunkPromptBuilder(prompts=prompts).build(chunk_text)
    return tokenizer.count_tokens(prompt)


def build_chunk_builder(
    cid: str,
    body: str,
    overflow_stack,
    *,
    chunk_summarizer=None,
    role: str = ROLE,
    system_input: str = SYSTEM_INPUT,
    user_input: str = USER_INPUT,
    output_format: str = OUTPUT_FORMAT,
):
    """One independent PromptBuilder per chunk, with a single CHUNKS item."""
    from src.application.context.sections.chunks_section import ChunksSection
    from src.application.prompt.prompt_builder import PromptBuilder
    from src.domain.entities import GenerationChunk

    builder = PromptBuilder(seed_defaults=True)
    builder.set_section(
        "CHUNKS",
        ChunksSection(
            [GenerationChunk(chunk_id=cid, content=body, reference=None)],
            overflow_strategies=overflow_stack,
            chunk_summarizer=chunk_summarizer,
        ),
    )
    builder.set_role(role)
    builder.set_history([])
    builder.set_system_input(system_input)
    builder.set_user_input(user_input)
    builder.set_output_format(output_format)
    return builder


def make_llm_client(
    *,
    base_url: str,
    api_key: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: float = 300.0,
    max_retries: int = 0,
):
    """Shared AsyncOpenAI + OpenAILLMClient instance used by the whole pipeline."""
    from openai import AsyncOpenAI

    from src.infrastructure.services.llm.openai_llm_client import OpenAILLMClient

    async_client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
    )
    return OpenAILLMClient(
        async_client,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )