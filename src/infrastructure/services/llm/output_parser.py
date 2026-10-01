"""Validate final Generation JSON and resolve fitted prompt citations."""

import json
import re
from collections.abc import Mapping

from src.application.dtos import GenerationResult, SimilarSuggestionInput
from src.application.exceptions import (
    LLMInvalidCitationError,
    LLMOutputParseError,
    LLMOutputSchemaError,
    LLMUnknownCitationError,
)
from src.application.interfaces.i_output_parser import IOutputParser
from src.domain.entities import GenerationChunk


_CITATION_ID_PATTERN = re.compile(r"\[[a-z][a-z0-9-]* [0-9]{3}\]")


class GenerationOutputParser(IOutputParser):
    """Resolve only IDs present in ``citation_map_for(fitted_output)``."""

    def parse(
        self,
        raw_output: str,
        *,
        citation_map: Mapping[str, GenerationChunk | SimilarSuggestionInput],
    ) -> GenerationResult:
        if not isinstance(raw_output, str) or not raw_output.strip():
            raise LLMOutputParseError("Final LLM output must be non-empty JSON text")
        try:
            output = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise LLMOutputParseError("Final LLM output is not valid JSON") from exc

        if not isinstance(output, dict):
            raise LLMOutputSchemaError("Final LLM output must be a JSON object")
        answer = output.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise LLMOutputSchemaError(
                "Final LLM output requires a non-blank answer string"
            )
        citations = output.get("citations")
        if not isinstance(citations, list):
            raise LLMOutputSchemaError("Final LLM output requires a citations list")
        if not isinstance(citation_map, Mapping):
            raise TypeError("citation_map must be a retained citation mapping")

        uncertainty = output.get("uncertainty")
        if uncertainty is not None and (
            not isinstance(uncertainty, str) or not uncertainty.strip()
        ):
            raise LLMOutputSchemaError("uncertainty must be a non-blank string or null")

        resolved: dict[str, GenerationChunk | SimilarSuggestionInput] = {}
        for citation_id in citations:
            if not isinstance(citation_id, str) or not _CITATION_ID_PATTERN.fullmatch(
                citation_id
            ):
                raise LLMInvalidCitationError(f"Invalid citation ID: {citation_id!r}")
            if citation_id in resolved:
                continue
            if citation_id not in citation_map:
                raise LLMUnknownCitationError(
                    f"Citation ID is not retained in the fitted prompt: {citation_id}"
                )
            item = citation_map[citation_id]
            if not isinstance(item, (GenerationChunk, SimilarSuggestionInput)):
                raise LLMInvalidCitationError(
                    f"Citation ID does not resolve to supported evidence: {citation_id}"
                )
            resolved[citation_id] = item

        return GenerationResult(
            answer=answer, citations=list(resolved.values()), uncertainty=uncertainty
        )
