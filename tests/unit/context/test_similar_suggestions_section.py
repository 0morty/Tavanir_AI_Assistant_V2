from src.application.context.sections.similar_suggestions_section import (
    SimilarSuggestionsSection,
)
from src.application.dtos import SectionProcessingResult, SimilarSuggestionInput
from src.application.reference.similar_suggestion_reference import (
    SimilarSuggestionReference,
)
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import GenerationChunk
from src.domain.enums import SuggestionStatus


class FakeCharTokenizer(Tokenizer):
    """Simple 1-token-per-char tokenizer for deterministic testing."""

    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        return [(i, (i, i + 1)) for i in range(len(text))]

    def count_tokens(self, text: str) -> int:
        return len(text)


def _make_item(
    item_id: str,
    title: str = "بهینه‌سازی شبکه",
    problem: str = "تلفات شبکه در ساعات پیک",
    solution: str = "نصب خازن‌های اتوماتیک",
    similarity: float = 0.95,
    status: SuggestionStatus = SuggestionStatus.EXECUTED,
) -> SimilarSuggestionInput:
    return SimilarSuggestionInput(
        id=item_id,
        status=status,
        title=title,
        problem=problem,
        solution=solution,
        similarity=similarity,
    )


def test_render_includes_all_when_budget_unlimited():
    tok = FakeCharTokenizer()
    s1 = _make_item("101", similarity=0.98)
    s2 = _make_item("102", similarity=0.91)
    section = SimilarSuggestionsSection([s1, s2])
    rendered = section.render()

    assert "## سوابق پیشنهادات مشابه بازیابی‌شده:" in rendered
    assert "[پیشنهاد مشابه 1] کد پیشنهاد: 101" in rendered
    assert "[پیشنهاد مشابه 2] کد پیشنهاد: 102" in rendered
    assert "0.98" in rendered
    assert "0.91" in rendered


def test_header_pre_context_persian_text():
    section = SimilarSuggestionsSection([_make_item("1")])
    assert section.pre_context == "## سوابق پیشنهادات مشابه بازیابی‌شده:"
    assert section.section_type == "SIMILAR-SUGGESTIONS"


def test_ignore_preserves_strict_rank_order():
    tok = FakeCharTokenizer()
    s1 = _make_item("101", problem="الف" * 20)
    s2 = _make_item("102", problem="ب" * 20)
    s3 = _make_item("103", problem="ج" * 20)
    section = SimilarSuggestionsSection([s1, s2, s3])

    pre = section.pre_context
    pre_tokens = tok.count_tokens(pre)
    frame_sep_tokens = tok.count_tokens(section.separator)

    item1_tokens = tok.count_tokens(section.item_content(s1))
    item2_tokens = tok.count_tokens(section.item_content(s2))
    sep_tokens = tok.count_tokens(section.item_separator)

    # Budget fits s1 and s2, but NOT s3
    capacity = pre_tokens + frame_sep_tokens + item1_tokens + sep_tokens + item2_tokens
    fitted = section.ignore(section.render(), capacity, tokenizer=tok)

    assert "101" in fitted
    assert "102" in fitted
    assert "103" not in fitted


def test_ignore_suppresses_header_when_zero_items_fit():
    tok = FakeCharTokenizer()
    s1 = _make_item("101", problem="الف" * 100)
    section = SimilarSuggestionsSection([s1])

    # Capacity only enough for header, but not enough for s1
    pre = section.pre_context
    pre_tokens = tok.count_tokens(pre)
    fitted = section.ignore(section.render(), pre_tokens + 5, tokenizer=tok)

    # Whole section must be suppressed to empty string
    assert fitted == ""


def test_truncate_neutralized_to_empty_string():
    tok = FakeCharTokenizer()
    section = SimilarSuggestionsSection([_make_item("101")])
    assert section.truncate(section.render(), 50, tokenizer=tok) == ""


def test_similar_suggestions_section_items_are_generation_chunks():
    s1 = _make_item("101", similarity=0.98)
    s2 = _make_item("102", similarity=0.91)
    section = SimilarSuggestionsSection([s1, s2])

    assert len(section.items) == 2
    for chunk in section.items:
        assert isinstance(chunk, GenerationChunk)
        assert isinstance(chunk.reference, SimilarSuggestionReference)

    assert section.items[0].chunk_id == "101"
    assert section.items[0].reference.similarity == 0.98
    assert section.items[1].chunk_id == "102"
    assert section.items[1].reference.similarity == 0.91



def test_similar_suggestions_section_processing_result_support():
    tok = FakeCharTokenizer()
    s1 = _make_item("101", problem="الف" * 20)
    section = SimilarSuggestionsSection([s1])

    prep = section.prepare()
    assert isinstance(prep, SectionProcessingResult)
    assert len(prep.items) == 1

    # Call ignore with SectionProcessingResult
    res = section.ignore(prep, 500, tokenizer=tok)
    assert isinstance(res, SectionProcessingResult)
    assert len(res.items) == 1
    assert "101" in res.content

