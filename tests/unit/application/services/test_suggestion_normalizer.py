import pytest
from src.application.services.suggestion_normalizer import normalize_suggestion

from src.domain.entities import (
    CommitteeEvaluation,
    ShamsiDate,
    Suggestion,
    SuggestionContent,
)
from src.domain.enums import SuggestionStatus
from src.infrastructure.services.text_processing.shekar_text_normalizer import (
    ShekarTextNormalizer,
)


@pytest.fixture
def normalizer() -> ShekarTextNormalizer:
    return ShekarTextNormalizer()


def test_normalize_suggestion_cleans_persian_characters_and_zwnj(
    normalizer: ShekarTextNormalizer,
):
    # Contains Arabic 'ي' and 'ك', missing ZWNJ in 'مي شود', etc.
    raw_suggestion = Suggestion(
        id="SUG-9001",
        content=SuggestionContent(
            title="بهينه سازي شبكه توزيع",  # Arabic ه / ي / ك
            problem="ولتاژ پايين مي باشد و باعث خسارت مي گردد.",  # Arabic ي, unjoined مي شود
            solution="نصب بانك خازني اتوماتيك در پست ها.",  # Arabic ك / ي
        ),
        evaluation=CommitteeEvaluation(
            status=SuggestionStatus.APPROVED,
            scrutiny="طرح در كميته بررسي گرديد.",
            description="مصوبه شماره ۱۲",
        ),
        date=ShamsiDate("1403/01/15"),
        context_title="معاونت انتقال و تجارت خارجي",
    )

    clean_suggestion = normalize_suggestion(raw_suggestion, normalizer)

    # 1. Identity and metadata preserved
    assert clean_suggestion.id == "SUG-9001"
    assert clean_suggestion.evaluation.status == SuggestionStatus.APPROVED
    assert str(clean_suggestion.date) == "1403/01/15"

    # 2. Textual fields normalized to Persian unicode standards
    assert "ي" not in clean_suggestion.content.title
    assert "ك" not in clean_suggestion.content.title
    assert "ی" in clean_suggestion.content.title
    assert "ک" in clean_suggestion.content.title

    assert clean_suggestion.content.problem is not None
    assert "ي" not in clean_suggestion.content.problem
    assert "مي باشد" not in clean_suggestion.content.problem
    assert "می‌باشد" in clean_suggestion.content.problem

    assert clean_suggestion.content.solution is not None
    assert "بانک خازنی اتوماتیک" in clean_suggestion.content.solution

    assert clean_suggestion.evaluation.scrutiny is not None
    assert "کمیته" in clean_suggestion.evaluation.scrutiny

    assert clean_suggestion.context_title is not None
    assert "خارجی" in clean_suggestion.context_title


def test_normalize_suggestion_preserves_none_fields(
    normalizer: ShekarTextNormalizer,
):
    partial_suggestion = Suggestion(
        id="SUG-9002",
        content=SuggestionContent(
            title="عنوان طرح پيشنهادي",
            problem="شرح مشكل سيستم توزيع برق",
            solution="راهكار اصلاح شبكه فشار ضعيف",
        ),
        evaluation=CommitteeEvaluation(
            status=SuggestionStatus.PENDING,
            scrutiny=None,
            description=None,
        ),
        date=None,
        context_title=None,
    )

    clean_suggestion = normalize_suggestion(partial_suggestion, normalizer)

    assert clean_suggestion.id == "SUG-9002"
    assert clean_suggestion.content.title == "عنوان طرح پیشنهادی"
    assert clean_suggestion.content.problem == "شرح مشکل سیستم توزیع برق"
    assert clean_suggestion.content.solution == "راهکار اصلاح شبکه فشار ضعیف"
    assert clean_suggestion.evaluation.scrutiny is None
    assert clean_suggestion.evaluation.description is None
    assert clean_suggestion.context_title is None
    assert clean_suggestion.date is None
