"""Diagnostic execution of the current SuggestionBuilder Generation pipeline.

Run from the repository root with ``python3 -m unittest``. External model
responses are scripted; all Generation orchestration remains production code.
"""

from __future__ import annotations

import json
import os
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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
)
from src.application.llm import LLMRequestBuilder
from src.application.prompt import PromptBuilder
from src.application.reference import (
    LLMBaseReferenceGenerator,
    ReferenceCache,
    ReferenceGenerationPrompts,
)
from src.application.reference.template_validator import (
    TemplateValidator,
    extract_placeholders,
)
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import GenerationChunk, Reference
from src.domain.enums import OverflowStrategy
from src.domain.overflow_strategy_stack import OverflowStrategyStack
from src.infrastructure.services.summarizers import LLMChunkSummarizer
from src.infrastructure.services.summarizers.chunk_prompt_builder import (
    ChunkPromptBuilder,
    ChunkSummarizationPrompts,
)


class CharacterTokenizer(Tokenizer):
    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        return [(ord(char), (index, index + 1)) for index, char in enumerate(text)]

    def count_tokens(self, text: str) -> int:
        return len(text)


class SuggestionReference(Reference):
    title: str
    page: int

    def __init__(self, title: str, page: int, generator: LLMBaseReferenceGenerator) -> None:
        self.title = title
        self.page = page
        self._generator = generator

    def __repr__(self) -> str:
        return f"SuggestionReference(title={self.title!r}, page={self.page!r})"

    @property
    def description(self) -> str:
        return "Source study and page for a residential energy suggestion."

    def fluent_text(self) -> str:
        return self._generator.generate(self)


class ScriptedReferenceLLM:
    template = 'There is a title "[title]" on page [page]:'

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.template


class ScriptedBatchLLM:
    summaries = (
        "Orient rooms and windows to carry daylight inward and reduce lamp use.",
        "Light shelves and clerestories spread daylight with pale interior finishes.",
        "Passive daylight design works with sensors and dimming for occupied rooms.",
        "Movable translucent partitions let daylight reach deeper rooms.",
        "Reflective ceilings and finishes redirect existing daylight without rebuilding walls.",
        "Glare, heat, privacy, and facade cost limit aggressive glazing.",
        "Appliance scheduling and thermal load control reduce household peaks, not lamp need.",
        "Seasonal lux measurements should precede daylight redesign.",
        "Modular shades regulate daylight and heat gain across seasons.",
        "Roof solar and storage offset grid purchases without changing lighting demand.",
    )

    def __init__(self) -> None:
        self.batches: list[tuple[str, ...]] = []

    def complete(self, prompt: str) -> str:
        raise AssertionError("Collection summarization should call complete_many")

    def complete_many(self, prompts: list[str]) -> list[str]:
        self.batches.append(tuple(prompts))
        if len(prompts) != 10:
            raise AssertionError(f"Expected one ten-item batch, got {len(prompts)}")
        return list(self.summaries)


class RecordingReferenceCache(ReferenceCache):
    def __init__(self, cache_dir: Path) -> None:
        super().__init__(cache_dir)
        self.events: list[tuple[str, str, str | None]] = []

    def load(self, shape_hash: str) -> str | None:
        value = super().load(shape_hash)
        self.events.append(("load", shape_hash, value))
        return value

    def save(self, shape_hash: str, template: str) -> None:
        super().save(shape_hash, template)
        self.events.append(("save", shape_hash, template))


class RecordingReferenceGenerator(LLMBaseReferenceGenerator):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.calls: list[tuple[Reference, str]] = []

    def generate(self, reference: Reference) -> str:
        result = super().generate(reference)
        self.calls.append((reference, result))
        return result


class RecordingDemandAllocator(DemandAllocator):
    def __init__(self) -> None:
        self.calls = []

    def allocate(self, demands, budget_tokens):
        result = super().allocate(demands, budget_tokens)
        self.calls.append((dict(demands), budget_tokens, dict(result)))
        return result


class RecordingRedistributionAllocator(RedistributionAllocator):
    def __init__(self) -> None:
        self.calls = []

    def redistribute(self, free_capacity_tokens, requests):
        result = super().redistribute(free_capacity_tokens, requests)
        self.calls.append((free_capacity_tokens, tuple(requests), result))
        return result


class RecordingCapacityAllocator(CapacityAllocator):
    def __init__(self, demand_allocator, redistribution_allocator) -> None:
        super().__init__(demand_allocator, redistribution_allocator)
        self.calls = []

    def allocate(self, requests, budget_tokens):
        result = super().allocate(requests, budget_tokens)
        self.calls.append((tuple(requests), budget_tokens, result))
        return result


class RecordingDispatcher(OverflowStrategyDispatcher):
    def __init__(self) -> None:
        self.attempts = []

    def apply(self, section, strategy, content, capacity_tokens, *, tokenizer):
        result = super().apply(
            section, strategy, content, capacity_tokens, tokenizer=tokenizer
        )
        self.attempts.append((section, strategy, content, capacity_tokens, result))
        return result


class SuggestionBuilder(PromptBuilder):
    def __init__(self, sections) -> None:
        super().__init__(seed_defaults=False)
        for section in sections:
            self.add_section(section)


CHUNK_DATA = (
    (
        "Orientation and daylight layout",
        "A row of private homes places living rooms along the south-facing side while service rooms occupy the dimmer edge. Designers compare seasonal sun paths before fixing window positions.",
        "Deep window reveals and an open circulation spine carry daylight from the facade toward shared spaces. Pale walls and a matte ceiling return useful light without mirror-like glare.",
        "The proposal aims to reduce daytime lamp operation by making ambient daylight available at the places residents use most. It needs a measured glare and cooling review before construction.",
    ),
    (
        "Light shelf and clerestory study",
        "In a narrow residential plot, high clerestory glazing admits sky light over neighboring walls. A light shelf sends that light above eye level toward the center of the plan.",
        "The interior finish schedule favors bright, durable plaster and light-colored doors. Local task lighting remains available for evening work and cloudy winter days.",
        "This is another architectural daylight solution, but its shelf and high-window mechanism differs from simple room orientation. Maintenance access and dust on the shelf affect performance.",
    ),
    (
        "Daylight-linked lighting controls",
        "The floor plan locates daytime activities near windows and leaves a clear path for daylight. That passive arrangement is paired with separately zoned LED fixtures.",
        "Ceiling daylight sensors dim lamps when useful daylight reaches a room, and occupancy sensors switch an empty zone off. Manual override remains available to residents.",
        "The building uses architecture and controls together. A commissioning study must avoid sensor placement that causes flicker or leaves work surfaces underlit.",
    ),
    (
        "Adaptive interior partitions",
        "A small home has a bright perimeter but dark internal rooms. Instead of cutting new exterior openings, the plan replaces selected opaque partitions with movable translucent panels.",
        "During the day, residents slide panels back so borrowed daylight crosses the circulation path. At night, the panels close to recover privacy and acoustic separation.",
        "The design can reduce daytime lighting in deeper rooms with limited electrical changes. Fire ratings, cleaning, and furniture layouts constrain where panels can move.",
    ),
    (
        "Reflective interior retrofit",
        "An existing home cannot economically change its facade orientation or window area. The proposal reshapes ceiling coves and uses light, low-gloss finishes near the existing openings.",
        "Diffusing surfaces direct available daylight toward a corridor and kitchen work area. Samples are checked for color quality and visual comfort rather than maximum reflectance alone.",
        "This reaches a similar lighting objective through interior geometry and materials. It should be evaluated against a simpler paint-only retrofit before capital work is approved.",
    ),
    (
        "Glazing risk assessment",
        "A design review challenges the assumption that more glass always saves electricity. West-facing glazing may admit strong sun when cooling equipment is already under load.",
        "Large openings can cause glare at desks, reveal private rooms to neighbors, and increase facade cost. Occupants may close blinds and turn lamps on, reversing the expected benefit.",
        "The reviewers recommend seasonal simulation and resident interviews before adopting aggressive daylight architecture. This is a limitation analysis, not a duplicate design proposal.",
    ),
    (
        "Household peak management",
        "A neighborhood study finds that water heating, cooling, and appliance use dominate evening electricity peaks. The suggested intervention does not alter room shape or window placement.",
        "Programmable loads could shift washing and water heating away from peak hours while thermostats reduce short cooling spikes. Residents retain control over essential appliances.",
        "The scheme can lower peak demand and potentially bills, but it does not directly reduce the need for artificial light. It should not be classified as the same architectural solution.",
    ),
    (
        "Seasonal daylight measurement",
        "A survey team proposes logging indoor lux levels at desks, kitchens, and corridors in representative private homes. Measurements include clear and overcast days.",
        "The team will pair light readings with lamp runtime and occupancy observations, then model winter and summer variation. A resident diary records glare and closed blinds.",
        "The result is evidence for choosing an intervention, not an intervention itself. It may show that a proposed window redesign has little benefit in a particular block.",
    ),
    (
        "Adaptive shading facade",
        "A modular external shade changes angle with the sun and keeps direct glare away from occupied rooms. The window geometry remains mostly fixed.",
        "Sensors or a simple seasonal schedule adjust the shade so diffuse daylight still reaches the interior. The design also limits solar heat gain in summer.",
        "Its goal is compatible with daylight architecture, but facade control is the main mechanism. Wind loading, actuator upkeep, and winter sun access require review.",
    ),
    (
        "Roof solar and storage",
        "A roof survey finds space for a small photovoltaic array and battery in several detached homes. The scheme offsets purchased electricity during sunny hours.",
        "A controller shifts flexible loads toward solar production and stores some output for the evening. The economics depend on roof condition and equipment life.",
        "This is relevant to household electricity use, yet it does not make rooms brighter or reduce the need for lamps. It is a competing energy investment, not a daylight design.",
    ),
)

ROLE = (
    "You are an analyst with several years of experience at Tavanir, Iran's "
    "specialized parent company for electricity generation, transmission, and "
    "distribution under the Ministry of Energy. You understand its terminology, "
    "operational practices, constraints, and organizational context."
)
SYSTEM_INPUT = (
    "Read each suggestion's actual content. Identify (1) exactly the same "
    "solution and (2) similar or closely related solutions. Distinguish "
    "identical mechanisms from related ideas; cite each source ID. Exclude "
    "unrelated household energy ideas from residential lighting groups. "
    "Explain borderline cases and evidence gaps. Treat the result as "
    "decision support rather than an organizational decision."
)
OUTPUT_FORMAT = (
    "Suggestions introducing the same solution:\n\n---\n\n"
    "1. First suggestion (source ID)\n\n---\n\n"
    "2. Second suggestion (source ID)\n\n---\n\n"
    "3. Third suggestion (source ID)\n\n---\n\n"
    "Suggestions introducing similar solutions:\n\n---\n\n"
    "1. First similar suggestion (source ID)\n\n---\n\n"
    "2. Second similar suggestion (source ID)\n\n---\n\n"
    "3. Third similar suggestion (source ID)"
)


def fenced(value: str) -> str:
    return f"```text\n{value}\n```\n"


class FinalSuggestionBuilderReportTest(unittest.TestCase):
    def test_pipeline_and_write_report(self) -> None:
        tokenizer = CharacterTokenizer()
        checks: list[tuple[str, bool, str]] = []
        errors: list[str] = []
        report_path = Path(os.environ.get(
            "CONTEXT_BUILDER_FINAL_REPORT_PATH",
            "/tmp/ContextBuilder_Final_SuggestionBuilder_Test_Report.md",
        ))

        def check(name: str, condition: bool, detail: str = "") -> None:
            checks.append((name, bool(condition), detail))

        with TemporaryDirectory(prefix="suggestion-builder-report-") as temp_dir:
            reference_llm = ScriptedReferenceLLM()
            batch_llm = ScriptedBatchLLM()
            cache = RecordingReferenceCache(Path(temp_dir) / "references")
            validator = TemplateValidator()
            reference_context = ContextBuilder(
                tokenizer=tokenizer,
                capacity_allocator=CapacityAllocator(DemandAllocator(), RedistributionAllocator()),
                dispatcher=OverflowStrategyDispatcher(),
            )
            reference_generator = RecordingReferenceGenerator(
                reference_llm,
                validator=validator,
                context_builder=reference_context,
                cache=cache,
                max_tokens=2048,
                prompts=ReferenceGenerationPrompts(
                    role="Write a concise English source reference template.",
                    system_input="Use every declared property exactly as a [name] placeholder; do not invent properties or include actual values.",
                    output_format="Return only one English reference template sentence.",
                    error_heading="The previous template was invalid:",
                ),
            )
            chunks = [
                GenerationChunk(
                    chunk_id=f"SUG-{index:03d}",
                    content="\n\n".join(paragraphs),
                    reference=SuggestionReference(title, 10 + index * 2, reference_generator),
                )
                for index, (title, *paragraphs) in enumerate(CHUNK_DATA, 1)
            ]
            batch_summarizer = LLMChunkSummarizer(
                batch_llm,
                builder=ChunkPromptBuilder(ChunkSummarizationPrompts(
                    role="Summarize one English source faithfully.",
                    system_input="Summarize only this source. Keep its main mechanism, limitation, and citation if present.",
                    output_format="Return only a short English summary.",
                )),
                max_attempts=1,
                batch_size=10,
            )
            sections = [
                RoleSection(ROLE, importance=0.7, demand=0.25,
                            overflow_strategies=OverflowStrategyStack([OverflowStrategy.TRUNCATE])),
                ChunksSection(chunks, importance=0.9, demand=0.50,
                              chunk_summarizer=batch_summarizer,
                              overflow_strategies=OverflowStrategyStack([
                                  OverflowStrategy.SUMMARIZE,
                                  OverflowStrategy.TRUNCATE,
                                  OverflowStrategy.IGNORE,
                              ])),
                SystemInputSection(SYSTEM_INPUT, importance=0.3, demand=0.10,
                                   overflow_strategies=OverflowStrategyStack([OverflowStrategy.TRUNCATE])),
                OutputFormatSection(OUTPUT_FORMAT, importance=0.8, demand=0.15,
                                    overflow_strategies=OverflowStrategyStack([OverflowStrategy.TRUNCATE])),
            ]
            builder = SuggestionBuilder(sections)
            source_copy = [(c.chunk_id, c.content, c.reference) for c in chunks]
            body_outputs = {section.section_type: section.body() for section in sections}
            prepared = {section.section_type: section.prepare() for section in sections}
            demand = RecordingDemandAllocator()
            redistribution = RecordingRedistributionAllocator()
            allocator = RecordingCapacityAllocator(demand, redistribution)
            dispatcher = RecordingDispatcher()
            context_builder = ContextBuilder(
                tokenizer=tokenizer,
                capacity_allocator=allocator,
                dispatcher=dispatcher,
            )
            budget = 2800
            context_result = None
            request = None
            try:
                context_result = context_builder.build(builder, max_tokens=budget)
                request = LLMRequestBuilder().build(
                    context_result, model="generation-test-model",
                    temperature=0.2, max_tokens=256,
                )
            except Exception as error:
                errors.append(f"{type(error).__name__}: {error}")
            cache_events = tuple(cache.events)

            lines = [
                "# ContextBuilder Final SuggestionBuilder Test Report", "",
                "## 1. Test Objective", "",
                "Execute the current Generation pipeline from four ordered sections through the actual LLMRequestBuilder. External LLM responses are scripted; no live provider inference occurs. The offset-aware character tokenizer counts one Unicode character as one test token. These counts are exact for this run and are not Gemma model token counts.", "",
                "## 2. Test Configuration", "",
                f"Budget: {budget} character tokens. Section separator: {builder.SECTION_SEPARATOR!r}. Reference prompt budget: 2048 character tokens. Request output max_tokens: 256 (separate from context budget).", "",
                "Demand 0.25/0.50/0.10/0.15 gives CHUNKS the largest initial share. ROLE and OUTPUT-FORMAT have shares above their sizes and return capacity. CHUNKS has high redistribution importance (0.9); SYSTEM-INPUT has lower importance (0.3), so it may require truncation. The explicit CHUNKS stack is SUMMARIZE, TRUNCATE, IGNORE, in that order.", "",
                "## 3. Section Construction", "",
            ]
            for section in sections:
                lines.append(f"### {section.section_type} — {type(section).__name__}\n")
                lines.append(f"Importance: {section.importance}; demand: {section.demand}; strategies: {[s.name for s in section.overflow_strategies.strategies]}.\n")
                lines.append("Exact body():\n")
                lines.append(fenced(body_outputs[section.section_type]))
            lines.append("Exactly 10 source chunks, with source IDs and three paragraphs each:\n")
            for item in chunks:
                lines.append(f"### {item.chunk_id} — {item.reference.title}, page {item.reference.page}\n")
                lines.append(fenced(item.content))

            lines.extend(["## 4. Generated References", "",
                          f"Reference generator: {type(reference_generator).__name__} inheriting production LLMBaseReferenceGenerator. Calls to generate(): {len(reference_generator.calls)}; actual reference LLM complete() calls: {len(reference_llm.prompts)}; cache events during execution: {len(cache_events)}. ChunksSection does not expose its inherited reference_generator constructor parameter; the structured Reference's fluent_text() delegates through an injected generator.\n"])
            for index, item in enumerate(chunks):
                details = item.reference.details
                first_load = cache_events[0 if index == 0 else index + 1] if index + 1 < len(cache_events) else None
                rendered = reference_generator.calls[index][1] if index < len(reference_generator.calls) else "NOT CAPTURED"
                lines.append(f"### {item.chunk_id}\n")
                lines.append(f"REFERENCE OBJECT: {item.reference!r}; class: {type(item.reference).__name__}; description: {item.reference.description}\n")
                lines.append(f"REFERENCE DETAILS: {details.properties!r}; shape hash: {details.hash()}; declared properties: title -> str, page -> int.\n")
                lines.append(f"CACHE RESULT: first observed load {first_load!r}; persisted template {ReferenceCache.load(cache, details.hash())!r}.\n")
                lines.append(f"LLM OUTPUT / generated template: {reference_llm.template!r}; placeholders: {extract_placeholders(reference_llm.template)!r}; validation: {validator.validate(reference_llm.template, details)!r}.\n")
                lines.append(f"RENDERED REFERENCE: {rendered!r}.\n")
            lines.append("Exact reference LLM input (the one cache miss):\n")
            lines.append(fenced(reference_llm.prompts[0] if reference_llm.prompts else "NO LLM CALL"))
            lines.extend(["## 5. Section Preparation", ""])
            for section in sections:
                state = prepared[section.section_type]
                lines.append(f"### {section.section_type}\n")
                lines.append(f"pre_context={section.pre_context!r}; post_context={section.post_context!r}; prepared tokens={len(state.content)}; item count={len(state.items or ())}.\n")
                lines.append("BEFORE (body):\n" + fenced(body_outputs[section.section_type]))
                lines.append("AFTER (prepared, including reference injection):\n" + fenced(state.content))
                if state.item_inputs:
                    for index, item_input in enumerate(state.item_inputs, 1):
                        lines.append(f"Independent prepared item input {index}, {len(item_input)} tokens:\n" + fenced(item_input))

            lines.extend(["## 6. Token Calculation", ""])
            reservation = (len(sections) - 1) * len(builder.SECTION_SEPARATOR)
            usable = budget - reservation
            lines.append(f"Total budget {budget}; separator reservation ({len(sections)} - 1) × {len(builder.SECTION_SEPARATOR)} = {reservation}; usable budget {budget} - {reservation} = {usable}.\n")
            lines.append("| Section | Importance | Demand | Prepared tokens |\n|---|---:|---:|---:|\n")
            for section in sections:
                lines.append(f"| {section.section_type} | {section.importance} | {section.demand} | {len(prepared[section.section_type].content)} |")
            lines.append("")
            if allocator.calls:
                requests, observed_usable, allocation = allocator.calls[0]
                initial = demand.calls[0][2]
                free, expansion, redistributed = redistribution.calls[0]
                final = dict(allocation.capacities)
                lines.extend(["## 7. Initial Allocation", "",
                              f"Production DemandAllocator output: {initial!r}; sum={sum(initial.values())}; input budget={observed_usable}.\n",
                              "| Section | Initial share | Needed | Initial surplus (+) / deficit (-) |\n|---|---:|---:|---:|\n"])
                for section in sections:
                    name = section.section_type
                    need = len(prepared[name].content)
                    lines.append(f"| {name} | {initial[name]} | {need} | {initial[name] - need} |")
                lines.extend(["", "## 8. Budget Re-distribution", "",
                              f"Free capacity before redistribution: {free} = sum(max(initial share - needed, 0)).\n",
                              "| Section | Expansion request | Weight | Award | Remaining deficit | Final capacity |\n|---|---:|---:|---:|---:|---:|\n"])
                expansion_by_name = {}
                for capacity_request, expansion_request, awarded in zip(
                    (r for r in requests if r.needed_tokens >= initial[r.key]),
                    expansion,
                    redistributed.allocations,
                ):
                    expansion_by_name[capacity_request.key] = (expansion_request, awarded)
                for section in sections:
                    name = section.section_type
                    pair = expansion_by_name.get(name)
                    asked = pair[0].requested_tokens if pair else 0
                    weight = pair[0].weight if pair else 0
                    award = pair[1].allocated_tokens if pair else 0
                    lines.append(f"| {name} | {asked} | {weight} | {award} | {asked - award} | {final[name]} |")
                lines.append(f"\nAward total {sum(r.allocated_tokens for r in redistributed.allocations)}; unused free capacity {redistributed.unused_capacity}; award + unused = {free}. Final capacity sum {sum(final.values())} ≤ usable {usable}.\n")
                if len(redistributed.allocations) == 2:
                    total_weight = sum(item.weight for item in expansion)
                    lines.append(
                        f"Weighted redistribution: floor({free} × {expansion[0].weight} / {total_weight}) = {redistributed.allocations[0].allocated_tokens} to CHUNKS; "
                        f"floor({free} × {expansion[1].weight} / {total_weight}) = {redistributed.allocations[1].allocated_tokens} to SYSTEM-INPUT.\n"
                    )
            else:
                initial, final = {}, {}
                lines.extend(["## 7. Initial Allocation", "", "No allocation completed.\n",
                              "## 8. Budget Re-distribution", "", "No redistribution completed.\n"])

            lines.extend(["## 9. Strategy Dispatch", ""])
            for index, (section, strategy, before, capacity, after) in enumerate(dispatcher.attempts, 1):
                before_count = len(before.content)
                after_count = None if after is None else len(after.content)
                selected = after is not None and after_count <= capacity
                before_ids = [getattr(item, "chunk_id", None) for item in before.items or ()]
                after_ids = [getattr(item, "chunk_id", None) for item in after.items or ()] if after else []
                lines.append(f"### Attempt {index}: {section.section_type} / {strategy.name}\n")
                lines.append(f"Section class: {type(section).__name__}; configured order: {[s.name for s in section.overflow_strategies.strategies]}; input tokens: {before_count}; capacity: {capacity}; remaining capacity before: {capacity-before_count}; output tokens: {after_count}; token delta: {None if after_count is None else before_count-after_count}; selected: {selected}; validation: {'fits' if selected else 'does not fit or unavailable'}; fallback: {'none' if selected else 'next configured strategy or safety fallback'}.\n")
                lines.append(f"Source IDs before: {before_ids!r}; after: {after_ids!r}; items removed: {[x for x in before_ids if x not in after_ids]!r}; ordering preserved: {after_ids == before_ids[:len(after_ids)]}; source items changed: {[(c.chunk_id, c.content, c.reference) for c in chunks] != source_copy}.\n")
                if before.item_inputs:
                    for item_index, item_input in enumerate(before.item_inputs, 1):
                        lines.append(f"Actual per-item input {item_index}:\n" + fenced(item_input))
                lines.append("INPUT:\n" + fenced(before.content))
                lines.append("OUTPUT:\n" + fenced(after.content if after else "NO RESULT"))
            lines.extend(["## 10. Chunk Summarization", "",
                          f"Source item count: {len(chunks)}; complete_many batch count: {len(batch_llm.batches)}; prompts in first batch: {len(batch_llm.batches[0]) if batch_llm.batches else 0}.\n"])
            chunk_attempt = next((a for a in dispatcher.attempts if a[0].section_type == "CHUNKS" and a[1] is OverflowStrategy.SUMMARIZE), None)
            if chunk_attempt and chunk_attempt[4]:
                before, after = chunk_attempt[2], chunk_attempt[4]
                lines.append(f"Output item count: {len(after.items or ())}. Each prepared item is passed separately to ChunkPromptBuilder; production LLMChunkSummarizer calls complete_many once.\n")
                for index, (source, fitted) in enumerate(zip(before.items or (), after.items or ())):
                    original_input = before.item_inputs[index]
                    processed_input = after.item_inputs[index]
                    saved = len(original_input) - len(processed_input)
                    lines.append(f"### {source.chunk_id}\n")
                    lines.append(f"Reference before: {source.reference!r}; reference after: {fitted.reference!r}; ID after: {fitted.chunk_id}. Input tokens: {len(original_input)}; output tokens: {len(processed_input)}; saved: {saved}; reduction: {saved/len(original_input)*100:.2f}%.\n")
                    lines.append("SUMMARIZER INPUT:\n" + fenced(original_input))
                    lines.append("COMPLETE_MANY PROMPT:\n" + fenced(batch_llm.batches[0][index] if batch_llm.batches else "NOT CAPTURED"))
                    lines.append("SUMMARIZED TEXT:\n" + fenced(fitted.content))
                    lines.append("AFTER (per-item prepared text):\n" + fenced(processed_input))
                input_total = sum(map(len, before.item_inputs))
                output_total = sum(map(len, after.item_inputs))
                lines.append(f"Total per-item input tokens {input_total}; output tokens {output_total}; saved {input_total-output_total}; reduction {(input_total-output_total)/input_total*100:.2f}%. These sums repeat per-item framing and therefore differ from aggregate CHUNKS section tokens.\n")
            else:
                lines.append("No successful CHUNKS summarization result.\n")

            lines.extend(["## 11. Final Section Results", ""])
            if context_result:
                for output in context_result.sections:
                    original = prepared[output.section_type]
                    lines.append(f"### {output.section_type}\n")
                    lines.append(f"Original tokens {output.requested_tokens}; final tokens {output.fitted_tokens}; capacity {output.capacity_tokens}; overflowed {output.overflowed}; retained IDs {[getattr(i, 'chunk_id', None) for i in output.items or ()]!r}; retained references {[getattr(i, 'reference', None) for i in output.items or ()]!r}.\n")
                    lines.append("BEFORE:\n" + fenced(original.content))
                    lines.append("AFTER:\n" + fenced(output.content))
                lines.extend(["## 12. PromptBuilder Output", "",
                              "Exact output of production PromptBuilder.assemble, as captured in ContextBuilderResult.prompt:\n",
                              fenced(context_result.prompt)])
                lines.extend(["## 13. LLMRequestBuilder", "",
                              f"Actual input type: {type(context_result).__name__}; section order: {[o.section_type for o in context_result.sections]!r}; separator: {context_result.section_separator!r}.\n",
                              "Production builder filters empty outputs and HISTORY, joins remaining content into one system message. This scenario has no HISTORY and no USER-INPUT; it produces one system message and zero user messages.\n"])
                lines.extend(["## 14. Final LLM Request", "",
                              f"Actual type: {type(request).__name__}. Actual LLMRequestBuilder.build return value serialized with json.dumps for display:\n",
                              "```json\n" + json.dumps(request, ensure_ascii=False, indent=2) + "\n```\n"])
                original_tokens = sum(len(state.content) for state in prepared.values())
                final_section_tokens = sum(output.fitted_tokens for output in context_result.sections)
                lines.extend(["## 15. Token Accounting Summary", "",
                              f"Original section tokens: {original_tokens}; final section tokens: {final_section_tokens}; section tokens saved: {original_tokens-final_section_tokens}; surviving separator tokens: {(sum(bool(o.content) for o in context_result.sections)-1)*len(builder.SECTION_SEPARATOR)}; final prompt tokens: {context_result.total_tokens}; budget: {budget}; remaining: {budget-context_result.total_tokens}.\n"])
                chunk_output = next(o for o in context_result.sections if o.section_type == "CHUNKS")
                lines.extend(["## 16. Reference Preservation Summary", "",
                              f"Original source IDs: {[c.chunk_id for c in chunks]!r}; final item IDs: {[c.chunk_id for c in chunk_output.items or ()]!r}.\n",
                              f"Structured references on final item objects: {[c.reference for c in chunk_output.items or ()]!r}.\n",
                              f"Rendered citation strings present in prepared CHUNKS: {all(text in prepared['CHUNKS'].content for _, text in reference_generator.calls[:10])}; present in final CHUNKS prompt text: {all(text in chunk_output.content for _, text in reference_generator.calls[:10])}.\n"])
            else:
                original_tokens = final_section_tokens = 0
                lines.extend(["## 11. Final Section Results", "", "Unavailable after execution error.\n",
                              "## 12. PromptBuilder Output", "", "Unavailable.\n",
                              "## 13. LLMRequestBuilder", "", "Not reached.\n",
                              "## 14. Final LLM Request", "", "Not produced.\n",
                              "## 15. Token Accounting Summary", "", "Not available.\n",
                              "## 16. Reference Preservation Summary", "", "Not available.\n"])

            expected_order = ["ROLE", "CHUNKS", "SYSTEM-INPUT", "OUTPUT-FORMAT"]
            check("four sections in exact order", [s.section_type for s in builder.sections] == expected_order)
            check("ten unique source IDs", len(chunks) == len({c.chunk_id for c in chunks}) == 10)
            check("three paragraphs per chunk", all(len(c.content.split("\n\n")) == 3 for c in chunks))
            check("English main section bodies", all(body_outputs[s.section_type].isascii() for s in sections))
            check("structured references and details", all(isinstance(c.reference, Reference) and c.reference.details.properties == (("title", "str"), ("page", "int")) for c in chunks))
            check("reference generator invoked", len(reference_generator.calls) >= 10)
            check("one template LLM call from shape cache", len(reference_llm.prompts) == 1)
            check("valid generated template", all(validator.validate(reference_llm.template, c.reference.details).valid for c in chunks))
            check("rendered references contain values", all(c.title in text and str(c.page) in text for c, text in reference_generator.calls))
            check("allocation and separator accounting", bool(initial) and sum(initial.values()) == usable and sum(final.values()) <= usable)
            check("redistribution accounting", bool(redistribution.calls) and sum(r.allocated_tokens for r in redistribution.calls[0][2].allocations) + redistribution.calls[0][2].unused_capacity == redistribution.calls[0][0])
            check("one independent ten-item batch", len(batch_llm.batches) == 1 and len(batch_llm.batches[0]) == 10)
            check("summarizer input isolation", bool(batch_llm.batches) and all(CHUNK_DATA[i][1][:35] in batch_llm.batches[0][i] and all(CHUNK_DATA[j][1][:35] not in batch_llm.batches[0][i] for j in range(10) if j != i) for i in range(10)))
            check("collection summarize executed", chunk_attempt is not None)
            check(
                "prepared chunks and summarizer IO omit report labels",
                re.search(r"\bChunk [0-9]+:", prepared["CHUNKS"].content) is None
                and all(
                    re.search(r"\bChunk [0-9]+:", text) is None
                    for batch in batch_llm.batches for text in batch
                )
                and all(re.search(r"\bChunk [0-9]+:", text) is None for text in batch_llm.summaries),
            )
            check("source items unchanged", [(c.chunk_id, c.content, c.reference) for c in chunks] == source_copy)
            if context_result:
                chunk_output = context_result.sections[1]
                check("section output order", [o.section_type for o in context_result.sections] == expected_order)
                check("no duplicate or unexpected section", len(context_result.sections) == len({o.section_type for o in context_result.sections}) == 4 and set(o.section_type for o in context_result.sections) == set(expected_order))
                check("role remains intact", context_result.sections[0].content == prepared["ROLE"].content)
                check("output format remains intact", context_result.sections[3].content == prepared["OUTPUT-FORMAT"].content)
                check("system input retains grouping and citation rules", all(term in context_result.sections[2].content for term in ("exactly the same", "similar or closely related", "cite each source ID", "Exclude unrelated")))
                check("all scripted summaries mapped one to one", [c.content for c in chunk_output.items or ()] == list(batch_llm.summaries))
                check("all chunk IDs and order survive", [c.chunk_id for c in chunk_output.items or ()] == [c.chunk_id for c in chunks])
                check("reference objects survive on items", [c.reference for c in chunk_output.items or ()] == [c.reference for c in chunks])
                check("rendered references survive in final prompt", all(text in chunk_output.content for _, text in reference_generator.calls[:10]), "Explicit source-traceability requirement")
                check("section capacities respected", all(o.fitted_tokens <= o.capacity_tokens for o in context_result.sections))
                check("prompt budget respected", context_result.total_tokens == len(context_result.prompt) <= budget)
                check("final prompt omits report labels", re.search(r"\bChunk [0-9]+:", context_result.prompt) is None)
                check("separator accounting", context_result.total_tokens == sum(o.fitted_tokens for o in context_result.sections if o.content) + (sum(bool(o.content) for o in context_result.sections)-1)*len(builder.SECTION_SEPARATOR))
                check("prompt assembled once in order", context_result.prompt == builder.assemble({o.section_type:o.content for o in context_result.sections}))
                check("request builder receives result", request is not None and isinstance(request, dict))
                check("nonempty ordered actual messages", request is not None and request["messages"] == [{"role":"system", "content":context_result.prompt}])
                check("request model settings", request is not None and request["model"] == "generation-test-model" and request["temperature"] == 0.2 and request["max_tokens"] == 256)
            failed = [name for name, ok, _ in checks if not ok]
            counts = {strategy: sum(attempt[1] is strategy for attempt in dispatcher.attempts) for strategy in OverflowStrategy}
            lines.extend(["## 17. Assertions", "",
                          "| Assertion | Result | Detail |\n|---|---|---|\n"])
            for name, ok, detail in checks:
                lines.append(f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
            lines.extend(["", "## 18. Errors and Failures", ""])
            if failed:
                for name in failed:
                    lines.append(f"- FAIL: {name}")
                if "rendered references survive in final prompt" in failed:
                    lines.append(
                        "Component: src/application/context/sections/referenced_collection_section.py "
                        "summarize() lines 141-159. The processed item copies retain their "
                        "Reference objects, but _summary_bodies() returns only the raw LLM "
                        "summaries. The scripted responses omitted citations, so the final "
                        "CHUNKS prompt omitted every rendered reference despite the prepared "
                        "inputs containing them. This demonstrates that source traceability "
                        "depends on the LLM repeating citations and is not enforced by the "
                        "current collection rendering path."
                    )
            if errors:
                for error in errors:
                    lines.append(f"- Execution error: {error}")
            if not failed and not errors:
                lines.append("No failed assertions or execution errors.")
            lines.extend(["", "EXPECTED / CONFIGURATION-DRIVEN BEHAVIOR: A selected SUMMARIZE or TRUNCATE operation is expected under this budget. Collection TRUNCATE is a no-op when attempted; IGNORE removes whole trailing items if reached. Missing references in final CHUNKS text are classified as a defect only because source traceability was an explicit requirement.", "",
                          "## 19. Final Result", "",
                          f"**{'FAIL' if failed or errors else 'PASS'}** — {len(checks)-len(failed)} assertions passed; {len(failed)} failed; {len(errors)} execution errors. No production code was changed.\n"])
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print("\n".join((
                f"Test Result: {'FAIL' if failed or errors else 'PASS'}",
                f"Total Sections: {len(sections)}",
                f"Total Chunks: {len(chunks)}",
                f"Total Reference Generations: {len(reference_generator.calls)} generator invocations; {len(reference_llm.prompts)} template LLM call",
                f"Total LLM Calls: {len(reference_llm.prompts)+len(batch_llm.batches)} boundary calls",
                f"Total Strategy Attempts: {len(dispatcher.attempts)}",
                f"Summarize Operations: {counts[OverflowStrategy.SUMMARIZE]}",
                f"Truncate Operations: {counts[OverflowStrategy.TRUNCATE]}",
                f"Ignore Operations: {counts[OverflowStrategy.IGNORE]}",
                f"Original Tokens: {original_tokens}",
                f"Final Tokens: {final_section_tokens}",
                f"Tokens Saved: {original_tokens-final_section_tokens}",
                f"Final Prompt Tokens: {context_result.total_tokens if context_result else 'unavailable'}",
                f"Final Budget: {budget}",
                f"Remaining Budget: {budget-context_result.total_tokens if context_result else 'unavailable'}",
                f"Assertions Passed: {len(checks)-len(failed)}",
                f"Assertions Failed: {len(failed)}",
                f"Execution Errors: {len(errors)}",
                f"Report Path: {report_path}",
            )))
            self.assertFalse(failed or errors, f"See {report_path}: failures={failed}; errors={errors}")


if __name__ == "__main__":
    unittest.main()
