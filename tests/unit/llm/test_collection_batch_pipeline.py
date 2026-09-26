"""Collection overflow keeps one LLM request and result per input item."""

import unittest

from src.application.context import ContextBuilder, OverflowStrategyDispatcher
from src.application.context.allocation import (
    CapacityAllocator,
    DemandAllocator,
    RedistributionAllocator,
)
from src.application.context.sections import ChunksSection, HistorySection
from src.application.prompt import PromptBuilder
from src.domain.context.summarizer import Summarizer
from src.domain.entities import GenerationChunk, HistoryMessage
from src.domain.enums import HistoryRole, OverflowStrategy
from src.domain.overflow_strategy_stack import OverflowStrategyStack
from src.infrastructure.services.summarizers import LLMChunkSummarizer
from tests.unit.llm.test_llm_request_builder_pipeline import CharacterTokenizer


class RecordingLLM:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.batches: list[list[str]] = []

    def complete(self, prompt: str) -> str:
        raise AssertionError("Collection summarization must use complete_many")

    def complete_many(self, prompts: list[str]) -> list[str]:
        self.batches.append(list(prompts))
        return [self.responses.pop(0) for _ in prompts]


class RecordingPlainSummarizer(Summarizer):
    def __init__(self) -> None:
        self.inputs: list[str] = []

    def summarize(self, text: str) -> str:
        self.inputs.append(text)
        return f"summary-{len(self.inputs)}"


class CollectionBatchPipelineTests(unittest.TestCase):
    def test_chunks_use_one_independent_prompt_per_item_in_one_batch(self) -> None:
        llm = RecordingLLM("first summary", "second summary")
        source_chunks = [
            GenerationChunk(chunk_id="1", content="FIRST_UNIQUE " * 10),
            GenerationChunk(chunk_id="2", content="SECOND_UNIQUE " * 10),
        ]
        section = ChunksSection(
            source_chunks,
            chunk_summarizer=LLMChunkSummarizer(llm, max_attempts=1),
            overflow_strategies=OverflowStrategyStack([OverflowStrategy.SUMMARIZE]),
        )
        builder = PromptBuilder(seed_defaults=False)
        builder.add_section(section)
        result = ContextBuilder(
            tokenizer=CharacterTokenizer(),
            capacity_allocator=CapacityAllocator(
                DemandAllocator(), RedistributionAllocator()
            ),
            dispatcher=OverflowStrategyDispatcher(),
        ).build(builder, max_tokens=35)

        self.assertEqual(result.sections[0].content, "first summary\n\nsecond summary")
        self.assertEqual([chunk.content for chunk in section.chunks], [
            "first summary", "second summary"
        ])
        self.assertEqual([chunk.chunk_id for chunk in section.chunks], ["1", "2"])
        self.assertIsNot(section.chunks[0], source_chunks[0])
        self.assertEqual(source_chunks[0].content, "FIRST_UNIQUE " * 10)
        self.assertEqual(source_chunks[1].content, "SECOND_UNIQUE " * 10)
        self.assertEqual(len(llm.batches), 1)
        self.assertEqual(len(llm.batches[0]), 2)
        self.assertIn("FIRST_UNIQUE", llm.batches[0][0])
        self.assertNotIn("SECOND_UNIQUE", llm.batches[0][0])
        self.assertIn("SECOND_UNIQUE", llm.batches[0][1])
        self.assertNotIn("FIRST_UNIQUE", llm.batches[0][1])

    def test_plain_collection_fallback_never_sends_joined_items(self) -> None:
        summarizer = RecordingPlainSummarizer()
        section = ChunksSection(
            [
                GenerationChunk(chunk_id="1", content="FIRST_UNIQUE"),
                GenerationChunk(chunk_id="2", content="SECOND_UNIQUE"),
            ],
            summarizer=summarizer,
        )

        self.assertEqual(
            section.summarize("ignored joined input", 100),
            "summary-1\n\nsummary-2",
        )
        self.assertEqual([chunk.content for chunk in section.chunks], [
            "summary-1", "summary-2"
        ])
        self.assertEqual(len(summarizer.inputs), 2)
        self.assertIn("FIRST_UNIQUE", summarizer.inputs[0])
        self.assertNotIn("SECOND_UNIQUE", summarizer.inputs[0])
        self.assertIn("SECOND_UNIQUE", summarizer.inputs[1])
        self.assertNotIn("FIRST_UNIQUE", summarizer.inputs[1])

    def test_later_overflow_strategy_clears_unselected_batch_results(self) -> None:
        source = GenerationChunk(chunk_id="1", content="ORIGINAL_CONTENT")
        section = ChunksSection(
            [source],
            chunk_summarizer=LLMChunkSummarizer(
                RecordingLLM("summary longer than capacity"), max_attempts=1
            ),
        )

        section.summarize("ignored", 5)
        self.assertEqual(section.chunks[0].content, "summary longer than capacity")
        section.truncate("ignored", 5, tokenizer=CharacterTokenizer())

        self.assertIsNone(section.summarized_items)
        self.assertIs(section.chunks[0], source)
        self.assertEqual(source.content, "ORIGINAL_CONTENT")

    def test_empty_history_turn_still_keeps_its_role_after_summary(self) -> None:
        llm = RecordingLLM("empty turn summary", "nonempty summary")
        history = HistorySection(
            [
                HistoryMessage(HistoryRole.USER, ""),
                HistoryMessage(HistoryRole.ASSISTANT, "LONG_CONTENT " * 10),
            ],
            chunk_summarizer=LLMChunkSummarizer(llm, max_attempts=1),
        )

        history.summarize("ignored joined input", 100)

        self.assertEqual(len(llm.batches), 1)
        self.assertEqual(len(llm.batches[0]), 2)
        self.assertIn("user: ", llm.batches[0][0])
        self.assertNotIn("assistant: ", llm.batches[0][0])
        self.assertIn("assistant: LONG_CONTENT", llm.batches[0][1])
        self.assertNotIn("user: ", llm.batches[0][1])
        self.assertEqual(
            history.fitted_messages,
            (
                HistoryMessage(HistoryRole.USER, "empty turn summary"),
                HistoryMessage(HistoryRole.ASSISTANT, "nonempty summary"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
