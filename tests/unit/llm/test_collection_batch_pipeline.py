"""Collection transformations preserve batch isolation and source items."""

import unittest

from src.application.context import ContextBuilder, OverflowStrategyDispatcher
from src.application.context.allocation import (
    CapacityAllocator,
    DemandAllocator,
    RedistributionAllocator,
)
from src.application.context.sections import ChunksSection, HistorySection
from src.application.context.sections.referenced_collection_section import (
    ReferencedCollectionSection,
)
from src.application.prompt import PromptBuilder
from src.domain.context.summarizer import Summarizer
from src.domain.entities import GenerationChunk, HistoryMessage, Reference
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


class FluentReference(Reference):
    @property
    def description(self) -> str:
        return "reference"

    def fluent_text(self) -> str:
        return "REF:"


class FramedCollection(ReferencedCollectionSection):
    @property
    def section_type(self) -> str:
        return "FRAMED"

    @property
    def pre_context(self) -> str:
        return "PRE"

    @property
    def post_context(self) -> str:
        return "POST"


class CollectionBatchPipelineTests(unittest.TestCase):
    def test_chunks_map_independent_batch_outputs_by_index(self) -> None:
        llm = RecordingLLM("first summary", "second summary")
        originals = [
            GenerationChunk(chunk_id="1", content="FIRST_UNIQUE " * 10),
            GenerationChunk(chunk_id="2", content="SECOND_UNIQUE " * 10),
        ]
        section = ChunksSection(
            originals,
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
        ).build(builder, max_tokens=75)

        self.assertEqual([item.content for item in result.sections[0].items], [
            "first summary", "second summary"
        ])
        self.assertEqual([item.chunk_id for item in result.sections[0].items], ["1", "2"])
        self.assertIsNot(result.sections[0].items[0], originals[0])
        self.assertEqual(originals[0].content, "FIRST_UNIQUE " * 10)
        self.assertEqual(section.chunks, tuple(originals))
        self.assertEqual(len(llm.batches), 1)
        self.assertEqual(len(llm.batches[0]), 2)
        self.assertIn("FIRST_UNIQUE", llm.batches[0][0])
        self.assertNotIn("SECOND_UNIQUE", llm.batches[0][0])
        self.assertIn("SECOND_UNIQUE", llm.batches[0][1])
        self.assertNotIn("FIRST_UNIQUE", llm.batches[0][1])
        self.assertIn("Relevant context chunks:", llm.batches[0][0])

    def test_plain_collection_fallback_never_joins_inputs(self) -> None:
        summarizer = RecordingPlainSummarizer()
        section = ChunksSection(
            [
                GenerationChunk(chunk_id="1", content="FIRST_UNIQUE"),
                GenerationChunk(chunk_id="2", content="SECOND_UNIQUE"),
            ],
            summarizer=summarizer,
        )
        result = section.summarize(section.prepare(), 100)
        self.assertEqual([item.content for item in result.items], ["summary-1", "summary-2"])
        self.assertEqual(len(summarizer.inputs), 2)
        self.assertNotIn("SECOND_UNIQUE", summarizer.inputs[0])
        self.assertNotIn("FIRST_UNIQUE", summarizer.inputs[1])

    def test_pre_post_and_references_are_in_each_processing_input(self) -> None:
        llm = RecordingLLM("A", "B")
        section = FramedCollection(
            [
                GenerationChunk("1", "first", FluentReference()),
                GenerationChunk("2", "second", FluentReference()),
            ],
            reference=FluentReference(),
            chunk_summarizer=LLMChunkSummarizer(llm, max_attempts=1),
        )
        prepared = section.prepare()
        result = section.summarize(prepared, 200)

        self.assertEqual([item.content for item in result.items], ["A", "B"])
        self.assertEqual(len(llm.batches), 1)
        for index, own in enumerate(("first", "second")):
            prompt = llm.batches[0][index]
            self.assertIn("PRE", prompt)
            self.assertIn("POST", prompt)
            self.assertIn("REF:", prompt)
            self.assertIn(own, prompt)
            self.assertNotIn(("second", "first")[index], prompt)
        self.assertEqual(section.items[0].content, "first")

    def test_context_builder_ignore_returns_only_whole_chunk_prefix(self) -> None:
        originals = [
            GenerationChunk("1", "one"),
            GenerationChunk("2", "SECOND_LONG_CONTENT"),
        ]
        section = ChunksSection(
            originals,
            overflow_strategies=OverflowStrategyStack([OverflowStrategy.IGNORE]),
        )
        builder = PromptBuilder(seed_defaults=False)
        builder.add_section(section)
        result = ContextBuilder(
            tokenizer=CharacterTokenizer(),
            capacity_allocator=CapacityAllocator(
                DemandAllocator(), RedistributionAllocator()
            ),
            dispatcher=OverflowStrategyDispatcher(),
        ).build(
            builder,
            max_tokens=len("Relevant context chunks:\n\nChunk 1:\none"),
        )

        self.assertEqual(result.sections[0].items, (originals[0],))
        self.assertEqual(
            result.sections[0].content,
            "Relevant context chunks:\n\nChunk 1:\none",
        )
        self.assertEqual(len(section.items), 2)

    def test_collection_truncate_returns_original_result_unchanged(self) -> None:
        section = ChunksSection([GenerationChunk("1", "original")])
        prepared = section.prepare()
        self.assertIs(
            section.truncate(prepared, 1, tokenizer=CharacterTokenizer()),
            prepared,
        )
        self.assertEqual(section.items[0].content, "original")

    def test_history_summaries_keep_original_roles(self) -> None:
        llm = RecordingLLM("empty turn summary", "nonempty summary")
        history = HistorySection(
            [
                HistoryMessage(HistoryRole.USER, ""),
                HistoryMessage(HistoryRole.ASSISTANT, "LONG_CONTENT " * 10),
            ],
            chunk_summarizer=LLMChunkSummarizer(llm, max_attempts=1),
        )
        result = history.summarize(history.prepare(), 100)
        self.assertEqual(
            result.items,
            (
                HistoryMessage(HistoryRole.USER, "empty turn summary"),
                HistoryMessage(HistoryRole.ASSISTANT, "nonempty summary"),
            ),
        )
        self.assertEqual(history.items[0].content, "")
        self.assertEqual(len(llm.batches[0]), 2)
        self.assertIn("user: ", llm.batches[0][0])
        self.assertIn("assistant: LONG_CONTENT", llm.batches[0][1])


if __name__ == "__main__":
    unittest.main()
