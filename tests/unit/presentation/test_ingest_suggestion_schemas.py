import pytest
from pydantic import ValidationError
from src.presentation.schemas.v1.ingest_suggestion_request import (
    IngestSuggestionRequest,
)
from src.presentation.schemas.v1.ingest_suggestion_response import (
    IngestSuggestionDataResponse,
)

from src.application.dtos import CreateSuggestionDTO
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
    normalize_digits_to_ascii,
    parse_committee_scrutiny,
    parse_secretariat_scrutiny,
    parse_suggestion_status,
)


def test_normalize_digits_to_ascii():
    assert normalize_digits_to_ascii(None) is None
    assert normalize_digits_to_ascii("۱۴۰۲/۰۸/۱۵") == "1402/08/15"
    assert normalize_digits_to_ascii("١٤٠٢/٠٨/١٥") == "1402/08/15"
    assert normalize_digits_to_ascii("1402/08/15") == "1402/08/15"


def test_parse_suggestion_status_variants():
    assert parse_suggestion_status(SuggestionStatus.APPROVED) == SuggestionStatus.APPROVED
    assert parse_suggestion_status(3) == SuggestionStatus.APPROVED
    assert parse_suggestion_status("3") == SuggestionStatus.APPROVED
    assert parse_suggestion_status("۳") == SuggestionStatus.APPROVED
    assert parse_suggestion_status("مصوب") == SuggestionStatus.APPROVED
    assert parse_suggestion_status("APPROVED") == SuggestionStatus.APPROVED

    with pytest.raises(InvalidSuggestionStatusError):
        parse_suggestion_status(None)

    with pytest.raises(InvalidSuggestionStatusError):
        parse_suggestion_status("")

    with pytest.raises(InvalidSuggestionStatusError):
        parse_suggestion_status("نامشخص")

    with pytest.raises(InvalidSuggestionStatusError):
        parse_suggestion_status(999)


def test_ingest_suggestion_request_valid_camel_case():
    payload = {
        "suggestionId": "sugg-201",
        "title": "عنوان پیشنهاد بررسی شبکه",
        "problem": "شرح مشکل مربوط به خطوط انتقال نیرو",
        "solution": "راهکار تعویض مقره‌ها با نوع سیلیکونی",
        "status": "مصوب",
        "committeeScrutiny": "تایید",
        "description": "ابلاغ شده برای اجرا در سال آینده",
        "shamsiDate": "۱۴۰۲/۰۵/۲۰",
        "contextTitle": "معاونت انتقال",
    }

    req = IngestSuggestionRequest.model_validate(payload)
    assert req.suggestion_id == "sugg-201"
    assert req.status == SuggestionStatus.APPROVED
    assert req.committee_scrutiny == CommitteeScrutiny.APPROVED
    assert req.shamsi_date == "1402/05/20"
    assert req.context_title == "معاونت انتقال"

    dto = req.to_dto()
    assert isinstance(dto, CreateSuggestionDTO)
    assert dto.suggestion_id == "sugg-201"
    assert dto.status == SuggestionStatus.APPROVED
    assert dto.committee_scrutiny == CommitteeScrutiny.APPROVED
    assert dto.committee_scrutiny_id == 0
    assert dto.shamsi_date == "1402/05/20"
    assert dto.context_title == "معاونت انتقال"


def test_ingest_suggestion_request_with_secretariat_fields():
    payload = {
        "suggestionId": "sugg-sec-1",
        "title": "عنوان پیشنهاد",
        "problem": "شرح مشکل",
        "solution": "راهکار اجرایی",
        "status": 1,
        "secretariatScrutiny": "خارج از چهارچوب",
        "secretariatComment": "موضوع در حوزه وظایف شرکت مادر تخصصی نیست.",
    }
    req = IngestSuggestionRequest.model_validate(payload)
    assert req.secretariat_scrutiny == SecretariatScrutiny.OUT_OF_FRAMEWORK
    assert req.secretariat_comment == "موضوع در حوزه وظایف شرکت مادر تخصصی نیست."

    dto = req.to_dto()
    assert dto.secretariat_scrutiny == SecretariatScrutiny.OUT_OF_FRAMEWORK
    assert dto.secretariat_scrutiny_id == 0
    assert dto.secretariat_comment == "موضوع در حوزه وظایف شرکت مادر تخصصی نیست."


def test_ingest_suggestion_request_with_legacy_tributary_aliases():
    payload = {
        "suggestionId": "sugg-trib-1",
        "title": "عنوان پیشنهاد",
        "problem": "شرح مشکل",
        "solution": "راهکار اجرایی",
        "status": 1,
        "tributaryScrutiny": 6,
        "tributaryComment": "پیشنهاد تکراری با شماره ۱۲۳۴۵",
    }
    req = IngestSuggestionRequest.model_validate(payload)
    assert req.secretariat_scrutiny == SecretariatScrutiny.DUPLICATE
    assert req.secretariat_comment == "پیشنهاد تکراری با شماره ۱۲۳۴۵"

    dto = req.to_dto()
    assert dto.secretariat_scrutiny == SecretariatScrutiny.DUPLICATE
    assert dto.secretariat_scrutiny_id == 6
    assert dto.secretariat_comment == "پیشنهاد تکراری با شماره ۱۲۳۴۵"


def test_ingest_suggestion_request_conflicting_scrutiny_aliases_raises_422():
    payload = {
        "suggestionId": "sugg-conflict-1",
        "title": "عنوان پیشنهاد",
        "problem": "شرح مشکل",
        "solution": "راهکار اجرایی",
        "status": 1,
        "secretariatScrutiny": 0,
        "tributaryScrutiny": 6,
    }
    with pytest.raises(ValidationError) as exc_info:
        IngestSuggestionRequest.model_validate(payload)
    assert "Cannot supply both" in str(exc_info.value)


def test_ingest_suggestion_request_conflicting_comment_aliases_raises_422():
    payload = {
        "suggestionId": "sugg-conflict-2",
        "title": "عنوان پیشنهاد",
        "problem": "شرح مشکل",
        "solution": "راهکار اجرایی",
        "status": 1,
        "secretariatComment": "نظر رسمی اول",
        "tributaryComment": "نظر رسمی دوم",
    }
    with pytest.raises(ValidationError) as exc_info:
        IngestSuggestionRequest.model_validate(payload)
    assert "Cannot supply both" in str(exc_info.value)


def test_ingest_suggestion_request_numeric_scrutiny_codes():
    payload = {
        "suggestionId": "sugg-num-1",
        "title": "عنوان پیشنهاد",
        "problem": "شرح مشکل",
        "solution": "راهکار اجرایی",
        "status": 2,
        "committeeScrutiny": -10,
        "secretariatScrutiny": "-2",
    }
    req = IngestSuggestionRequest.model_validate(payload)
    assert req.committee_scrutiny == CommitteeScrutiny.SELECT_CONSULTANT_RETURN_FOR_CORRECTION
    assert req.secretariat_scrutiny == SecretariatScrutiny.SEND_TO_APPROVER


def test_ingest_suggestion_request_supports_snake_case_fields():
    payload = {
        "suggestion_id": "sugg-snake-1",
        "title": "عنوان پیشنهاد",
        "problem": "شرح مشکل",
        "solution": "راهکار اجرایی",
        "status": "مصوب",
        "committee_scrutiny": "تایید",
        "secretariat_scrutiny": "خارج از چهارچوب",
        "secretariat_comment": "توضیحات دبیرخانه",
        "shamsi_date": "1402/05/20",
        "context_title": "معاونت انتقال",
    }
    req = IngestSuggestionRequest.model_validate(payload)
    assert req.suggestion_id == "sugg-snake-1"
    assert req.committee_scrutiny == CommitteeScrutiny.APPROVED
    assert req.secretariat_scrutiny == SecretariatScrutiny.OUT_OF_FRAMEWORK
    assert req.secretariat_comment == "توضیحات دبیرخانه"


def test_ingest_suggestion_request_rejects_legacy_scrutiny_field():
    payload = {
        "suggestionId": "sugg-legacy-1",
        "title": "عنوان پیشنهاد معتبر",
        "problem": "شرح مشکل معتبر سازمانی",
        "solution": "راهکار اجرایی معتبر سازمانی",
        "status": "APPROVED",
        "scrutiny": "تایید",
    }
    with pytest.raises(ValidationError) as exc_info:
        IngestSuggestionRequest.model_validate(payload)
    assert "extra_forbidden" in str(exc_info.value) or "Extra inputs are not permitted" in str(exc_info.value)


def test_ingest_suggestion_request_empty_strings_coerced_to_none():
    payload = {
        "suggestionId": "sugg-202",
        "title": "عنوان پیشنهاد معتبر",
        "problem": "شرح مشکل معتبر سازمانی",
        "solution": "راهکار اجرایی معتبر سازمانی",
        "status": 3,
        "committeeScrutiny": "   ",
        "description": "",
        "shamsiDate": "   ",
        "contextTitle": "",
    }

    req = IngestSuggestionRequest.model_validate(payload)
    assert req.committee_scrutiny is None
    assert req.description is None
    assert req.shamsi_date is None
    assert req.context_title is None

    dto = req.to_dto()
    assert dto.committee_scrutiny is None
    assert dto.description is None
    assert dto.shamsi_date is None
    assert dto.context_title is None


def test_ingest_suggestion_request_forbids_extra_fields():
    payload = {
        "suggestionId": "sugg-203",
        "title": "عنوان پیشنهاد معتبر",
        "problem": "شرح مشکل معتبر سازمانی",
        "solution": "راهکار اجرایی معتبر سازمانی",
        "status": "APPROVED",
        "unknown_extra_field": "some_value",
    }

    with pytest.raises(ValidationError):
        IngestSuggestionRequest.model_validate(payload)


def test_ingest_suggestion_request_rejects_empty_suggestion_id():
    payload = {
        "suggestionId": "   ",
        "title": "عنوان پیشنهاد معتبر",
        "problem": "شرح مشکل معتبر سازمانی",
        "solution": "راهکار اجرایی معتبر سازمانی",
        "status": "APPROVED",
    }

    with pytest.raises(ValidationError):
        IngestSuggestionRequest.model_validate(payload)


def test_ingest_suggestion_data_response_serialization():
    resp = IngestSuggestionDataResponse(
        suggestion_id="sugg-204",
        chunks_count=4,
        status="CREATED",
    )
    dumped = resp.model_dump(by_alias=True)
    assert dumped == {
        "suggestionId": "sugg-204",
        "chunksCount": 4,
        "status": "CREATED",
    }
