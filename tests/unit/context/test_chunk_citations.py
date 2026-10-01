"""Citation identity stays with each chunk through rendering and overflow."""

import re
import unittest
from dataclasses import dataclass

from src.application.context import ContextBuilder, OverflowStrategyDispatcher
from src.application.context.allocation import (
    CapacityAllocator,
    DemandAllocator,
    RedistributionAllocator,
)
from src.application.context.sections import ChunksSection
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.application.llm import LLMRequestBuilder
from src.application.prompt import PromptBuilder
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import GenerationChunk, Reference
from src.domain.enums import OverflowStrategy
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class CharacterTokenizer(Tokenizer):
    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        return [(ord(char), (index, index + 1)) for index, char in enumerate(text)]

    def count_tokens(self, text: str) -> int:
        return len(text)


@dataclass(frozen=True)
class SourceReference(Reference):
    title: str

    @property
    def description(self) -> str:
        return "Test source"

    def fluent_text(self) -> str:
        return f"Source: {self.title}"


class RecordingSummarizer(ITextSummarizer):
    def __init__(self) -> None:
        self.batches: list[tuple[str, ...]] = []

    def summarize(self, text: str, *, max_tokens: int | None = None) -> str:
        raise AssertionError("Chunk summaries must be batched")

    def summarize_chunks(self, chunks: list[str], *, capacity_tokens: int) -> list[str]:
        self.batches.append(tuple(chunks))
        return ["Chunk 1: brief first", "brief second [chunk 999]"]


def context_builder() -> ContextBuilder:
    return ContextBuilder(
        tokenizer=CharacterTokenizer(),
        capacity_allocator=CapacityAllocator(DemandAllocator(), RedistributionAllocator()),
        dispatcher=OverflowStrategyDispatcher(),
    )


def build_section(section: ChunksSection, budget: int):
    builder = PromptBuilder(seed_defaults=False)
    builder.add_section(section)
    return context_builder().build(builder, max_tokens=budget)


class ChunkCitationTests(unittest.TestCase):
    def test_mapping_is_short_ordered_unique_and_direct_to_items(self) -> None:
        chunks = [
            GenerationChunk("SUG-004", "four"),
            GenerationChunk("SUG-002", "two"),
            GenerationChunk("SUG-009", "nine"),
        ]
        section = ChunksSection(chunks)
        expected = {
            "[chunk 001]": chunks[0],
            "[chunk 002]": chunks[1],
            "[chunk 003]": chunks[2],
        }
        self.assertEqual(section.citation_map, expected)
        self.assertEqual(ChunksSection(chunks).citation_map, expected)
        self.assertIs(section.citation_map["[chunk 001]"], chunks[0])
        self.assertIs(section.citation_map["[chunk 002]"], chunks[1])
        self.assertIs(section.citation_map["[chunk 003]"], chunks[2])
        self.assertNotIn("SUG-004", section.render())
        self.assertEqual(len(section.citation_map), len(chunks))
        self.assertTrue(all(re.fullmatch(r"\[chunk [0-9]{3}\]", key) for key in expected))

    def test_equal_chunks_still_receive_distinct_position_ids(self) -> None:
        shared = GenerationChunk("SUG-001", "same", SourceReference("A"))
        section = ChunksSection([shared, shared])
        self.assertEqual(list(section.citation_map), ["[chunk 001]", "[chunk 002]"])
        self.assertEqual(section.prepare().content.count("Unique ID: [chunk 001]"), 1)
        self.assertEqual(section.prepare().content.count("Unique ID: [chunk 002]"), 1)

    def test_reference_then_citation_then_chunk_content(self) -> None:
        section = ChunksSection([
            GenerationChunk("SUG-001", "The first proposal.", SourceReference("Study A")),
            GenerationChunk("SUG-002", "The second proposal."),
        ])
        rendered = section.prepare().content
        self.assertIn(
            "Source: Study A\nUnique ID: [chunk 001]\n\nThe first proposal.",
            rendered,
        )
        self.assertIn("Unique ID: [chunk 002]\n\nThe second proposal.", rendered)
        self.assertLess(rendered.index("[chunk 001]"), rendered.index("[chunk 002]"))
        self.assertEqual(section.item_content(section.chunks[0]), "The first proposal.")
        self.assertNotRegex(rendered, r"\bChunk [0-9]+:")

    def test_summarization_reattaches_reference_and_id_without_model_help(self) -> None:
        summarizer = RecordingSummarizer()
        source = [
            GenerationChunk("SUG-001", "first evidence " * 15, SourceReference("Study A")),
            GenerationChunk("SUG-002", "second evidence " * 15, SourceReference("Study B")),
        ]
        section = ChunksSection(
            source,
            chunk_summarizer=summarizer,
            overflow_strategies=OverflowStrategyStack([OverflowStrategy.SUMMARIZE]),
        )
        result = build_section(section, 230)
        output = result.sections[0]
        self.assertTrue(output.overflowed)
        self.assertEqual(len(summarizer.batches), 1)
        self.assertEqual(len(summarizer.batches[0]), 2)
        self.assertIn("[chunk 001]", summarizer.batches[0][0])
        self.assertNotIn("second evidence", summarizer.batches[0][0])
        self.assertIn("[chunk 002]", summarizer.batches[0][1])
        self.assertNotIn("first evidence", summarizer.batches[0][1])
        self.assertTrue(all(re.search(r"\bChunk [0-9]+:", text) is None for text in summarizer.batches[0]))
        self.assertIn("Source: Study A\nUnique ID: [chunk 001]\n\nbrief first", output.content)
        self.assertIn("Source: Study B\nUnique ID: [chunk 002]\n\nbrief second", output.content)
        self.assertNotIn("[chunk 999]", output.content)
        self.assertNotRegex(output.content, r"\bChunk [0-9]+:")
        self.assertNotRegex(result.prompt, r"\bChunk [0-9]+:")
        self.assertEqual(output.items[0].content, "brief first")
        self.assertEqual([item.chunk_id for item in output.items], ["SUG-001", "SUG-002"])
        self.assertEqual([item.reference for item in output.items], [item.reference for item in source])
        self.assertEqual([item.content for item in source], ["first evidence " * 15, "second evidence " * 15])
        self.assertEqual(LLMRequestBuilder().build_messages(result), [
            {"role": "system", "content": result.prompt}
        ])
        self.assertLessEqual(result.total_tokens, result.budget_tokens)

    def test_truncate_noop_then_ignore_keeps_only_surviving_citations(self) -> None:
        section = ChunksSection(
            [
                GenerationChunk("SUG-001", "one", SourceReference("A")),
                GenerationChunk("SUG-002", "two", SourceReference("B")),
            ],
            overflow_strategies=OverflowStrategyStack([
                OverflowStrategy.TRUNCATE, OverflowStrategy.IGNORE
            ]),
        )
        prepared = section.prepare()
        self.assertIs(section.truncate(prepared, 1, tokenizer=CharacterTokenizer()), prepared)
        first_only = "Relevant context chunks:\n\nSource: A\nUnique ID: [chunk 001]\n\none"
        result = build_section(section, len(first_only))
        output = result.sections[0]
        self.assertEqual(output.content, first_only)
        self.assertEqual([item.chunk_id for item in output.items], ["SUG-001"])
        self.assertEqual(section.citation_map_for(output), {"[chunk 001]": section.chunks[0]})
        self.assertNotIn("[chunk 002]", result.prompt)
        self.assertIs(
            section.resolve_citation_ids(["[chunk 001]"], output)["[chunk 001]"],
            section.chunks[0],
        )
        with self.assertRaisesRegex(ValueError, "Unknown citation ID"):
            section.resolve_citation_ids(["[chunk 002]"], output)

    def test_structured_extraction_is_exact_ordered_unique_and_rejects_unknown_ids(self) -> None:
        section = ChunksSection([
            GenerationChunk("SUG-001", "one"), GenerationChunk("SUG-002", "two")
        ])
        output = build_section(section, 200).sections[0]
        structured = {"answer": "supported", "citations": [
            "[chunk 002]", "[chunk 001]", "[chunk 002]"
        ]}
        ids = section.extract_citation_ids(structured)
        self.assertEqual(ids, ["[chunk 002]", "[chunk 001]"])
        resolved = section.resolve_citation_ids(ids, output)
        self.assertIs(resolved["[chunk 002]"], section.chunks[1])
        self.assertIs(resolved["[chunk 001]"], section.chunks[0])
        with self.assertRaisesRegex(ValueError, "Unknown citation ID"):
            section.resolve_citation_ids(["[chunk 999]"], output)
        for invalid in ("[Chunk 001]", "[chunk 01]", "[chunk 0001]", "[chunk abc]"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                section.extract_citation_ids({"citations": [invalid]})

    def test_three_digit_limit_is_enforced(self) -> None:
        with self.assertRaises(ValueError):
            ChunksSection([GenerationChunk(str(index), "text") for index in range(1000)])


if __name__ == "__main__":
    unittest.main()
