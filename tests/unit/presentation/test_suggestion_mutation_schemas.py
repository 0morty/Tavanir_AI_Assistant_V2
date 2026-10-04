import pytest
from pydantic import ValidationError

from src.application.dtos import (
    BulkDeleteSuggestionsDTO,
    PatchSuggestionDTO,
    UpdateSuggestionDTO,
)
from src.domain.enums import CommitteeScrutiny, SuggestionStatus
from src.domain.exceptions import DomainError
from src.presentation.schemas.v1 import (
    BulkDeleteRequest,
    PatchSuggestionRequest,
    UpdateSuggestionRequest,
)


def test_put_requires_mandatory_fields():
    # Missing problem, solution, status
    with pytest.raises(ValidationError) as exc_info:
        UpdateSuggestionRequest.model_validate({"title": "عنوان جدید"})
    errors = exc_info.value.errors()
    missing_fields = {e["loc"][0] for e in errors}
    assert "problem" in missing_fields or "currentProblem" in missing_fields
    assert "solution" in missing_fields
    assert "status" in missing_fields


def test_put_body_id_mismatch_raises():
    req = UpdateSuggestionRequest.model_validate(
        {
            "suggestionId": "sugg-body-1",
            "title": "عنوان معتبر",
            "problem": "شرح مشکل سازمان",
            "solution": "راهکار عملیاتی",
            "status": "مصوب",
        }
    )
    with pytest.raises((ValueError, DomainError), match="does not match URL path"):
        req.to_dto(path_suggestion_id="sugg-path-2")


def test_put_valid_conversion_to_dto():
    req = UpdateSuggestionRequest.model_validate(
        {
            "title": "بهینه‌سازی سیستم‌ها",
            "problem": "فرسودگی تجهیزات",
            "solution": "تعویض تجهیزات فرسوده",
            "status": "مصوب",
            "committeeScrutiny": "تایید",
            "shamsiDate": "۱۴۰۲/۰۶/۱۵",
            "contextTitle": "معاونت توزیع",
        }
    )
    dto = req.to_dto(path_suggestion_id="sugg-100")
    assert isinstance(dto, UpdateSuggestionDTO)
    assert dto.suggestion_id == "sugg-100"
    assert dto.title == "بهینه‌سازی سیستم‌ها"
    assert dto.status == SuggestionStatus.APPROVED
    assert dto.committee_scrutiny == CommitteeScrutiny.APPROVED
    assert dto.shamsi_date == "1402/06/15"
    assert dto.context_title == "معاونت توزیع"


def test_patch_rejects_suggestion_id_in_body():
    with pytest.raises(ValidationError) as exc_info:
        PatchSuggestionRequest.model_validate(
            {"suggestionId": "sugg-100", "title": "عنوان جدید"}
        )
    assert "immutable" in str(exc_info.value)


def test_patch_rejects_empty_or_all_null_payload():
    with pytest.raises(ValidationError) as exc_info:
        PatchSuggestionRequest.model_validate({})
    assert "At least one non-null field" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        PatchSuggestionRequest.model_validate({"title": None, "problem": None})
    assert "At least one non-null field" in str(exc_info.value)


def test_patch_ignores_omitted_and_null_fields():
    req = PatchSuggestionRequest.model_validate(
        {"title": "عنوان جدید برای پیشنهاد", "problem": None}
    )
    dto = req.to_dto(path_suggestion_id="sugg-100")
    assert isinstance(dto, PatchSuggestionDTO)
    assert dto.suggestion_id == "sugg-100"
    assert dto.title == "عنوان جدید برای پیشنهاد"
    assert dto.problem is None
    assert dto.solution is None
    assert dto.status is None


def test_bulk_delete_validation_bounds():
    # Empty list
    with pytest.raises(ValidationError):
        BulkDeleteRequest.model_validate({"suggestionIds": []})

    # More than 100 items
    with pytest.raises(ValidationError) as exc_info:
        BulkDeleteRequest.model_validate(
            {"suggestionIds": [f"id-{i}" for i in range(101)]}
        )
    assert "100 items" in str(exc_info.value)

    # Duplicate IDs
    with pytest.raises(ValidationError) as exc_info:
        BulkDeleteRequest.model_validate(
            {"suggestionIds": ["sugg-1", "sugg-2", "sugg-1"]}
        )
    assert "Duplicate" in str(exc_info.value)

    # Empty string inside items
    with pytest.raises(ValidationError) as exc_info:
        BulkDeleteRequest.model_validate({"suggestionIds": ["sugg-1", "   "]})
    assert "non-empty string" in str(exc_info.value)

    # Valid batch
    req = BulkDeleteRequest.model_validate(
        {"suggestionIds": ["sugg-1", "sugg-2", "sugg-3"]}
    )
    dto = req.to_dto()
    assert isinstance(dto, BulkDeleteSuggestionsDTO)
    assert dto.suggestion_ids == ["sugg-1", "sugg-2", "sugg-3"]


def test_patch_rejects_blank_or_whitespace_only_payload():
    # Blank or whitespace-only optional strings must be rejected as no-ops
    with pytest.raises(ValidationError) as exc_info:
        PatchSuggestionRequest.model_validate({"description": "   "})
    assert "At least one non-null field" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        PatchSuggestionRequest.model_validate({"contextTitle": ""})
    assert "At least one non-null field" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        PatchSuggestionRequest.model_validate(
            {"description": "   ", "contextTitle": "", "shamsiDate": " "}
        )
    assert "At least one non-null field" in str(exc_info.value)


def test_context_title_length_bounds():
    # 512 is valid
    valid_title = "a" * 512
    req = PatchSuggestionRequest.model_validate({"contextTitle": valid_title})
    assert req.context_title == valid_title

    # 513 is rejected
    invalid_title = "a" * 513
    with pytest.raises(ValidationError):
        PatchSuggestionRequest.model_validate({"contextTitle": invalid_title})

