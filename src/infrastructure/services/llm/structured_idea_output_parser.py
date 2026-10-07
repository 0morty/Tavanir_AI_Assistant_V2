"""Strictly parse the five marked, separator-delimited idea fields."""

import re

from src.application.dtos import StructuredIdeaResult
from src.application.exceptions import LLMOutputParseError, LLMOutputSchemaError
from src.application.interfaces.i_structured_idea_output_parser import (
    IStructuredIdeaOutputParser,
)
from src.application.prompt.structure_idea_prompt_config import (
    IDEA_OUTPUT_MARKERS,
    IDEA_OUTPUT_SEPARATOR,
)


class StructuredIdeaOutputParser(IStructuredIdeaOutputParser):
    def parse(self, raw_output: str) -> StructuredIdeaResult:
        if not isinstance(raw_output, str) or not raw_output.strip():
            raise LLMOutputParseError("Idea model output must be nonblank plain text")

        normalized = raw_output.replace("\r\n", "\n")
        blocks = normalized.split(IDEA_OUTPUT_SEPARATOR)
        if len(blocks) != 5 or normalized.count("***") != 4:
            raise LLMOutputSchemaError(
                "Idea model output requires five blocks and four standalone *** separators"
            )
        if "```" in normalized or re.search(
            r"(?m)^\s*(?:#{1,6}(?:\s|$)|~~~)", normalized
        ):
            raise LLMOutputSchemaError("Idea model output must not contain Markdown formatting")

        values: list[str] = []
        for expected_marker, block in zip(IDEA_OUTPUT_MARKERS, blocks):
            marker, newline, content = block.partition("\n")
            if marker != expected_marker or not newline or not content.strip():
                raise LLMOutputSchemaError(
                    "Idea model output requires the exact ordered markers and nonblank fields"
                )
            if any(
                re.fullmatch(r"\s*\{[^{}\n]+\}\s*", line)
                for line in content.splitlines()
            ):
                raise LLMOutputSchemaError("Idea model output contains an additional field marker")
            values.append(content.strip())

        return StructuredIdeaResult(
            title=values[0],
            current_problem=values[1],
            solution=values[2],
            advantage=values[3],
            disadvantage=values[4],
        )
