import uuid
from dataclasses import replace

import pytest

from src.domain.entities import (
    CommitteeEvaluation,
    SecretariatEvaluation,
    ShamsiDate,
    Suggestion,
    SuggestionContent,
)
from src.domain.enums import (
    ChunkStatus,
    CommitteeScrutiny,
    SecretariatScrutiny,
    SuggestionChunkType,
    SuggestionStatus,
)
from src.domain.exceptions import SuggestionChunkingError
from src.infrastructure.services.chunkers import FieldAwareSuggestionChunker


@pytest.fixture
def chunker() -> FieldAwareSuggestionChunker:
    return FieldAwareSuggestionChunker(
        max_chunk_chars=500,  # small threshold for testability
        overlap_chars=50,
        min_chunk_chars=5,
    )


@pytest.fixture
def full_suggestion() -> Suggestion:
    return Suggestion(
        id="SUG-2001",
        content=SuggestionContent(
            title="نصب کلیدهای اتوماتیک قدرت",
            problem="افت ولتاژ مکرر در پست‌های فشار قوی به دلیل فرسودگی تجهیزات قطع و وصل قدیمی.",
            solution="جایگزینی کلیدهای گازی قدیمی با بریکرهای نوین مجهز به سنسورهای پایش آنلاین وضعیت گاز SF6.",
        ),
        evaluation=CommitteeEvaluation(
            status=SuggestionStatus.APPROVED,
            scrutiny=CommitteeScrutiny.APPROVED,
            description="مصوب جلسه شماره ۴۵ کارگروه نظام پیشنهادات شرکت توانیر.",
            scrutiny_id=0,
        ),
        date=ShamsiDate("1402/10/12"),
        context_title="معاونت انتقال و تجارت خارجی",
        secretariat_evaluation=SecretariatEvaluation(
            scrutiny=SecretariatScrutiny.REFER_TO_COMMITTEE,
            comment="تایید مدارک و ارجاع به کمیته انتقال.",
            scrutiny_id=3,
        ),
    )


@pytest.mark.asyncio
async def test_full_suggestion_produces_4_chunks(
    chunker: FieldAwareSuggestionChunker, full_suggestion: Suggestion
):
    chunks = await chunker.chunk(full_suggestion)

    assert len(chunks) == 4

    types = [c.metadata.chunk_type for c in chunks]
    assert types == [
        SuggestionChunkType.TITLE,
        SuggestionChunkType.PROBLEM,
        SuggestionChunkType.SOLUTION,
        SuggestionChunkType.EVALUATION,
    ]

    # Invariants for all chunks
    chunk_ids = set()
    for c in chunks:
        assert c.parent_id == "SUG-2001"
        assert c.parent_content is None
        assert c.chunk_status == ChunkStatus.ACTIVE
        assert c.metadata.status == SuggestionStatus.APPROVED
        assert c.metadata.context_title == "معاونت انتقال و تجارت خارجی"
        assert str(c.metadata.date) == "1402/10/12"
        assert c.metadata.sub_index == 0
        assert c.metadata.committee_scrutiny == CommitteeScrutiny.APPROVED
        assert c.metadata.committee_scrutiny_id == 0
        assert c.metadata.secretariat_scrutiny == SecretariatScrutiny.REFER_TO_COMMITTEE
        assert c.metadata.secretariat_scrutiny_id == 3
        # Valid UUIDv4 and unique
        parsed_uuid = uuid.UUID(c.chunk_id, version=4)
        assert parsed_uuid is not None
        chunk_ids.add(c.chunk_id)

    assert len(chunk_ids) == 4


@pytest.mark.asyncio
async def test_strict_field_isolation(
    chunker: FieldAwareSuggestionChunker, full_suggestion: Suggestion
):
    chunks = await chunker.chunk(full_suggestion)

    title_chunk = next(
        c for c in chunks if c.metadata.chunk_type == SuggestionChunkType.TITLE
    )
    problem_chunk = next(
        c for c in chunks if c.metadata.chunk_type == SuggestionChunkType.PROBLEM
    )
    solution_chunk = next(
        c for c in chunks if c.metadata.chunk_type == SuggestionChunkType.SOLUTION
    )

    # Title chunk contains department anchor
    assert (
        "حوزه: معاونت انتقال و تجارت خارجی | عنوان: نصب کلیدهای اتوماتیک قدرت"
        in title_chunk.content
    )

    # Problem and Solution MUST NOT contain title or department prefixes
    assert "حوزه:" not in problem_chunk.content
    assert "عنوان:" not in problem_chunk.content
    assert problem_chunk.content == full_suggestion.content.problem

    assert "حوزه:" not in solution_chunk.content
    assert "عنوان:" not in solution_chunk.content
    assert solution_chunk.content == full_suggestion.content.solution


@pytest.mark.asyncio
async def test_rule_of_omission_for_missing_fields(
    chunker: FieldAwareSuggestionChunker,
):
    suggestion = Suggestion(
        id="SUG-3001",
        content=SuggestionContent(
            title="بهینه‌سازی سیستم روشنایی ساختمان",
            problem="افت ولتاژ در طبقات اداری به دلیل بار روشنایی",
            solution="تعویض لامپ‌های فلورسنت با پنل‌های ال‌ای‌دی کم‌مصرف هوشمند.",
        ),
        evaluation=CommitteeEvaluation(
            status=SuggestionStatus.PENDING,
            scrutiny=None,  # Missing
            description=None,  # Missing
        ),
        date=None,
        context_title=None,
    )

    chunks = await chunker.chunk(suggestion)

    assert len(chunks) == 3
    types = [c.metadata.chunk_type for c in chunks]
    assert types == [
        SuggestionChunkType.TITLE,
        SuggestionChunkType.PROBLEM,
        SuggestionChunkType.SOLUTION,
    ]

    # Title without context_title has no separator
    assert chunks[0].content == "بهینه‌سازی سیستم روشنایی ساختمان"
    assert chunks[0].metadata.context_title is None


@pytest.mark.asyncio
async def test_noise_and_placeholder_filtering(
    chunker: FieldAwareSuggestionChunker,
):
    suggestion = Suggestion(
        id="SUG-4001",
        content=SuggestionContent(
            title="مدیریت بار پیک مصرف تابستان",
            problem="بار مصرفی در ساعات اوج تابستان شبکه را ناپایدار می‌کند.",
            solution="اجرای طرح پاسخگویی بار با هماهنگی صنایع همکار در ساعات اوج بار شبکه.",
        ),
        evaluation=CommitteeEvaluation(
            status=SuggestionStatus.NOT_ACCEPTED,
            scrutiny=None,
            description="...",  # Too short (< 5 chars)
        ),
        date=None,
        context_title="   ",  # Blank context title
    )

    chunks = await chunker.chunk(suggestion)

    # Evaluation should be omitted due to noise/length in optional fields
    assert len(chunks) == 3
    types = [c.metadata.chunk_type for c in chunks]
    assert types == [
        SuggestionChunkType.TITLE,
        SuggestionChunkType.PROBLEM,
        SuggestionChunkType.SOLUTION,
    ]


@pytest.mark.asyncio
async def test_evaluation_partial_formatting(
    chunker: FieldAwareSuggestionChunker,
):
    # Case A: Only Secretariat Substantive Comment
    sugg_a = Suggestion(
        id="SUG-5001",
        content=SuggestionContent(
            title="طرح تست الف",
            problem="شرح نقص فنی ترانس",
            solution="تعویض قطعات فرسوده با نو",
        ),
        evaluation=CommitteeEvaluation(
            status=SuggestionStatus.REJECTED,
            scrutiny=CommitteeScrutiny.REJECTED,
            description=None,
        ),
        secretariat_evaluation=SecretariatEvaluation(
            scrutiny=SecretariatScrutiny.AUTO_REJECTED_EXPERT,
            comment="رد خودکار به دلیل عدم ارائه مدارک تکمیلی در مهلت مقرر کارشناسی.",
        ),
        date=None,
        context_title=None,
    )
    chunks_a = await chunker.chunk(sugg_a)
    eval_a = next(
        c for c in chunks_a if c.metadata.chunk_type == SuggestionChunkType.EVALUATION
    )
    assert "ارزیابی دبیرخانه: رد خودکار به دلیل کارشناسی" in eval_a.content
    assert (
        "نظر دبیرخانه: رد خودکار به دلیل عدم ارائه مدارک تکمیلی در مهلت مقرر کارشناسی."
        in eval_a.content
    )
    assert "بررسی کمیته:" not in eval_a.content
    assert "توضیحات مصوبه:" not in eval_a.content

    # Case B: Only Committee Substantive Description
    sugg_b = Suggestion(
        id="SUG-5002",
        content=SuggestionContent(
            title="طرح تست ب",
            problem="افت بازدهی حرارتی توربین",
            solution="شستشوی پره‌های کمپرسور",
        ),
        evaluation=CommitteeEvaluation(
            status=SuggestionStatus.EXECUTED,
            scrutiny=CommitteeScrutiny.ACCEPTED_AS_EXECUTED_SUGGESTION,
            description="پروژه در پست شهید رجایی با موفقیت اجرا شد.",
        ),
        date=None,
        context_title=None,
    )
    chunks_b = await chunker.chunk(sugg_b)
    eval_b = next(
        c for c in chunks_b if c.metadata.chunk_type == SuggestionChunkType.EVALUATION
    )
    assert eval_b.content == (
        "بررسی کمیته: پذیرفته شده به عنوان پیشنهاد اجراشده\n"
        "توضیحات مصوبه: پروژه در پست شهید رجایی با موفقیت اجرا شد."
    )
    assert "ارزیابی دبیرخانه:" not in eval_b.content


@pytest.mark.asyncio
async def test_substantive_commentary_guard_edge_cases(
    chunker: FieldAwareSuggestionChunker,
):
    # 1. Enums present, but both comments empty -> 0 evaluation chunks
    sugg_no_comments = Suggestion(
        id="SUG-GUARD-1",
        content=SuggestionContent(
            title="طرح بدون توضیحات تکمیلی",
            problem="شرح مشکل معتبر سیستم برق",
            solution="راهکار اجرایی معتبر مهندسی",
        ),
        evaluation=CommitteeEvaluation(
            status=SuggestionStatus.APPROVED,
            scrutiny=CommitteeScrutiny.APPROVED,
            description=None,
        ),
        secretariat_evaluation=SecretariatEvaluation(
            scrutiny=SecretariatScrutiny.REFER_TO_COMMITTEE,
            comment=None,
        ),
        date=None,
        context_title=None,
    )
    chunks = await chunker.chunk(sugg_no_comments)
    eval_chunks = [
        c for c in chunks if c.metadata.chunk_type == SuggestionChunkType.EVALUATION
    ]
    assert len(eval_chunks) == 0
    assert len(chunks) == 3

    # 2. Short comments under 15 chars -> 0 evaluation chunks
    sugg_short = Suggestion(
        id="SUG-GUARD-2",
        content=SuggestionContent(
            title="طرح با نظر خیلی کوتاه",
            problem="شرح مشکل معتبر سیستم برق",
            solution="راهکار اجرایی معتبر مهندسی",
        ),
        evaluation=CommitteeEvaluation(
            status=SuggestionStatus.REJECTED,
            scrutiny=CommitteeScrutiny.REJECTED,
            description="رد شد",  # < 15 chars
        ),
        secretariat_evaluation=SecretariatEvaluation(
            scrutiny=SecretariatScrutiny.OUT_OF_FRAMEWORK,
            comment="بررسی شد",  # < 15 chars
        ),
        date=None,
        context_title=None,
    )
    chunks_short = await chunker.chunk(sugg_short)
    eval_short = [
        c
        for c in chunks_short
        if c.metadata.chunk_type == SuggestionChunkType.EVALUATION
    ]
    assert len(eval_short) == 0

    # 3. Both comments substantive -> 1 consolidated evaluation chunk
    sugg_both = Suggestion(
        id="SUG-GUARD-3",
        content=SuggestionContent(
            title="طرح با دو نظر تفصیلی",
            problem="شرح مشکل معتبر سیستم برق",
            solution="راهکار اجرایی معتبر مهندسی",
        ),
        evaluation=CommitteeEvaluation(
            status=SuggestionStatus.APPROVED,
            scrutiny=CommitteeScrutiny.APPROVED,
            description="مصوب جلسه کارگروه با اکثریت آرا و تخصیص منابع مالی لازم.",
        ),
        secretariat_evaluation=SecretariatEvaluation(
            scrutiny=SecretariatScrutiny.REFER_TO_COMMITTEE,
            comment="مدارک اولیه بررسی و جهت تصمیم‌گیری نهایی به کمیته ارجاع گردید.",
        ),
        date=None,
        context_title=None,
    )
    chunks_both = await chunker.chunk(sugg_both)
    eval_both = [
        c
        for c in chunks_both
        if c.metadata.chunk_type == SuggestionChunkType.EVALUATION
    ]
    assert len(eval_both) == 1
    content = eval_both[0].content
    assert "ارزیابی دبیرخانه: ارجاع به کمیته" in content
    assert (
        "نظر دبیرخانه: مدارک اولیه بررسی و جهت تصمیم‌گیری نهایی به کمیته ارجاع گردید."
        in content
    )
    assert "بررسی کمیته: تایید" in content
    assert (
        "توضیحات مصوبه: مصوب جلسه کارگروه با اکثریت آرا و تخصیص منابع مالی لازم."
        in content
    )

    # 4. Substantive comment with unmapped/None scrutiny -> Emits comment cleanly
    sugg_none_scrutiny = Suggestion(
        id="SUG-GUARD-4",
        content=SuggestionContent(
            title="طرح بدون عنوان وضعیت",
            problem="شرح مشکل معتبر سیستم برق",
            solution="راهکار اجرایی معتبر مهندسی",
        ),
        evaluation=CommitteeEvaluation(
            status=SuggestionStatus.PENDING,
            scrutiny=None,
            description="توضیحات کارشناسی کامل پیرامون ابعاد مختلف این پیشنهاد ثبت شده است.",
        ),
        secretariat_evaluation=None,
        date=None,
        context_title=None,
    )
    chunks_none = await chunker.chunk(sugg_none_scrutiny)
    eval_none = next(
        c
        for c in chunks_none
        if c.metadata.chunk_type == SuggestionChunkType.EVALUATION
    )
    assert (
        eval_none.content
        == "توضیحات مصوبه: توضیحات کارشناسی کامل پیرامون ابعاد مختلف این پیشنهاد ثبت شده است."
    )
    assert "بررسی کمیته:" not in eval_none.content


@pytest.mark.asyncio
async def test_essay_recursive_splitting_preserves_sub_indexes(
    chunker: FieldAwareSuggestionChunker,
):
    paragraph_1 = "مرحله اول این است که سنسورهای پایش دما روی تمامی اتصالات فاز نصب شوند تا در صورت بالا رفتن دما اخطار صادر شود."
    paragraph_2 = "مرحله دوم شامل اتصال بی‌سیم این سنسورها به شبکه مخابراتی دیسپاچینگ منطقه‌ای از طریق پروتکل امن ارتباطی می‌باشد."
    paragraph_3 = "مرحله سوم کالیبراسیون و صحت‌سنجی اطلاعات دریافتی با مقادیر اندازه‌گیری شده میدانی توسط کارشناسان مربوطه است."
    paragraph_4 = "مرحله نهایی استقرار سامانه هشدار زودهنگام و اتصال آن به سیستم اعلان خرابی مرکزی جهت پیشگیری از سوختن ترانسفورماتور است."
    paragraph_5 = "این فرآیند در نهایت موجب کاهش هزینه‌های تعمیرات و نگهداری دوره‌ای و جلوگیری از قطعی‌های ناخواسته در ساعات اوج بار مصرف برق در کل شبکه خواهد شد."

    long_solution = f"{paragraph_1}\n\n{paragraph_2}\n\n{paragraph_3}\n\n{paragraph_4}\n\n{paragraph_5}"
    assert len(long_solution) > 500

    suggestion = Suggestion(
        id="SUG-6001",
        content=SuggestionContent(
            title="طرح پایش ترانسفورماتورها",
            problem="مشکل حرارتی",
            solution=long_solution,
        ),
        evaluation=CommitteeEvaluation(
            status=SuggestionStatus.PENDING, scrutiny=None, description=None
        ),
        date=None,
        context_title=None,
    )

    chunks = await chunker.chunk(suggestion)

    solution_chunks = [
        c for c in chunks if c.metadata.chunk_type == SuggestionChunkType.SOLUTION
    ]
    assert len(solution_chunks) > 1

    # Verify sequential sub_indexes and strict field isolation
    for idx, sc in enumerate(solution_chunks):
        assert sc.metadata.sub_index == idx
        assert sc.parent_id == "SUG-6001"
        assert "حوزه:" not in sc.content
        assert "عنوان:" not in sc.content
        assert len(sc.content) <= 500


@pytest.mark.asyncio
async def test_invalid_suggestion_raises_error(
    chunker: FieldAwareSuggestionChunker,
):
    # Empty ID
    with pytest.raises(SuggestionChunkingError, match="valid non-empty id"):
        await chunker.chunk(
            Suggestion(
                id="",
                content=SuggestionContent(
                    title="عنوان معتبر",
                    problem="مشکل معتبر تستی",
                    solution="راهکار معتبر تستی",
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.PENDING, scrutiny=None, description=None
                ),
                date=None,
                context_title=None,
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["problem", "solution"])
async def test_inline_images_are_excluded_from_vectors_and_preserved_in_source(
    chunker: FieldAwareSuggestionChunker, full_suggestion: Suggestion, field: str
):
    before = "نصب تجهیزات پایش شبکه برای کاهش تلفات."
    after = "اندازه‌گیری نتایج پس از اجرای طرح."
    image = "data:image/png;base64," + "A" * 10000
    original = before + "\n" + image + "\n" + after
    suggestion = replace(
        full_suggestion, content=replace(full_suggestion.content, **{field: original})
    )

    chunks = await chunker.chunk(suggestion)
    field_chunks = [c for c in chunks if c.metadata.chunk_type.value == field]

    assert [c.content for c in field_chunks] == [before + "\n\n" + after]
    assert getattr(suggestion.content, field) == original
    assert all("data:image" not in c.content and image not in c.content for c in chunks)
    assert field_chunks[0].parent_id == suggestion.id
    assert field_chunks[0].metadata.sub_index == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["problem", "solution"])
async def test_image_only_mandatory_fields_are_rejected(
    chunker: FieldAwareSuggestionChunker, full_suggestion: Suggestion, field: str
):
    original = "data:image/png;base64," + "A" * 10000
    suggestion = replace(
        full_suggestion, content=replace(full_suggestion.content, **{field: original})
    )

    with pytest.raises(SuggestionChunkingError, match="no substantive text"):
        await chunker.chunk(suggestion)
    assert getattr(suggestion.content, field) == original
