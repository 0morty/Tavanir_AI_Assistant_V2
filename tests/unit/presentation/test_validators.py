import pytest

from src.domain.enums import (
    CommitteeScrutiny,
    SecretariatScrutiny,
    SuggestionStatus,
)
from src.domain.exceptions import (
    InvalidCommitteeScrutinyError,
    InvalidSecretariatScrutinyError,
    InvalidSuggestionStatusError,
)
from src.presentation.schemas.validators import (
    empty_str_to_none,
    normalize_digits_to_ascii,
    parse_committee_scrutiny,
    parse_secretariat_scrutiny,
    parse_suggestion_status,
)


def test_empty_str_to_none():
    assert empty_str_to_none(None) is None
    assert empty_str_to_none("") is None
    assert empty_str_to_none("   ") is None
    assert empty_str_to_none("valid") == "valid"
    assert empty_str_to_none(123) == 123


def test_normalize_digits_to_ascii():
    assert normalize_digits_to_ascii(None) is None
    assert normalize_digits_to_ascii("۰۱۲۳۴۵۶۷۸۹") == "0123456789"
    assert normalize_digits_to_ascii("٠١٢٣٤٥٦٧٨٩") == "0123456789"
    assert normalize_digits_to_ascii("-۱۰") == "-10"


def test_parse_committee_scrutiny():
    # None and empty strings
    assert parse_committee_scrutiny(None) is None
    assert parse_committee_scrutiny("") is None
    assert parse_committee_scrutiny("   ") is None

    # Enum direct pass
    assert parse_committee_scrutiny(CommitteeScrutiny.APPROVED) == CommitteeScrutiny.APPROVED

    # Integer codes (negative, zero, positive)
    assert parse_committee_scrutiny(-10) == CommitteeScrutiny.SELECT_CONSULTANT_RETURN_FOR_CORRECTION
    assert parse_committee_scrutiny(0) == CommitteeScrutiny.APPROVED
    assert parse_committee_scrutiny(-3) == CommitteeScrutiny.APPROVED_PRELIMINARY
    assert parse_committee_scrutiny(1) == CommitteeScrutiny.REJECTED
    assert parse_committee_scrutiny(21) == CommitteeScrutiny.ON_COMPANY_AGENDA

    # String integer codes (including negative and Persian digits)
    assert parse_committee_scrutiny("-10") == CommitteeScrutiny.SELECT_CONSULTANT_RETURN_FOR_CORRECTION
    assert parse_committee_scrutiny("-۱۰") == CommitteeScrutiny.SELECT_CONSULTANT_RETURN_FOR_CORRECTION
    assert parse_committee_scrutiny("0") == CommitteeScrutiny.APPROVED
    assert parse_committee_scrutiny("۰") == CommitteeScrutiny.APPROVED
    assert parse_committee_scrutiny("1") == CommitteeScrutiny.REJECTED

    # Disambiguation: "تایید" maps to 0 (APPROVED)
    assert parse_committee_scrutiny("تایید") == CommitteeScrutiny.APPROVED

    # Persian titles
    assert parse_committee_scrutiny("رد") == CommitteeScrutiny.REJECTED
    assert parse_committee_scrutiny("ارسال به کارشناس") == CommitteeScrutiny.SEND_TO_EXPERT

    # Errors on unmapped codes or titles
    with pytest.raises(InvalidCommitteeScrutinyError) as exc_info:
        parse_committee_scrutiny(999)
    assert exc_info.value.pointer == "/data/committeeScrutiny"
    assert exc_info.value.field_name == "committee_scrutiny"

    with pytest.raises(InvalidCommitteeScrutinyError):
        parse_committee_scrutiny("-999")

    with pytest.raises(InvalidCommitteeScrutinyError):
        parse_committee_scrutiny("عنوان ناموجود کمیته")


def test_parse_secretariat_scrutiny():
    # None and empty strings
    assert parse_secretariat_scrutiny(None) is None
    assert parse_secretariat_scrutiny("") is None
    assert parse_secretariat_scrutiny("   ") is None

    # Enum direct pass
    assert parse_secretariat_scrutiny(SecretariatScrutiny.SEND_TO_APPROVER) == SecretariatScrutiny.SEND_TO_APPROVER

    # Integer codes (negative, zero, positive)
    assert parse_secretariat_scrutiny(-2) == SecretariatScrutiny.SEND_TO_APPROVER
    assert parse_secretariat_scrutiny(0) == SecretariatScrutiny.OUT_OF_FRAMEWORK
    assert parse_secretariat_scrutiny(6) == SecretariatScrutiny.DUPLICATE
    assert parse_secretariat_scrutiny(17) == SecretariatScrutiny.AUTO_REJECTED_EXPERT

    # String integer codes (including negative and Persian digits)
    assert parse_secretariat_scrutiny("-2") == SecretariatScrutiny.SEND_TO_APPROVER
    assert parse_secretariat_scrutiny("-۲") == SecretariatScrutiny.SEND_TO_APPROVER
    assert parse_secretariat_scrutiny("0") == SecretariatScrutiny.OUT_OF_FRAMEWORK
    assert parse_secretariat_scrutiny("۶") == SecretariatScrutiny.DUPLICATE

    # Persian titles
    assert parse_secretariat_scrutiny("خارج از چهارچوب") == SecretariatScrutiny.OUT_OF_FRAMEWORK
    assert parse_secretariat_scrutiny("ارجاع به کمیته") == SecretariatScrutiny.REFER_TO_COMMITTEE

    # Errors on unmapped codes or titles
    with pytest.raises(InvalidSecretariatScrutinyError) as exc_info:
        parse_secretariat_scrutiny(999)
    assert exc_info.value.pointer == "/data/secretariatScrutiny"
    assert exc_info.value.field_name == "secretariat_scrutiny"

    with pytest.raises(InvalidSecretariatScrutinyError):
        parse_secretariat_scrutiny("-999")

    with pytest.raises(InvalidSecretariatScrutinyError):
        parse_secretariat_scrutiny("عنوان ناموجود دبیرخانه")
