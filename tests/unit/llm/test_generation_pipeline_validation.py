"""Executable Generation boundary checks with deterministic English inputs.

Run from the repository root with
``python3 -m unittest tests.unit.llm.test_generation_pipeline_validation -v``.
The provider is scripted and the tokenizer counts Unicode characters, not model tokens.
"""

import json
import unittest

from src.application.context import ContextBuilder, OverflowStrategyDispatcher
from src.application.context.allocation import (
    CapacityAllocator,
    DemandAllocator,
    RedistributionAllocator,
)
from src.application.context.sections import (
    ChunksSection,
    OutputFormatSection,
    RoleSection,
    SystemInputSection,
    UserInputSection,
)
from src.application.interfaces.i_llm_client import ILLMClient
from src.application.llm import LLMRequestBuilder
from src.application.prompt import PromptBuilder
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import GenerationChunk, Reference
from src.domain.enums import OverflowStrategy
from src.domain.overflow_strategy_stack import OverflowStrategyStack
from src.infrastructure.services.summarizers.chunk_prompt_builder import (
    ChunkPromptBuilder,
    ChunkSummarizationPrompts,
)
from src.infrastructure.services.summarizers.llm_chunk_summarizer import (
    LLMChunkSummarizer,
)


class CharacterTokenizer(Tokenizer):
    @property
    def supports_offset_mapping(self):
        return True

    def encode(self, text):
        return [(ord(char), (index, index + 1)) for index, char in enumerate(text)]

    def count_tokens(self, text):
        return len(text)


class StudyReference(Reference):
    def __init__(self, title, page):
        self.title = title
        self.page = page

    @property
    def description(self):
        return "Study title and source page."

    def fluent_text(self):
        return f'Reference: There is a title "{self.title}" on page {self.page}:'


class ScriptedLLM(ILLMClient):
    def __init__(self, response, summaries=()):
        self.response = response
        self.summaries = list(summaries)
        self.prompts = []
        self.batches = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return self.response

    def complete_many(self, prompts):
        self.batches.append(tuple(prompts))
        return self.summaries[: len(prompts)]


def chunks():
    return [
        GenerationChunk("SOURCE-A", "South-facing living rooms carry winter daylight inward. Pale walls reduce daytime lamp use.", StudyReference("Room orientation study", 12)),
        GenerationChunk("SOURCE-B", "A light shelf directs clerestory daylight toward the center of a narrow home. Dust and glare require review.", StudyReference("Light shelf and clerestory study", 14)),
        GenerationChunk("SOURCE-C", "Daylight sensors dim LED circuits when measured light is sufficient. Commissioning prevents flicker.", StudyReference("Lighting controls trial", 19)),
    ]


def context(builder, budget):
    return ContextBuilder(
        tokenizer=CharacterTokenizer(),
        capacity_allocator=CapacityAllocator(DemandAllocator(), RedistributionAllocator()),
        dispatcher=OverflowStrategyDispatcher(),
    ).build(builder, max_tokens=budget)


class GenerationPipelineValidationTests(unittest.TestCase):
    def test_manual_prompt_provider_response_and_citation_lifecycle(self):
        sources = chunks()
        collection = ChunksSection(sources)
        builder = PromptBuilder(seed_defaults=False)
        builder.add_section(RoleSection("You are an electricity proposal analyst."))
        builder.add_section(collection)
        builder.add_section(SystemInputSection(
            "Use the evidence below. Preserve Reference and Unique ID when processing cited content. "
            "State uncertainty and return decision support only."
        ))
        builder.add_section(UserInputSection("Assess daylight design for homes with low daytime lamp use."))
        builder.add_section(OutputFormatSection(
            'Return JSON with an answer string and citations array of exact Unique ID values.'
        ))
        prepared = {section.section_type: section.prepare() for section in builder.sections}
        budget = sum(len(part.content) for part in prepared.values()) + 20
        result = context(builder, budget)
        request = LLMRequestBuilder().build(
            result, model="scripted-validation-model", temperature=0.2, max_tokens=256
        )
        raw = json.dumps({
            "answer": "Light shelves and daylight controls are related approaches.",
            "citations": ["[chunk 002]", "[chunk 003]", "[chunk 002]"],
        })
        provider = ScriptedLLM(raw)
        observed_raw = provider.complete(result.prompt)
        parsed = json.loads(observed_raw)
        cited = collection.extract_citation_ids(parsed)
        resolved = collection.resolve_citation_ids(cited, result.sections[1])

        self.assertEqual([part.section_type for part in result.sections],
                         ["ROLE", "CHUNKS", "SYSTEM-INPUT", "USER-INPUT", "OUTPUT-FORMAT"])
        self.assertEqual(collection.citation_ids,
                         ("[chunk 001]", "[chunk 002]", "[chunk 003]"))
        self.assertEqual(list(collection.citation_map.values()), sources)
        self.assertEqual([item.chunk_id for item in sources],
                         ["SOURCE-A", "SOURCE-B", "SOURCE-C"])
        for index, item in enumerate(sources, 1):
            rendered = (
                f'{item.reference.fluent_text()}\nUnique ID: [chunk {index:03d}]\n\n'
                f'{item.content}'
            )
            self.assertIn(rendered, result.prompt)
        self.assertNotRegex(result.prompt, r"\bChunk [0-9]+:")
        self.assertIn("Preserve Reference and Unique ID", result.prompt)
        self.assertEqual(result.total_tokens, len(result.prompt))
        self.assertLessEqual(result.total_tokens, budget)
        self.assertEqual(request["messages"], [{"role": "system", "content": result.prompt}])
        self.assertEqual(request["model"], "scripted-validation-model")
        self.assertEqual(request["temperature"], 0.2)
        self.assertEqual(request["max_tokens"], 256)
        self.assertEqual(provider.prompts, [result.prompt])
        self.assertEqual(parsed["answer"], "Light shelves and daylight controls are related approaches.")
        self.assertEqual(cited, ["[chunk 002]", "[chunk 003]"])
        self.assertEqual(list(resolved), cited)
        self.assertIs(resolved["[chunk 002]"], sources[1])
        self.assertIs(resolved["[chunk 003]"], sources[2])
        self.assertNotIn("[chunk 001]", resolved)

    def test_empty_and_single_reference_collections(self):
        empty = ChunksSection([])
        self.assertEqual(empty.prepare().content, "")
        self.assertEqual(empty.citation_map, {})
        self.assertEqual(empty.extract_citation_ids({"citations": []}), [])
        single = ChunksSection(chunks()[:1])
        prepared = single.prepare()
        self.assertEqual(single.citation_ids, ("[chunk 001]",))
        self.assertIn("Unique ID: [chunk 001]", prepared.content)
        self.assertIs(single.resolve_citation_ids(["[chunk 001]"], prepared)["[chunk 001]"], single.items[0])

    def test_summarization_rebinds_reference_and_citation_without_model_help(self):
        sources = chunks()
        provider = ScriptedLLM("unused", ["South rooms reduce lamp use.", "Light shelf redirects daylight.", "Sensors dim LEDs."])
        summarizer = LLMChunkSummarizer(
            provider,
            builder=ChunkPromptBuilder(ChunkSummarizationPrompts(
                role="Summarize this source accurately.",
                system_input="Keep the central mechanism and limitation of this source only.",
                output_format="Return one concise English summary.",
            )),
            max_attempts=1,
        )
        collection = ChunksSection(
            sources,
            chunk_summarizer=summarizer,
            overflow_strategies=OverflowStrategyStack([OverflowStrategy.SUMMARIZE]),
        )
        original = collection.prepare()
        summarized = collection.summarize(original, 500)
        self.assertIsNotNone(summarized)
        self.assertEqual(len(provider.batches), 1)
        self.assertEqual(len(provider.batches[0]), 3)
        self.assertLess(len(summarized.content), len(original.content))
        self.assertEqual(summarized.citation_ids, original.citation_ids)
        self.assertEqual([item.chunk_id for item in summarized.items], [item.chunk_id for item in sources])
        self.assertEqual([item.content for item in sources], [item.content for item in chunks()])
        for index, (source, prompt, summary) in enumerate(zip(sources, provider.batches[0], provider.summaries), 1):
            self.assertIn(source.content, prompt)
            self.assertIn(source.reference.fluent_text(), prompt)
            self.assertIn(f"Unique ID: [chunk {index:03d}]", prompt)
            self.assertNotRegex(prompt, r"\bChunk [0-9]+:")
            self.assertIn(source.reference.fluent_text(), summarized.content)
            self.assertIn(f"Unique ID: [chunk {index:03d}]\n\n{summary}", summarized.content)
        self.assertIs(collection.resolve_citation_ids(["[chunk 002]"], summarized)["[chunk 002]"], sources[1])

    def test_truncate_and_ignore_have_distinct_citation_effects(self):
        tokenizer = CharacterTokenizer()
        collection = ChunksSection(chunks())
        prepared = collection.prepare()
        self.assertIs(collection.truncate(prepared, 5, tokenizer=tokenizer), prepared)
        first_body = prepared.item_bodies[0]
        first_only = collection.pre_context + collection.separator + first_body
        ignored = collection.ignore(prepared, len(first_only), tokenizer=tokenizer)
        self.assertEqual(ignored.content, first_only)
        self.assertEqual(ignored.citation_ids, ("[chunk 001]",))
        self.assertEqual(list(collection.citation_map_for(ignored)), ["[chunk 001]"])
        with self.assertRaisesRegex(ValueError, "Unknown citation ID"):
            collection.resolve_citation_ids(["[chunk 002]"], ignored)

        text = SystemInputSection("Keep this exact wording for the source.")
        truncated = text.truncate(text.prepare(), 12, tokenizer=tokenizer)
        self.assertEqual(truncated.content, text.prepare().content[:12])
        self.assertEqual(len(truncated.content), 12)

    def test_context_builder_dispatches_ignore_and_truncate(self):
        collection = ChunksSection(
            chunks(),
            overflow_strategies=OverflowStrategyStack(
                [OverflowStrategy.TRUNCATE, OverflowStrategy.IGNORE]
            ),
        )
        first_only = (
            collection.pre_context + collection.separator
            + collection.prepare().item_bodies[0]
        )
        builder = PromptBuilder(seed_defaults=False)
        builder.add_section(collection)
        result = context(builder, len(first_only))
        self.assertTrue(result.sections[0].overflowed)
        self.assertEqual(result.prompt, first_only)
        self.assertEqual(result.sections[0].citation_ids, ("[chunk 001]",))

        text = SystemInputSection("Keep the complete source content when capacity permits.")
        builder = PromptBuilder(seed_defaults=False)
        builder.add_section(text)
        result = context(builder, 18)
        self.assertTrue(result.sections[0].overflowed)
        self.assertEqual(result.prompt, text.prepare().content[:18])
        self.assertEqual(result.total_tokens, 18)

    def test_malformed_missing_and_unknown_citations_are_rejected(self):
        collection = ChunksSection(chunks())
        retained = collection.prepare()
        for payload in ({"answer": "No citation"}, {"citations": "[chunk 001]"},
                        {"citations": ["chunk 001"]}, {"citations": ["[chunk 01]"]},
                        {"citations": [1]}, []):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                collection.extract_citation_ids(payload)
        with self.assertRaisesRegex(ValueError, "Unknown citation ID"):
            collection.resolve_citation_ids(["[chunk 999]"], retained)
        with self.assertRaises(json.JSONDecodeError):
            json.loads('{"answer":')
        self.assertEqual(collection.extract_citation_ids({"citations": []}), [])

    def test_provider_failure_propagates_during_summarization(self):
        class FailingProvider(ScriptedLLM):
            def complete_many(self, prompts):
                raise RuntimeError("simulated provider failure")

        collection = ChunksSection(
            chunks()[:1],
            chunk_summarizer=LLMChunkSummarizer(
                FailingProvider("unused"),
                builder=ChunkPromptBuilder(ChunkSummarizationPrompts(
                    role="Summarize the source.",
                    system_input="Preserve the evidence meaning.",
                    output_format="Return an English summary.",
                )),
                max_attempts=1,
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "simulated provider failure"):
            collection.summarize(collection.prepare(), 100)


if __name__ == "__main__":
    unittest.main()
