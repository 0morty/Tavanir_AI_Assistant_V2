import pytest
from src.application.dtos import SimilarSuggestionInput
from src.application.reference.similar_suggestion_reference import (
    SimilarSuggestionReference,
)
from src.domain.entities import GenerationChunk, ReferenceDetails
from src.domain.enums import SuggestionStatus


def test_similar_suggestion_reference_fields_and_description():
    ref = SimilarSuggestionReference(
        suggestion_id="SUG-101",
        status="تصویب شده",
        similarity=2.45,
        context_title="فنی و مهندسی",
    )
    assert ref.suggestion_id == "SUG-101"
    assert ref.status == "تصویب شده"
    assert ref.similarity == 2.45
    assert ref.context_title == "فنی و مهندسی"

    # Verify reranker logit domain semantics are in description
    desc = ref.description
    assert "Cross-Encoder Reranker" in desc or "بازرتبه‌بندی" in desc
    assert "Raw Logit" in desc or "لاجیت خام" in desc
    assert "Sigmoid" in desc or "سیگموئید" in desc
    assert "کمتر از صفر" in desc or "مثبت" in desc


def test_fluent_text_raises_not_implemented_error():
    ref = SimilarSuggestionReference(
        suggestion_id="101",
        status="اجرا شده",
        similarity=1.85,
        context_title="توزیع برق",
    )
    with pytest.raises(NotImplementedError):
        ref.fluent_text()


def test_reference_details_extraction():
    ref = SimilarSuggestionReference(
        suggestion_id="101",
        status="اجرا شده",
        similarity=0.95,
        context_title="بهره‌برداری",
    )
    details = ReferenceDetails.from_instance(ref)
    property_names = [name for name, _ in details.properties]
    assert "suggestion_id" in property_names
    assert "status" in property_names
    assert "similarity" in property_names
    assert "context_title" in property_names

    # If context_title is None, it must be excluded per ReferenceDetails rules
    ref_none_ctx = SimilarSuggestionReference(
        suggestion_id="101",
        status="اجرا شده",
        similarity=0.95,
        context_title=None,
    )
    details_none = ReferenceDetails.from_instance(ref_none_ctx)
    names_none = [name for name, _ in details_none.properties]
    assert "context_title" not in names_none


def test_dto_to_generation_chunk_adapter_automatic_reference():
    dto = SimilarSuggestionInput(
        id="SUG-999",
        status=SuggestionStatus.EXECUTED,
        title="کاهش تلفات ترانسفورماتور",
        problem="گرمای بیش از حد هسته ترانس",
        solution="بهبود گردش روغن خنک‌کننده",
        similarity=3.12,
        context_title="تجهیزات پست",
    )

    chunk = dto.to_generation_chunk(index=2)
    assert isinstance(chunk, GenerationChunk)
    assert chunk.chunk_id == "SUG-999"

    # Content ingredients
    assert "[پیشنهاد مشابه 2]" in chunk.content
    assert "کاهش تلفات ترانسفورماتور" in chunk.content
    assert "گرمای بیش از حد هسته ترانس" in chunk.content
    assert "بهبود گردش روغن خنک‌کننده" in chunk.content

    # Reference attached
    assert isinstance(chunk.reference, SimilarSuggestionReference)
    assert chunk.reference.suggestion_id == "SUG-999"
    assert chunk.reference.status == SuggestionStatus.EXECUTED.title_fa
    assert chunk.reference.similarity == 3.12
    assert chunk.reference.context_title == "تجهیزات پست"


def test_dto_to_generation_chunk_preserves_custom_reference():
    custom_ref = SimilarSuggestionReference(
        suggestion_id="CUSTOM-1",
        status="سفارشی",
        similarity=5.0,
    )
    dto = SimilarSuggestionInput(
        id="SUG-1",
        status=SuggestionStatus.APPROVED,
        title="عنوان تستی",
        problem="مسئله تستی",
        solution="راهکار تستی",
        similarity=1.0,
        reference=custom_ref,
    )
    chunk = dto.to_generation_chunk(index=1)
    assert chunk.reference is custom_ref
