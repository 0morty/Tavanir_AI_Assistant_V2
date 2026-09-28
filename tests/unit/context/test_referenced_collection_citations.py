"""Citation identity belongs to every referenced collection section."""

import json
import unittest
from dataclasses import dataclass

from src.application.context import ContextBuilder, OverflowStrategyDispatcher
from src.application.context.allocation import (
    CapacityAllocator,
    DemandAllocator,
    RedistributionAllocator,
)
from src.application.context.sections import ReferencedCollectionSection
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.application.llm import LLMRequestBuilder
from src.application.prompt import PromptBuilder
from src.domain.context.tokenizer import Tokenizer
from src.domain.enums import OverflowStrategy
from src.domain.overflow_strategy_stack import OverflowStrategyStack


@dataclass
class Evidence:
    source_id: str
    content: str


class RegulationSection(ReferencedCollectionSection):
    def __init__(self, items, **kwargs):
        super().__init__(items, citation_label="regulation", **kwargs)

    @property
    def section_type(self) -> str:
        return "REGULATIONS"


class CharacterTokenizer(Tokenizer):
    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        return [(ord(char), (index, index + 1)) for index, char in enumerate(text)]

    def count_tokens(self, text: str) -> int:
        return len(text)


class RecordingSummarizer(ITextSummarizer):
    def __init__(self):
        self.inputs = []

    def summarize(self, text: str, *, max_tokens: int | None = None) -> str:
        raise AssertionError("Collection summaries must be batched")

    def summarize_chunks(self, chunks: list[str], *, capacity_tokens: int) -> list[str]:
        self.inputs = list(chunks)
        return ["brief first", "brief second [regulation 999]"]


def build(section, budget):
    prompt_builder = PromptBuilder(seed_defaults=False)
    prompt_builder.add_section(section)
    return ContextBuilder(
        tokenizer=CharacterTokenizer(),
        capacity_allocator=CapacityAllocator(DemandAllocator(), RedistributionAllocator()),
        dispatcher=OverflowStrategyDispatcher(),
    ).build(prompt_builder, max_tokens=budget)


class ReferencedCollectionCitationTests(unittest.TestCase):
    def test_original_items_have_deterministic_position_ids(self):
        shared = Evidence("SRC-1", "the same evidence")
        items = [shared, shared, Evidence("SRC-2", "other evidence")]
        section = RegulationSection(items)

        self.assertEqual(section.citation_ids_for(shared), ("[regulation 001]", "[regulation 002]"))
        self.assertEqual(section.citation_map, {
            "[regulation 001]": shared,
            "[regulation 002]": shared,
            "[regulation 003]": items[2],
        })
        self.assertEqual(RegulationSection(items).citation_ids, section.citation_ids)
        self.assertEqual([item.source_id for item in section.items], ["SRC-1", "SRC-1", "SRC-2"])
        self.assertIn("Unique ID: [regulation 003]\n\nother evidence", section.prepare().content)

    def test_summary_keeps_original_mapping_through_final_request(self):
        items = [Evidence("SRC-1", "first evidence " * 15), Evidence("SRC-2", "second evidence " * 15)]
        summarizer = RecordingSummarizer()
        section = RegulationSection(
            items,
            chunk_summarizer=summarizer,
            overflow_strategies=OverflowStrategyStack([OverflowStrategy.SUMMARIZE]),
        )

        result = build(section, 100)
        output = result.sections[0]
        request = LLMRequestBuilder().build_messages(result)
        self.assertTrue(output.overflowed)
        self.assertIn("[regulation 001]", summarizer.inputs[0])
        self.assertIn("[regulation 002]", summarizer.inputs[1])
        self.assertEqual(output.citation_ids, section.citation_ids)
        self.assertIn("Unique ID: [regulation 001]\n\nbrief first", result.prompt)
        self.assertIn("Unique ID: [regulation 002]\n\nbrief second", result.prompt)
        self.assertNotIn("[regulation 999]", result.prompt)
        self.assertEqual(request, [{"role": "system", "content": result.prompt}])
        structured_output = json.loads(
            '{"answer": "supported", "citations": '
            '["[regulation 002]", "[regulation 001]", "[regulation 002]"]}'
        )
        ids = section.extract_citation_ids(structured_output)
        self.assertEqual(ids, ["[regulation 002]", "[regulation 001]"])
        resolved = section.resolve_citation_ids(ids, output)
        self.assertIs(resolved["[regulation 002]"], items[1])
        self.assertIs(resolved["[regulation 001]"], items[0])
        self.assertEqual([item.content for item in items], ["first evidence " * 15, "second evidence " * 15])

    def test_truncate_is_noop_and_ignore_rejects_removed_item(self):
        section = RegulationSection(
            [Evidence("SRC-1", "one"), Evidence("SRC-2", "two")],
            overflow_strategies=OverflowStrategyStack([OverflowStrategy.TRUNCATE, OverflowStrategy.IGNORE]),
        )
        prepared = section.prepare()
        self.assertIs(section.truncate(prepared, 1, tokenizer=CharacterTokenizer()), prepared)
        first_only = "Unique ID: [regulation 001]\n\none"
        result = build(section, len(first_only))
        output = result.sections[0]
        self.assertEqual(result.prompt, first_only)
        self.assertEqual(output.citation_ids, ("[regulation 001]",))
        self.assertEqual(section.citation_map_for(output), {"[regulation 001]": section.items[0]})
        with self.assertRaisesRegex(ValueError, "Unknown citation ID"):
            section.resolve_citation_ids(["[regulation 002]"], output)

    def test_ignore_after_summary_preserves_original_identity(self):
        items = [Evidence("SRC-1", "first evidence " * 15), Evidence("SRC-2", "second evidence " * 15)]
        section = RegulationSection(items, chunk_summarizer=RecordingSummarizer())
        summarized = section.summarize(section.prepare(), 100)
        first_only = "Unique ID: [regulation 001]\n\nbrief first"
        ignored = section.ignore(summarized, len(first_only), tokenizer=CharacterTokenizer())
        self.assertEqual(ignored.content, first_only)
        self.assertEqual(ignored.citation_ids, ("[regulation 001]",))
        self.assertIs(
            section.resolve_citation_ids(["[regulation 001]"], ignored)["[regulation 001]"],
            items[0],
        )
        with self.assertRaisesRegex(ValueError, "Unknown citation ID"):
            section.resolve_citation_ids(["[regulation 002]"], ignored)

    def test_structured_output_rejects_invalid_and_unknown_citations(self):
        section = RegulationSection([Evidence("SRC-1", "one")])
        output = build(section, 200).sections[0]
        for value in ("[regulation 01]", "[Regulation 001]", "[chunk 001]", 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                section.extract_citation_ids({"citations": [value]})
        for value in (None, "[regulation 001]", ["[regulation 001]", 1]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                section.extract_citation_ids({"citations": value})
        with self.assertRaisesRegex(ValueError, "Unknown citation ID"):
            section.resolve_citation_ids(["[regulation 999]"], output)
        with self.assertRaises(ValueError):
            section.extract_citation_ids({"answer": "missing citations"})
        with self.assertRaises(ValueError):
            section.extract_citation_ids("not structured output")

    def test_three_digit_limit_is_generic(self):
        with self.assertRaises(ValueError):
            RegulationSection([Evidence(str(index), "x") for index in range(1000)])


if __name__ == "__main__":
    unittest.main()
