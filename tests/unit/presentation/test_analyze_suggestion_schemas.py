from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.application.dtos import AnalyzeSuggestionDTO
from src.domain.exceptions import InvalidSuggestionContentError
from src.presentation.schemas.v1 import (
    AnalyzeSuggestionDataResponse,
    AnalyzeSuggestionRequest,
)


def test_analyze_suggestion_request_valid_camel_case():
    payload = {
        "title": "کاهش تلفات در خطوط شبکه توزیع",
        "currentProblem": "تلفات بالا در خطوط روستایی به دلیل فرسودگی هادی‌ها",
        "solution": "تعویض سیم‌های مسی با کابل خودنگهدار آلومینیومی",
        "contextTitle": "معاونت مهندسی و نظارت",
    }
    req = AnalyzeSuggestionRequest.model_validate(payload)
    assert req.title == "کاهش تلفات در خطوط شبکه توزیع"
    assert req.current_problem == "تلفات بالا در خطوط روستایی به دلیل فرسودگی هادی‌ها"
    assert req.solution == "تعویض سیم‌های مسی با کابل خودنگهدار آلومینیومی"
    assert req.context_title == "معاونت مهندسی و نظارت"

    dto = req.to_dto()
    assert isinstance(dto, AnalyzeSuggestionDTO)
    assert dto.title == req.title
    assert dto.problem == req.current_problem
    assert dto.solution == req.solution
    assert dto.context_title == req.context_title


def test_analyze_suggestion_request_missing_required_fields():
    # Missing solution
    with pytest.raises(ValidationError) as exc_info:
        AnalyzeSuggestionRequest.model_validate(
            {
                "title": "کاهش تلفات در خطوط شبکه",
                "currentProblem": "تلفات بالا در خطوط روستایی",
            }
        )
    errors = exc_info.value.errors()
    assert any(e["loc"] == ("solution",) for e in errors)


def test_analyze_suggestion_request_rejects_noise_placeholders():
    with pytest.raises(InvalidSuggestionContentError) as exc_info:
        AnalyzeSuggestionRequest.model_validate(
            {
                "title": "کاهش تلفات شبکه توزیع",
                "currentProblem": "ندارد",  # noise placeholder
                "solution": "تعویض سیم با کابل خودنگهدار",
            }
        )
    assert "substantive content" in str(exc_info.value.message)
    assert exc_info.value.pointer == "/data/currentProblem"


def test_analyze_suggestion_request_rejects_short_content():
    with pytest.raises(InvalidSuggestionContentError) as exc_info:
        AnalyzeSuggestionRequest.model_validate(
            {
                "title": "تست",  # < 5 chars
                "currentProblem": "تلفات بالا در خطوط روستایی",
                "solution": "تعویض سیم با کابل خودنگهدار",
            }
        )
    assert "substantive content" in str(exc_info.value.message)


def test_analyze_suggestion_request_forbids_extra_fields():
    with pytest.raises(ValidationError) as exc_info:
        AnalyzeSuggestionRequest.model_validate(
            {
                "title": "کاهش تلفات در خطوط شبکه توزیع",
                "currentProblem": "تلفات بالا در خطوط روستایی به دلیل فرسودگی هادی‌ها",
                "solution": "تعویض سیم‌های مسی با کابل خودنگهدار آلومینیومی",
                "unexpectedField": 12345,
            }
        )
    errors = exc_info.value.errors()
    assert any(e["type"] == "extra_forbidden" for e in errors)


def test_analyze_suggestion_data_response_camel_case_serialization():
    resp = AnalyzeSuggestionDataResponse(
        analysis="## تحلیل اولیه\n\nتطابق کامل یافت شد.",
        similar_executed_ids=["SUG-101", "SUG-102"],
        similar_approved_ids=["SUG-201"],
        similar_pending_ids=["SUG-301"],
        similar_rejected_ids=["SUG-401"],
        similar_not_accepted_ids=["SUG-501"],
        applied_statute_ids=["STAT-01"],
    )
    dumped = resp.model_dump(by_alias=True)
    assert dumped == {
        "analysis": "## تحلیل اولیه\n\nتطابق کامل یافت شد.",
        "similarExecutedIds": ["SUG-101", "SUG-102"],
        "similarApprovedIds": ["SUG-201"],
        "similarPendingIds": ["SUG-301"],
        "similarRejectedIds": ["SUG-401"],
        "similarNotAcceptedIds": ["SUG-501"],
        "appliedStatuteIds": ["STAT-01"],
        "uncertainty": None,
        "citedSuggestionIds": [],
        "isFallbackMode": False,
        "groundingRatio": 0.0,
    }


def test_analyze_suggestion_data_response_with_decision_support_fields():
    resp = AnalyzeSuggestionDataResponse(
        analysis="## تحلیل جامع",
        similar_executed_ids=["SUG-101"],
        uncertainty="عدم قطعیت در تامین قطعات",
        cited_suggestion_ids=["SUG-101"],
        is_fallback_mode=True,
        grounding_ratio=1.0,
    )
    dumped = resp.model_dump(by_alias=True)
    assert dumped["uncertainty"] == "عدم قطعیت در تامین قطعات"
    assert dumped["citedSuggestionIds"] == ["SUG-101"]
    assert dumped["isFallbackMode"] is True
    assert dumped["groundingRatio"] == 1.0
