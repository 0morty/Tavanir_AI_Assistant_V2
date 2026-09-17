import pytest
from pydantic import ValidationError
from src.presentation.schemas.v1.ingest_suggestion_request import (
    IngestSuggestionRequest,
)
from src.presentation.schemas.v1.ingest_suggestion_response import (
    IngestSuggestionDataResponse,
)

from src.application.dtos import CreateSuggestionDTO
from src.domain.enums import SuggestionStatus
from src.domain.exceptions import InvalidSuggestionStatusError
from src.presentation.schemas.validators import (
    normalize_digits_to_ascii,
    parse_suggestion_status,
)


def test_normalize_digits_to_ascii():
    assert normalize_digits_to_ascii(None) is None
    assert normalize_digits_to_ascii("۱۴۰۲/۰۸/۱۵") == "1402/08/15"
    assert normalize_digits_to_ascii("١٤٠٢/٠٨/١٥") == "1402/08/15"
    assert normalize_digits_to_ascii("1402/08/15") == "1402/08/15"


def test_parse_suggestion_status():
    # Persian titles
    assert parse_suggestion_status("مصوب") == SuggestionStatus.APPROVED
    assert parse_suggestion_status("رد") == SuggestionStatus.REJECTED
    assert parse_suggestion_status("عدم پذیرش") == SuggestionStatus.NOT_ACCEPTED
    assert parse_suggestion_status("در حال اجرا") == SuggestionStatus.PENDING
    assert parse_suggestion_status("اجرا شده") == SuggestionStatus.EXECUTED

    # Enum names
    assert parse_suggestion_status("APPROVED") == SuggestionStatus.APPROVED
    assert parse_suggestion_status("REJECTED") == SuggestionStatus.REJECTED

    # Integer IDs
    assert parse_suggestion_status(3) == SuggestionStatus.APPROVED
    assert parse_suggestion_status("3") == SuggestionStatus.APPROVED

    # Enum direct pass
    assert (
        parse_suggestion_status(SuggestionStatus.APPROVED) == SuggestionStatus.APPROVED
    )

    # Invalid values
    with pytest.raises(InvalidSuggestionStatusError):
        parse_suggestion_status("نامعلوم")

    with pytest.raises(InvalidSuggestionStatusError):
        parse_suggestion_status(999)


def test_ingest_suggestion_request_valid_camel_case():
    payload = {
        "suggestionId": "sugg-201",
        "title": "عنوان پیشنهاد بررسی شبکه",
        "problem": "شرح مشکل مربوط به خطوط انتقال نیرو",
        "solution": "راهکار تعویض مقره‌ها با نوع سیلیکونی",
        "status": "مصوب",
        "scrutiny": "تایید شده در کمیته فنی",
        "description": "ابلاغ شده برای اجرا در سال آینده",
        "shamsiDate": "۱۴۰۲/۰۵/۲۰",
        "contextTitle": "معاونت انتقال",
    }

    req = IngestSuggestionRequest.model_validate(payload)
    assert req.suggestion_id == "sugg-201"
    assert req.status == SuggestionStatus.APPROVED
    assert req.shamsi_date == "1402/05/20"
    assert req.context_title == "معاونت انتقال"

    dto = req.to_dto()
    assert isinstance(dto, CreateSuggestionDTO)
    assert dto.suggestion_id == "sugg-201"
    assert dto.status == SuggestionStatus.APPROVED
    assert dto.shamsi_date == "1402/05/20"
    assert dto.context_title == "معاونت انتقال"


def test_ingest_suggestion_request_empty_strings_coerced_to_none():
    payload = {
        "suggestionId": "sugg-202",
        "title": "عنوان پیشنهاد معتبر",
        "problem": "شرح مشکل معتبر سازمانی",
        "solution": "راهکار اجرایی معتبر سازمانی",
        "status": 3,
        "scrutiny": "   ",
        "description": "",
        "shamsiDate": "   ",
        "contextTitle": "",
    }

    req = IngestSuggestionRequest.model_validate(payload)
    assert req.scrutiny is None
    assert req.description is None
    assert req.shamsi_date is None
    assert req.context_title is None

    dto = req.to_dto()
    assert dto.scrutiny is None
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
