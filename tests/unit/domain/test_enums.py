import pytest

from src.domain.enums import (
    AuthorityLevel,
    ChunkStatus,
    CommitteeScrutiny,
    OverflowStrategy,
    RegulatoryDocumentType,
    SecretariatScrutiny,
    SourceType,
    SuggestionChunkType,
    SuggestionStatus,
)
from src.domain.exceptions import (
    InvalidCommitteeScrutinyError,
    InvalidSecretariatScrutinyError,
    InvalidSuggestionStatusError,
)


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


def test_overflow_strategy():
    assert OverflowStrategy.TRUNCATE.value == "truncate"
    assert OverflowStrategy.SUMMARIZE.value == "summarize"
    assert OverflowStrategy.IGNORE.value == "ignore"


def test_source_type():
    assert SourceType.SUGGESTION.value == ("suggestion", 1)
    assert SourceType.STATUTE.value == ("statute", 2)


def test_secretariat_scrutiny_enum():
    # Codes and titles
    assert SecretariatScrutiny.SEND_TO_APPROVER.code == -2
    assert SecretariatScrutiny.SEND_TO_APPROVER.title_fa == "ارسال به تایید کننده"
    assert SecretariatScrutiny.OUT_OF_FRAMEWORK.code == 0
    assert SecretariatScrutiny.AUTO_REJECTED_EXPERT.code == 17

    # Resolver from_code (negative, zero, positive)
    assert SecretariatScrutiny.from_code(-2) == SecretariatScrutiny.SEND_TO_APPROVER
    assert SecretariatScrutiny.from_code(0) == SecretariatScrutiny.OUT_OF_FRAMEWORK
    assert SecretariatScrutiny.from_code(17) == SecretariatScrutiny.AUTO_REJECTED_EXPERT

    # Resolver from_string (exact and normalized)
    assert (
        SecretariatScrutiny.from_string("خارج از چهارچوب")
        == SecretariatScrutiny.OUT_OF_FRAMEWORK
    )
    assert (
        SecretariatScrutiny.from_string("OUT_OF_FRAMEWORK")
        == SecretariatScrutiny.OUT_OF_FRAMEWORK
    )

    # Properties
    assert SecretariatScrutiny.DUPLICATE.is_duplicate is True
    assert SecretariatScrutiny.ALREADY_SUBMITTED_BY_PERSON.is_duplicate is True
    assert SecretariatScrutiny.ALREADY_SUBMITTED_BY_NUMBER.is_duplicate is True
    assert SecretariatScrutiny.OUT_OF_FRAMEWORK.is_duplicate is False

    assert SecretariatScrutiny.OUT_OF_FRAMEWORK.is_rejection is True
    assert SecretariatScrutiny.GENERAL_CONDITIONS_NOT_MET.is_rejection is True
    assert SecretariatScrutiny.NOT_A_SUGGESTION.is_rejection is True
    assert SecretariatScrutiny.REJECTED.is_rejection is True
    assert SecretariatScrutiny.AUTO_REJECTED_EXPERT.is_rejection is True
    assert SecretariatScrutiny.REFER_TO_COMMITTEE.is_rejection is False

    # Errors on invalid inputs
    with pytest.raises(InvalidSecretariatScrutinyError):
        SecretariatScrutiny.from_code(999)

    with pytest.raises(InvalidSecretariatScrutinyError):
        SecretariatScrutiny.from_string("متن غیرمعتبر")


def test_committee_scrutiny_enum():
    # Codes and titles
    assert CommitteeScrutiny.SELECT_CONSULTANT_RETURN_FOR_CORRECTION.code == -10
    assert CommitteeScrutiny.APPROVED.code == 0
    assert CommitteeScrutiny.APPROVED_PRELIMINARY.code == -3
    assert CommitteeScrutiny.ACCEPTED_AS_EXECUTED_SUGGESTION.code == 6

    # Resolvers from_code (boundary negative, zero, positive)
    assert (
        CommitteeScrutiny.from_code(-10)
        == CommitteeScrutiny.SELECT_CONSULTANT_RETURN_FOR_CORRECTION
    )
    assert CommitteeScrutiny.from_code(0) == CommitteeScrutiny.APPROVED
    assert CommitteeScrutiny.from_code(-3) == CommitteeScrutiny.APPROVED_PRELIMINARY
    assert CommitteeScrutiny.from_code(1) == CommitteeScrutiny.REJECTED

    # Disambiguation: string "تایید" resolves to code 0 (APPROVED)
    assert CommitteeScrutiny.from_string("تایید") == CommitteeScrutiny.APPROVED
    assert CommitteeScrutiny.from_string("APPROVED") == CommitteeScrutiny.APPROVED
    assert (
        CommitteeScrutiny.from_string("APPROVED_PRELIMINARY")
        == CommitteeScrutiny.APPROVED_PRELIMINARY
    )

    # Persian normalization in lookup
    assert (
        CommitteeScrutiny.from_string("رد به دلیل رد کارشناسی")
        == CommitteeScrutiny.REJECTED_EXPERT_OPINION
    )

    # Errors on invalid inputs
    with pytest.raises(InvalidCommitteeScrutinyError):
        CommitteeScrutiny.from_code(999)

    with pytest.raises(InvalidCommitteeScrutinyError):
        CommitteeScrutiny.from_string("وضعیت ناموجود")
