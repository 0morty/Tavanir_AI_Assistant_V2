"""Generation output contains resolved source chunks, not prompt citation IDs."""

import unittest
from dataclasses import FrozenInstanceError, fields
from typing import get_type_hints

import src.application.dtos as dtos
from src.application.context.sections import ChunksSection
from src.application.dtos import GenerationResult, SimilarSuggestionInput
from src.domain.entities import GenerationChunk


class GenerationResultTests(unittest.TestCase):
    def test_answer_with_no_citations(self) -> None:
        result = GenerationResult(answer="No supporting evidence.", citations=[])

        self.assertEqual(result.answer, "No supporting evidence.")
        self.assertEqual(result.citations, [])
        with self.assertRaises(FrozenInstanceError):
            result.answer = "Changed"

    def test_contract_contains_chunks_without_citation_wrapper(self) -> None:
        chunks = [GenerationChunk("source-a", "first"), GenerationChunk("source-b", "second")]
        result = GenerationResult(answer="Supported.", citations=chunks)

        self.assertEqual([field.name for field in fields(GenerationResult)], ["answer", "citations", "uncertainty"])
        self.assertEqual(get_type_hints(GenerationResult)["citations"], list[GenerationChunk | SimilarSuggestionInput])
        self.assertFalse(hasattr(dtos, "ResolvedCitation"))
        self.assertEqual(len(result.citations), 2)
        self.assertTrue(all(type(citation) is GenerationChunk for citation in result.citations))
        self.assertIs(result.citations[0], chunks[0])
        self.assertIs(result.citations[1], chunks[1])

    def test_existing_resolution_supplies_original_chunks_to_result(self) -> None:
        chunks = [GenerationChunk("source-a", "first"), GenerationChunk("source-b", "second")]
        section = ChunksSection(chunks)
        prepared = section.prepare()
        output = {
            "answer": "The second and first sources support this.",
            "citations": ["[chunk 002]", "[chunk 001]", "[chunk 002]"],
        }

        citation_ids = section.extract_citation_ids(output)
        resolved = section.resolve_citation_ids(citation_ids, prepared)
        result = GenerationResult(answer=output["answer"], citations=list(resolved.values()))

        self.assertEqual(citation_ids, ["[chunk 002]", "[chunk 001]"])
        self.assertIs(result.citations[0], chunks[1])
        self.assertIs(result.citations[1], chunks[0])
        self.assertTrue(all(type(citation) is GenerationChunk for citation in result.citations))
        self.assertNotIn("citation_id", [field.name for field in fields(result)])
        self.assertNotIn("[chunk 002]", result.citations)


if __name__ == "__main__":
    unittest.main()
