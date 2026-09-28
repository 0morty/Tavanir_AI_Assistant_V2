from src.application.context.sections.similar_suggestions_section import (
    SimilarSuggestionsSection,
)
from src.domain.context.tokenizer import Tokenizer

from src.application.dtos import SimilarSuggestionInput
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
    s1 = _make_item("101", similarity=0.98)
    s2 = _make_item("102", similarity=0.91)
    section = SimilarSuggestionsSection([s1, s2])
    rendered = section.render()

    assert "## سوابق پیشنهادات مشابه بازیابی‌شده:" in rendered
    assert "Unique ID: [similar 001]" in rendered
    assert "Unique ID: [similar 002]" in rendered
    assert "کد پیشنهاد: 101" not in rendered
    assert "[پیشنهاد مشابه 1]" not in rendered
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

    prepared = section.prepare()
    item1_tokens = tok.count_tokens(prepared.item_bodies[0])
    item2_tokens = tok.count_tokens(prepared.item_bodies[1])
    sep_tokens = tok.count_tokens(section.item_separator)

    # Budget fits s1 and s2, but not s3.
    capacity = pre_tokens + frame_sep_tokens + item1_tokens + sep_tokens + item2_tokens
    fitted = section.ignore(prepared, capacity, tokenizer=tok)

    assert fitted.citation_ids == ("[similar 001]", "[similar 002]")
    assert "[similar 003]" not in fitted.content
    assert [item.id for item in fitted.items] == ["101", "102"]


def test_ignore_suppresses_header_when_zero_items_fit():
    tok = FakeCharTokenizer()
    s1 = _make_item("101", problem="الف" * 100)
    section = SimilarSuggestionsSection([s1])

    # Capacity only enough for header, but not enough for s1
    pre = section.pre_context
    pre_tokens = tok.count_tokens(pre)
    fitted = section.ignore(section.prepare(), pre_tokens + 5, tokenizer=tok)

    # Whole section must be suppressed to empty string.
    assert fitted.content == ""
    assert fitted.citation_ids == ()


def test_truncate_keeps_whole_collection_for_ignore_fallback():
    tok = FakeCharTokenizer()
    section = SimilarSuggestionsSection([_make_item("101")])
    prepared = section.prepare()
    assert section.truncate(prepared, 50, tokenizer=tok) is prepared
