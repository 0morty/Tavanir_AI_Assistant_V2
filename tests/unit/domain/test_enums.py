import pytest

from src.domain.enums import (
    AuthorityLevel,
    ChunkStatus,
    RegulatoryDocumentType,
    SourceType,
    SuggestionChunkType,
    SuggestionStatus,
)
from src.domain.exceptions import InvalidSuggestionStatusError


def test_suggestion_status_mapping():
    assert SuggestionStatus.APPROVED.title_fa == "مصوب"
    assert SuggestionStatus.APPROVED.status_id == 3

    assert SuggestionStatus.from_string("مصوب") == SuggestionStatus.APPROVED
    assert SuggestionStatus.from_string("APPROVED") == SuggestionStatus.APPROVED
    assert SuggestionStatus.from_id(3) == SuggestionStatus.APPROVED

    with pytest.raises(InvalidSuggestionStatusError):
        SuggestionStatus.from_string("نامعتبر")

    with pytest.raises(InvalidSuggestionStatusError):
        SuggestionStatus.from_id(999)


def test_suggestion_chunk_type():
    assert SuggestionChunkType.TITLE.value == "title"
    assert SuggestionChunkType.PROBLEM.value == "problem"
    assert SuggestionChunkType.SOLUTION.value == "solution"
    assert SuggestionChunkType.EVALUATION.value == "evaluation"


def test_regulatory_document_type():
    assert RegulatoryDocumentType.STATUTE.value == "statute"
    assert RegulatoryDocumentType.REGULATION.value == "regulation"
    assert RegulatoryDocumentType.DIRECTIVE.value == "directive"
    assert RegulatoryDocumentType.PROCEDURE.value == "procedure"
    assert RegulatoryDocumentType.GUIDELINE.value == "guideline"


def test_authority_level():
    assert AuthorityLevel.BINDING.value == "binding"
    assert AuthorityLevel.GUIDANCE.value == "guidance"


def test_chunk_status():
    assert ChunkStatus.ACTIVE.value == "active"
    assert ChunkStatus.STAGING.value == "staging"
    assert ChunkStatus.DEPRECATED.value == "deprecated"


def test_source_type():
    assert SourceType.SUGGESTION.value == ("suggestion", 1)
    assert SourceType.STATUTE.value == ("statute", 2)
