"""Final model output is validated against retained Generation evidence."""

import json
import unittest

from src.application.context import ContextBuilder, OverflowStrategyDispatcher
from src.application.context.allocation import (
    CapacityAllocator,
    DemandAllocator,
    RedistributionAllocator,
)
from src.application.context.sections import ChunksSection, SimilarSuggestionsSection
from src.application.dtos import SimilarSuggestionInput
from src.application.exceptions import (
    LLMInvalidCitationError,
    LLMOutputParseError,
    LLMOutputSchemaError,
    LLMUnknownCitationError,
)
from src.application.interfaces.i_output_parser import IOutputParser
from src.application.prompt import PromptBuilder
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import GenerationChunk
from src.domain.enums import OverflowStrategy, SuggestionStatus
from src.domain.overflow_strategy_stack import OverflowStrategyStack
from src.infrastructure.services.llm.output_parser import GenerationOutputParser


class CharacterTokenizer(Tokenizer):
    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        return [(ord(char), (index, index + 1)) for index, char in enumerate(text)]

    def count_tokens(self, text: str) -> int:
        return len(text)


class GenerationOutputParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = GenerationOutputParser()
        self.chunks = [
            GenerationChunk("SOURCE-A", "first original"),
            GenerationChunk("SOURCE-B", "second original"),
            GenerationChunk("SOURCE-C", "third original"),
        ]
        self.section = ChunksSection(self.chunks)
        self.retained = self.section.citation_map_for(self.section.prepare())

    def test_implements_port_and_returns_original_chunks_in_first_seen_order(self) -> None:
        self.assertIsInstance(self.parser, IOutputParser)
        raw = json.dumps(
            {
                "answer": "Supported by two sources.",
                "citations": ["[chunk 003]", "[chunk 001]", "[chunk 003]"],
            }
        )

        result = self.parser.parse(raw, citation_map=self.retained)

        self.assertEqual(result.answer, "Supported by two sources.")
        self.assertEqual(len(result.citations), 2)
        self.assertIs(result.citations[0], self.chunks[2])
        self.assertIs(result.citations[1], self.chunks[0])
        self.assertTrue(all(type(item) is GenerationChunk for item in result.citations))

    def test_empty_citations_do_not_infer_ids_from_answer_text(self) -> None:
        raw = json.dumps({"answer": "Mentions [chunk 001].", "citations": []})

        result = self.parser.parse(raw, citation_map={})

        self.assertEqual(result.answer, "Mentions [chunk 001].")
        self.assertEqual(result.citations, [])

    def test_similar_label_citations_use_the_same_retained_map_contract(self) -> None:
        retained = {
            "[similar 001]": self.chunks[0],
            "[similar 003]": self.chunks[2],
        }
        raw = json.dumps(
            {
                "answer": "Supported.",
                "citations": ["[similar 001]", "[similar 001]", "[similar 003]"],
            }
        )

        result = self.parser.parse(raw, citation_map=retained)

        self.assertEqual(len(result.citations), 2)
        self.assertIs(result.citations[0], self.chunks[0])
        self.assertIs(result.citations[1], self.chunks[2])

    def test_rejects_empty_malformed_and_non_object_output(self) -> None:
        cases = (
            ("", LLMOutputParseError),
            ("   ", LLMOutputParseError),
            ('{"answer":', LLMOutputParseError),
            ('```json\n{"answer": "yes", "citations": []}\n```', LLMOutputParseError),
            ('["answer", "citations"]', LLMOutputSchemaError),
        )
        for raw, error_type in cases:
            with self.subTest(raw=raw), self.assertRaises(error_type):
                self.parser.parse(raw, citation_map=self.retained)

    def test_rejects_invalid_answer_and_citations_schema(self) -> None:
        cases = (
            {"citations": []},
            {"answer": "", "citations": []},
            {"answer": "  \n ", "citations": []},
            {"answer": 7, "citations": []},
            {"answer": "yes"},
            {"answer": "yes", "citations": None},
            {"answer": "yes", "citations": "[chunk 001]"},
        )
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(LLMOutputSchemaError):
                self.parser.parse(json.dumps(payload), citation_map=self.retained)

    def test_rejects_non_string_and_malformed_citation_ids(self) -> None:
        for citation in (1, None, "[Chunk 001]", "[chunk 01]", "[chunk 1000]", "SOURCE-A"):
            with self.subTest(citation=citation), self.assertRaises(LLMInvalidCitationError):
                self.parser.parse(
                    json.dumps({"answer": "yes", "citations": [citation]}),
                    citation_map=self.retained,
                )

    def test_rejects_unknown_and_removed_citations(self) -> None:
        with self.assertRaises(LLMUnknownCitationError):
            self.parser.parse(
                '{"answer": "yes", "citations": ["[chunk 999]"]}',
                citation_map=self.retained,
            )

        section = ChunksSection(
            self.chunks,
            overflow_strategies=OverflowStrategyStack([OverflowStrategy.IGNORE]),
        )
        prepared = section.prepare()
        first_only = section.pre_context + section.separator + prepared.item_bodies[0]
        builder = PromptBuilder(seed_defaults=False)
        builder.add_section(section)
        fitted = ContextBuilder(
            tokenizer=CharacterTokenizer(),
            capacity_allocator=CapacityAllocator(
                DemandAllocator(), RedistributionAllocator()
            ),
            dispatcher=OverflowStrategyDispatcher(),
        ).build(builder, max_tokens=len(first_only))
        fitted_map = section.citation_map_for(fitted.sections[0])
        self.assertEqual(list(fitted_map), ["[chunk 001]"])
        with self.assertRaises(LLMUnknownCitationError):
            self.parser.parse(
                '{"answer": "yes", "citations": ["[chunk 002]"]}',
                citation_map=fitted_map,
            )

    def test_rejects_citation_that_does_not_resolve_to_generation_chunk(self) -> None:
        suggestion = SimilarSuggestionInput(
            id="SUG-001",
            status=SuggestionStatus.PENDING,
            title="Proposal title",
            problem="Problem statement",
            solution="Proposed solution",
            similarity=0.8,
        )
        section = SimilarSuggestionsSection([suggestion])
        retained = section.citation_map_for(section.prepare())

        with self.assertRaises(LLMInvalidCitationError):
            self.parser.parse(
                '{"answer": "yes", "citations": ["[similar 001]"]}',
                citation_map=retained,
            )


if __name__ == "__main__":
    unittest.main()
