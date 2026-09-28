"""Focused schema contract test for LLMBaseReferenceGenerator."""

from __future__ import annotations

import os
import re
import unittest
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
from typing import ClassVar, get_type_hints

from src.application.context import ContextBuilder, OverflowStrategyDispatcher
from src.application.exceptions import LLMAPIError
from src.application.context.allocation import (
    CapacityAllocator,
    DemandAllocator,
    RedistributionAllocator,
)
from src.application.interfaces.i_llm_client import ILLMClient
from src.application.reference import LLMBaseReferenceGenerator, ReferenceCache
from src.application.reference.template_filler import substitute_placeholders
from src.application.reference.template_validator import TemplateValidator
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import Reference


class MyReference(Reference):
    """Literal annotated subclass from the request, plus required instance behavior."""

    title: str
    page: int

    def __init__(self, title: str, page: int) -> None:
        self.title = title
        self.page = page

    @property
    def description(self) -> str:
        return "A named source and its page."


@dataclass
class DataclassMyReference(Reference):
    title: str
    page: int

    @property
    def description(self) -> str:
        return "A named source and its page."


@dataclass
class DocumentReference(Reference):
    document_name: str
    page: int
    section: str

    @property
    def description(self) -> str:
        return "A document section and page."


@dataclass
class RegulationReference(Reference):
    title: str
    article: str
    page: int

    @property
    def description(self) -> str:
        return "A regulation article and page."


class CharacterTokenizer(Tokenizer):
    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        return [(ord(character), (index, index + 1)) for index, character in enumerate(text)]

    def count_tokens(self, text: str) -> int:
        return len(text)


class ScriptedLLM(ILLMClient):
    """Records exact prompts and supplies one raw response per call."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []
        self.outputs: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        self.outputs.append(self.response)
        return self.response


_PLACEHOLDER = re.compile(r"\[([A-Za-z_][A-Za-z0-9_]*)\]")


def _placeholder_analysis(template: str, names: tuple[str, ...]) -> dict:
    detected = _PLACEHOLDER.findall(template)
    counts = Counter(detected)
    expected = set(names)
    missing = sorted(expected - counts.keys())
    unknown = sorted(counts.keys() - expected)
    duplicates = {name: count for name, count in counts.items() if count > 1}
    outside = _PLACEHOLDER.sub("", template)
    template_valid = bool(detected) and bool(outside.strip()) and "[" not in outside and "]" not in outside
    return {
        "detected": detected,
        "missing": missing,
        "unknown": unknown,
        "duplicates": duplicates,
        "schema_compliant": not missing and not unknown and not duplicates,
        "template_valid": template_valid,
    }


def _semantic_valid(template: str, names: tuple[str, ...]) -> bool:
    """Check field roles, allowing title/source wording variants."""
    patterns = {
        "title": r"(?:title|from|regulation|named|called)\W+(?:\")?\[title\]",
        "document_name": r"document\W+\[document_name\]",
        "page": r"page\W+\[page\]",
        "section": r"section\W+\[section\]",
        "article": r"article\W+\[article\]",
    }
    return all(re.search(patterns[name], template, re.IGNORECASE) for name in names)


def _context_builder() -> ContextBuilder:
    return ContextBuilder(
        tokenizer=CharacterTokenizer(),
        capacity_allocator=CapacityAllocator(
            DemandAllocator(), RedistributionAllocator()
        ),
        dispatcher=OverflowStrategyDispatcher(),
    )


class LLMReferenceGeneratorSchemaTest(unittest.TestCase):
    def test_inherited_annotation_schema_excludes_unavailable_values(self) -> None:
        class ParentReference(Reference):
            title: str
            category: ClassVar[str] = "source"

            @property
            def description(self) -> str:
                return "An annotated source."

        class ChildReference(ParentReference):
            page: int
            note: str | None

            def __init__(self) -> None:
                self.title = "Relay Maintenance Log"
                self.page = 42
                self.note = None

        reference = ChildReference()
        self.assertEqual(
            reference.details.properties,
            (("title", "str"), ("page", "int")),
        )
        self.assertEqual(
            reference.details.hash(),
            DataclassMyReference("Relay Maintenance Log", 42).details.hash(),
        )

    def test_generated_templates_match_reference_schemas(self) -> None:
        validator = TemplateValidator()
        cases = (
            (
                "MyReference with dataclass storage",
                DataclassMyReference("Relay Maintenance Log", 42),
                'There is a title "[title]" on page [page]:',
                True,
            ),
            (
                "MyReference alternate wording with dataclass storage",
                DataclassMyReference("Relay Maintenance Log", 42),
                'Page [page] contains information from "[title]":',
                True,
            ),
            (
                "DocumentReference",
                DocumentReference("Outage Dispatch Review", 12, "Crew Assignment"),
                "Document [document_name], section [section], page [page]:",
                True,
            ),
            (
                "RegulationReference",
                RegulationReference("Grid Reliability Code", "Article 7", 8),
                'Regulation "[title]", article [article], page [page]:',
                True,
            ),
            (
                "Unknown placeholders",
                DataclassMyReference("Relay Maintenance Log", 42),
                "The reference is about [name] on page [number].",
                False,
            ),
            (
                "Missing article",
                RegulationReference("Grid Reliability Code", "Article 7", 8),
                'There is a title "[title]" on page [page].',
                False,
            ),
            (
                "Non-template response",
                DataclassMyReference("Relay Maintenance Log", 42),
                "MyReference contains a title and page.",
                False,
            ),
        )
        lines = [
            "LLMReferenceGenerator schema verification",
            "Implementation: LLMBaseReferenceGenerator.generate(reference instance)",
            "LLM boundary: scripted deterministic responses; no live provider was called.",
            "Prompt configuration: production defaults.",
            "Context construction: real ContextBuilder, allocators, and dispatcher.",
            "Tokenizer seam: deterministic one-character-per-token tokenizer.",
            "Template validity and semantic checks below are independent of TemplateValidator.",
            "",
        ]
        failures: list[str] = []

        with TemporaryDirectory(prefix="reference-schema-test-") as root:
            plain = MyReference("Relay Maintenance Log", 42)
            plain_client = ScriptedLLM('There is a title "[title]" on page [page]:')
            plain_cache = ReferenceCache(Path(root) / "plain")
            plain_generator = LLMBaseReferenceGenerator(
                plain_client,
                validator=validator,
                context_builder=_context_builder(),
                cache=plain_cache,
                max_tokens=4096,
            )
            plain_result = plain_generator.generate(plain)
            plain_types = get_type_hints(MyReference)
            plain_names = tuple(plain_types)
            plain_schema = tuple((name, plain_types[name].__name__) for name in plain_names)
            plain_template = plain_client.outputs[-1].strip() if plain_client.outputs else ""
            plain_analysis = _placeholder_analysis(plain_template, plain_names)
            plain_semantic = _semantic_valid(plain_template, plain_names)
            plain_schema_pass = (
                plain.details.properties == plain_schema
                and plain_analysis["schema_compliant"]
            )
            plain_validator_result = (
                validator.validate(plain_template, plain.details)
                if plain_client.outputs else None
            )
            plain_rendered = (
                substitute_placeholders(plain_template, plain)
                if plain_schema_pass and plain_analysis["template_valid"] else None
            )
            plain_render_pass = (
                plain_rendered is not None
                and plain_rendered == plain_result
                and all(plain_rendered.count(str(getattr(plain, name))) == 1
                        for name in plain_names)
            )
            plain_pass = (
                plain_schema_pass and plain_analysis["template_valid"]
                and plain_semantic and plain_render_pass
                and plain_validator_result is not None
                and plain_validator_result.valid
                and len(plain_client.prompts) == 1
                and plain_cache.load(plain.details.hash()) == plain_template
            )
            lines.extend((
                "=" * 72,
                "PRIMARY CASE: MyReference exactly as an annotated subclass",
                "=" * 72,
                "REFERENCE SCHEMA",
                f"Class: {type(plain).__name__}",
                f"Declared fields and types: {plain_schema}",
                f"Actual ReferenceDetails: {plain.details.properties}",
                f"Expected placeholders: {[f'[{name}]' for name in plain_names]}",
                "EXACT LLM INPUT",
                plain_client.prompts[0] if plain_client.prompts else "none; generator did not call the LLM",
                "EXACT RAW LLM OUTPUT",
                plain_client.outputs[0] if plain_client.outputs else "none; generator did not call the LLM",
                "VALIDATION",
                f"Detected placeholders: {[f'[{name}]' for name in plain_analysis['detected']]}",
                f"Expected placeholders: {[f'[{name}]' for name in plain_names]}",
                f"Missing placeholders: {plain_analysis['missing']}",
                f"Unknown placeholders: {plain_analysis['unknown']}",
                f"Duplicate placeholders: {plain_analysis['duplicates']}",
                f"Schema compliance: {'PASS' if plain_schema_pass else 'FAIL'}",
                f"Template validity: {'PASS' if plain_analysis['template_valid'] else 'FAIL'}",
                f"Rendering test: {'PASS' if plain_render_pass else 'FAIL'}",
                f"Semantic validity: {'PASS' if plain_semantic else 'FAIL'}",
                f"Actual TemplateValidator.valid: {plain_validator_result.valid if plain_validator_result else 'not invoked'}",
                "RENDER TEST",
                f"Rendered result: {plain_rendered if plain_rendered is not None else 'not attempted; schema unavailable'}",
                f"Generator result: {plain_result!r}",
                f"Case result: {'PASS' if plain_pass else 'FAIL'}",
                "",
            ))
            if not plain_pass:
                failures.append(
                    "Literal MyReference: annotations exist, but ReferenceDetails is empty "
                    "for a non-dataclass instance, so generate() returned empty text without an LLM call"
                    if not plain.details.properties else
                    "Literal MyReference: generated template failed schema, semantic, render, or cache checks"
                )

            for index, (label, reference, raw_output, should_be_valid) in enumerate(cases, 1):
                field_types = get_type_hints(type(reference))
                names = tuple(field_types)
                expected_types = tuple((name, field_types[name].__name__) for name in names)
                actual_details = reference.details.properties
                analysis = _placeholder_analysis(raw_output.strip(), names)
                semantic_valid = _semantic_valid(raw_output.strip(), names)
                provider = ScriptedLLM(raw_output)
                cache = ReferenceCache(Path(root) / str(index))
                generator = LLMBaseReferenceGenerator(
                    provider,
                    validator=validator,
                    context_builder=_context_builder(),
                    cache=cache,
                    max_attempts=2,
                    max_tokens=4096,
                )
                generated_error = None
                try:
                    generated_text = generator.generate(reference)
                except LLMAPIError as error:
                    generated_text = None
                    generated_error = error
                validator_result = validator.validate(raw_output.strip(), reference.details)
                cached_template = cache.load(reference.details.hash())
                sample_values = {name: getattr(reference, name) for name in names}
                rendered = None
                render_pass = False
                if analysis["schema_compliant"] and analysis["template_valid"]:
                    rendered = substitute_placeholders(raw_output.strip(), reference)
                    render_pass = (
                        generated_text == rendered
                        and all(rendered.count(str(value)) == 1 for value in sample_values.values())
                        and _PLACEHOLDER.search(rendered) is None
                    )
                schema_pass = analysis["schema_compliant"] and actual_details == expected_types
                overall_case_pass = (
                    (schema_pass and analysis["template_valid"] and semantic_valid and render_pass
                     and validator_result.valid and generated_error is None
                     and len(provider.prompts) == 1
                     and cached_template == raw_output.strip())
                    if should_be_valid
                    else (not validator_result.valid and isinstance(generated_error, LLMAPIError)
                          and cached_template is None and len(provider.prompts) == 2)
                )
                if not overall_case_pass:
                    failures.append(
                        f"{label}: expected validator.valid={should_be_valid}; "
                        f"actual={validator_result.valid}; missing={analysis['missing']}; "
                        f"unknown={analysis['unknown']}; cached={cached_template is not None}"
                    )

                lines.extend((
                    "=" * 72,
                    f"CASE {index}: {label}",
                    "=" * 72,
                    "REFERENCE SCHEMA",
                    f"Class: {type(reference).__name__}",
                    f"Declared fields and types: {expected_types}",
                    f"Actual ReferenceDetails: {actual_details}",
                    f"Expected placeholders: {[f'[{name}]' for name in names]}",
                    f"Sample values: {sample_values}",
                    "",
                    "EXACT LLM INPUT",
                ))
                for prompt_index, prompt in enumerate(provider.prompts, 1):
                    lines.extend((f"Attempt {prompt_index}:", prompt, ""))
                lines.append("EXACT RAW LLM OUTPUT")
                for output_index, output in enumerate(provider.outputs, 1):
                    lines.extend((f"Attempt {output_index}:", output, ""))
                lines.extend((
                    "VALIDATION",
                    f"Detected placeholders: {[f'[{name}]' for name in analysis['detected']]}",
                    f"Expected placeholders: {[f'[{name}]' for name in names]}",
                    f"Missing placeholders: {analysis['missing']}",
                    f"Unknown placeholders: {analysis['unknown']}",
                    f"Duplicate placeholders: {analysis['duplicates']}",
                    f"Schema compliance: {'PASS' if schema_pass else 'FAIL'}",
                    f"Template validity: {'PASS' if analysis['template_valid'] else 'FAIL'}",
                    f"Rendering test: {'PASS' if render_pass else 'FAIL' if should_be_valid else 'NOT APPLICABLE'}",
                    f"Semantic validity: {'PASS' if semantic_valid else 'FAIL'}",
                    "Semantic check: each placeholder has a matching source, page, section, or article cue.",
                    f"Actual TemplateValidator.valid: {validator_result.valid}",
                    f"Actual TemplateValidator error: {validator_result.error_message() or 'none'}",
                    f"Expected validator rejection: {not should_be_valid}",
                    f"Generator LLM call count: {len(provider.prompts)}",
                    f"Template cached: {cached_template is not None}",
                    "RENDER TEST",
                    f"Rendered result: {rendered if rendered is not None else 'not attempted; schema incomplete'}",
                    f"Generator result: {generated_text if generated_error is None else 'controlled failure'}",
                    f"Generator error: {generated_error if generated_error is not None else 'none'}",
                    f"Case result: {'PASS' if overall_case_pass else 'FAIL'}",
                    "",
                ))
                if provider.prompts:
                    for prompt in provider.prompts:
                        for name, type_name in expected_types:
                            property_row = f"| {name} | {type_name} |"
                            if property_row not in prompt:
                                failures.append(
                                    f"{label}: LLM prompt omitted schema row {property_row!r}"
                                )
                if not should_be_valid and len(provider.prompts) > 1:
                    if validator_result.error_message() not in provider.prompts[1]:
                        failures.append(
                            f"{label}: retry prompt omitted validator feedback"
                        )

        lines.extend((
            "=" * 72,
            "IMPLEMENTATION CHECKS",
            "=" * 72,
            f"Plain annotated Reference schema and generation: {'PASS' if plain_pass else 'FAIL'}",
            "Dataclass and alternate-wording cases are evaluated separately above.",
            "Invalid responses must raise a controlled LLM error and remain uncached.",
            "LLMBaseReferenceGenerator.generate accepts a Reference instance.",
            "",
            "=" * 72,
            "FINAL RESULT",
            "=" * 72,
            f"Failed requirements: {len(failures)}",
            *[f"- {failure}" for failure in failures],
            f"LLMReferenceGenerator Test Result: {'FAIL' if failures else 'PASS'}",
            "",
        ))
        report = "\n".join(lines)
        path = Path(os.environ.get(
            "LLM_REFERENCE_REPORT_PATH",
            str(Path(gettempdir()) / "llm_reference_generator_schema_report.txt"),
        ))
        path.write_text(report, encoding="utf-8")
        print(f"Execution report: {path}")
        if failures:
            self.fail("\n".join(failures) + f"\nFull report: {path}")


if __name__ == "__main__":
    unittest.main()
