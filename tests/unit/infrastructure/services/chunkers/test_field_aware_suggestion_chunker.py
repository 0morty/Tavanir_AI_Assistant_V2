import uuid

import pytest

from src.domain.entities import (
    CommitteeEvaluation,
    ShamsiDate,
    Suggestion,
    SuggestionContent,
)
from src.domain.enums import ChunkStatus, SuggestionChunkType, SuggestionStatus
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
            scrutiny="طرح پیشنهادی در کارگروه تخصصی انتقال بررسی و توجیه فنی و اقتصادی آن تأیید شد.",
            description="مصوب جلسه شماره ۴۵ کارگروه نظام پیشنهادات شرکت توانیر.",
        ),
        date=ShamsiDate("1402/10/12"),
        context_title="معاونت انتقال و تجارت خارجی",
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
            scrutiny="ندارد",  # Noise placeholder
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
    # Case A: Only Scrutiny
    sugg_a = Suggestion(
        id="SUG-5001",
        content=SuggestionContent(
            title="طرح تست الف",
            problem="شرح نقص فنی ترانس",
            solution="تعویض قطعات فرسوده با نو",
        ),
        evaluation=CommitteeEvaluation(
            status=SuggestionStatus.REJECTED,
            scrutiny="فاقد توجیه اقتصادی و خارج از اولویت‌های شرکت.",
            description=None,
        ),
        date=None,
        context_title=None,
    )
    chunks_a = await chunker.chunk(sugg_a)
    eval_a = next(
        c for c in chunks_a if c.metadata.chunk_type == SuggestionChunkType.EVALUATION
    )
    assert eval_a.content == "بررسی کمیته: فاقد توجیه اقتصادی و خارج از اولویت‌های شرکت."
    assert "توضیحات مصوبه:" not in eval_a.content

    # Case B: Only Description
    sugg_b = Suggestion(
        id="SUG-5002",
        content=SuggestionContent(
            title="طرح تست ب",
            problem="افت بازدهی حرارتی توربین",
            solution="شستشوی پره‌های کمپرسور",
        ),
        evaluation=CommitteeEvaluation(
            status=SuggestionStatus.EXECUTED,
            scrutiny=None,
            description="پروژه در پست شهید رجایی با موفقیت اجرا شد.",
        ),
        date=None,
        context_title=None,
    )
    chunks_b = await chunker.chunk(sugg_b)
    eval_b = next(
        c for c in chunks_b if c.metadata.chunk_type == SuggestionChunkType.EVALUATION
    )
    assert eval_b.content == "توضیحات مصوبه: پروژه در پست شهید رجایی با موفقیت اجرا شد."
    assert "بررسی کمیته:" not in eval_b.content


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
