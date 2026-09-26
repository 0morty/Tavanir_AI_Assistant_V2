from typing import Any, cast

import pytest
from dependency_injector import providers
from src.application.context.allocation import (
    CapacityAllocator,
    DemandAllocator,
    RedistributionAllocator,
)
from src.application.context.context_builder import ContextBuilder
from src.application.context.overflow_strategy_dispatcher import (
    OverflowStrategyDispatcher,
)
from src.application.prompt.suggestion_analysis_prompt_config import (
    SuggestionAnalysisPromptConfig,
)
from src.application.prompt.suggestion_prompt_preparer import (
    SuggestionPromptPreparer,
)
from src.containers import Container
from src.domain.context.tokenizer import Tokenizer

from src.application.dtos import (
    CurrentSuggestionInput,
    GenerationInput,
    RegulationInput,
    SimilarSuggestionInput,
)
from src.application.exceptions import (
    DuplicateEvidenceIdError,
    InsufficientEvidenceBudgetError,
    PromptBudgetExceededError,
)
from src.application.interfaces import ISuggestionPromptPreparer
from src.domain.enums import SuggestionStatus
from src.domain.exceptions import InvalidSuggestionContentError


class FakeTokenizer(Tokenizer):
    """Deterministic character-based tokenizer for testing token budget calculations."""

    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        return [(i, (i, i + 1)) for i in range(len(text))]

    def count_tokens(self, text: str) -> int:
        return len(text)


def _make_current(
    title: str = "طرح هوشمندسازی شبکه توزیع",
    problem: str = "فرسودگی شدید تجهیزات و اتلاف انرژی بالا",
    solution: str = "نصب رله‌های میکروپروسسوری پیشرفته",
    context_title: str | None = "فنی و مهندسی",
) -> CurrentSuggestionInput:
    return CurrentSuggestionInput(
        title=title,
        problem=problem,
        solution=solution,
        context_title=context_title,
    )


def _make_similar(
    sug_id: str,
    title: str = "بهینه‌سازی دیسپاچینگ",
    problem: str = "عدم تعادل بار در ساعات اوج مصرف",
    solution: str = "استفاده از الگوریتم‌های هوش مصنوعی",
    similarity: float = 0.92,
    status: SuggestionStatus = SuggestionStatus.EXECUTED,
    context_title: str | None = "دیسپاچینگ",
) -> SimilarSuggestionInput:
    return SimilarSuggestionInput(
        id=sug_id,
        status=status,
        title=title,
        problem=problem,
        solution=solution,
        similarity=similarity,
        context_title=context_title,
    )


def _make_preparer(
    tokenizer: FakeTokenizer | None = None,
    config: SuggestionAnalysisPromptConfig | None = None,
) -> tuple[SuggestionPromptPreparer, FakeTokenizer]:
    tok = FakeTokenizer() if tokenizer is None else tokenizer
    conf = SuggestionAnalysisPromptConfig() if config is None else config
    dispatcher = OverflowStrategyDispatcher()
    allocator = CapacityAllocator(DemandAllocator(), RedistributionAllocator())
    ctx_builder = ContextBuilder(
        tokenizer=tok,
        capacity_allocator=allocator,
        dispatcher=dispatcher,
    )
    preparer = SuggestionPromptPreparer(
        context_builder=ctx_builder,
        tokenizer=tok,
        config=conf,
    )
    return preparer, tok


# ==============================================================================
# 6.1 Domain DTO Validation & RFC 6901 Pointer Tests
# ==============================================================================


def test_current_suggestion_empty_title():
    with pytest.raises(InvalidSuggestionContentError) as exc_info:
        CurrentSuggestionInput(
            title="",
            problem="مسئله دارای متن معتبر است",
            solution="راهکار دارای متن معتبر است",
        )
    assert exc_info.value.pointer == "/data/currentTitle"
    assert exc_info.value.field_name == "title"


def test_current_suggestion_empty_problem():
    with pytest.raises(InvalidSuggestionContentError) as exc_info:
        CurrentSuggestionInput(
            title="عنوان معتبر",
            problem="   ",
            solution="راهکار دارای متن معتبر است",
        )
    assert exc_info.value.pointer == "/data/currentProblem"
    assert exc_info.value.field_name == "problem"


def test_current_suggestion_empty_solution():
    with pytest.raises(InvalidSuggestionContentError) as exc_info:
        CurrentSuggestionInput(
            title="عنوان معتبر",
            problem="مسئله دارای متن معتبر است",
            solution="",
        )
    assert exc_info.value.pointer == "/data/currentSolution"
    assert exc_info.value.field_name == "solution"


def test_current_suggestion_noise_placeholder():
    with pytest.raises(InvalidSuggestionContentError) as exc_info:
        CurrentSuggestionInput(
            title="عنوان معتبر",
            problem="ندارد",
            solution="راهکار دارای متن معتبر است",
        )
    assert exc_info.value.pointer == "/data/currentProblem"
    assert "substantive content" in str(exc_info.value)


def test_similar_suggestion_validation_with_index():
    item = SimilarSuggestionInput(
        id="sug-123",
        status=SuggestionStatus.EXECUTED,
        title="عنوان معتبر",
        problem="کم",  # < 5 chars
        solution="راهکار معتبر با متن کافی",
        similarity=0.88,
    )
    with pytest.raises(InvalidSuggestionContentError) as exc_info:
        item.validate_with_index(2)
    assert exc_info.value.pointer == "/data/similarSuggestions/2/problem"
    assert exc_info.value.field_name == "problem"


def test_similar_suggestion_empty_id():
    item = SimilarSuggestionInput(
        id="",
        status=SuggestionStatus.EXECUTED,
        title="عنوان معتبر",
        problem="مسئله معتبر با متن کافی",
        solution="راهکار معتبر با متن کافی",
        similarity=0.88,
    )
    with pytest.raises(InvalidSuggestionContentError) as exc_info:
        item.validate_with_index(0)
    assert exc_info.value.pointer == "/data/similarSuggestions/0/id"
    assert exc_info.value.field_name == "id"


def test_duplicate_similar_suggestion_id():
    sug1 = _make_similar("duplicate-id-1")
    sug2 = _make_similar("unique-id")
    sug3 = _make_similar("duplicate-id-1")

    with pytest.raises(DuplicateEvidenceIdError) as exc_info:
        GenerationInput(
            current_suggestion=_make_current(),
            similar_suggestions=[sug1, sug2, sug3],
        )
    assert exc_info.value.pointer == "/data/similarSuggestions/2/id"
    assert exc_info.value.field_name == "id"


def test_empty_similar_suggestions_is_allowed():
    gen_input = GenerationInput(
        current_suggestion=_make_current(),
        similar_suggestions=[],
    )
    assert len(gen_input.similar_suggestions) == 0


def test_regulations_default_and_populated():
    reg = RegulationInput(
        id="reg-1",
        title="قانون بهبود مصرف انرژی",
        content="ماده یک: الزام به رعایت الگوهای بهینه‌سازی",
        citation="ماده ۱ بند ب",
    )
    gen_input = GenerationInput(
        current_suggestion=_make_current(),
        regulations=[reg],
    )
    assert len(gen_input.regulations) == 1
    assert gen_input.regulations[0].id == "reg-1"


def test_current_suggestion_non_string_field():
    with pytest.raises(InvalidSuggestionContentError) as exc_info:
        CurrentSuggestionInput(
            title=cast(Any, 12345),
            problem="مسئله دارای متن معتبر است",
            solution="راهکار دارای متن معتبر است",
        )
    assert exc_info.value.pointer == "/data/currentTitle"


def test_similar_suggestion_invalid_similarity_negative():
    item = _make_similar("sug-1", similarity=-0.1)
    with pytest.raises(InvalidSuggestionContentError) as exc_info:
        item.validate_with_index(0)
    assert exc_info.value.pointer == "/data/similarSuggestions/0/similarity"
    assert exc_info.value.field_name == "similarity"


def test_similar_suggestion_invalid_similarity_greater_than_one():
    item = _make_similar("sug-1", similarity=1.05)
    with pytest.raises(InvalidSuggestionContentError) as exc_info:
        item.validate_with_index(3)
    assert exc_info.value.pointer == "/data/similarSuggestions/3/similarity"


def test_similar_suggestion_invalid_similarity_nan():
    item = _make_similar("sug-1", similarity=float("nan"))
    with pytest.raises(InvalidSuggestionContentError) as exc_info:
        item.validate_with_index(1)
    assert exc_info.value.pointer == "/data/similarSuggestions/1/similarity"


def test_generation_input_none_current_suggestion():
    with pytest.raises(InvalidSuggestionContentError) as exc_info:
        GenerationInput(current_suggestion=cast(Any, None))
    assert exc_info.value.pointer == "/data/currentSuggestion"
    assert exc_info.value.field_name == "current_suggestion"


def test_generation_input_invalid_similar_suggestion_type():
    with pytest.raises(InvalidSuggestionContentError) as exc_info:
        GenerationInput(
            current_suggestion=_make_current(),
            similar_suggestions=cast(Any, ["not-a-similar-suggestion-object"]),
        )
    assert exc_info.value.pointer == "/data/similarSuggestions/0"
    assert exc_info.value.field_name == "similar_suggestions"


def test_whitespace_context_title_falls_back_to_omoomi():
    preparer, _ = _make_preparer()
    gen_input = GenerationInput(current_suggestion=_make_current(context_title="    "))
    result = preparer.prepare(gen_input, max_prompt_tokens=50000)
    assert "حوزه تخصصی: عمومی" in result.prompt


# ==============================================================================
# 6.2 Upfront Token Budgeting & Fail-Fast Boundaries
# ==============================================================================


def test_negative_or_zero_budget():
    preparer, _ = _make_preparer()
    gen_input = GenerationInput(current_suggestion=_make_current())

    with pytest.raises(PromptBudgetExceededError) as exc1:
        preparer.prepare(gen_input, max_prompt_tokens=0)
    assert exc1.value.pointer == "/data/maxPromptTokens"

    with pytest.raises(PromptBudgetExceededError) as exc2:
        preparer.prepare(gen_input, max_prompt_tokens=-10)
    assert exc2.value.pointer == "/data/maxPromptTokens"


def test_budget_exceeded_on_fixed_sections():
    preparer, tokenizer = _make_preparer()
    gen_input = GenerationInput(current_suggestion=_make_current())
    conf = SuggestionAnalysisPromptConfig()

    curr = gen_input.current_suggestion
    user_content = f"عنوان پیشنهاد: {curr.title}\nحوزه تخصصی: {curr.context_title}\nمسئله و چالش: {curr.problem}\nراهکار پیشنهادی: {curr.solution}"
    t_fixed = (
        tokenizer.count_tokens(conf.system_instruction)
        + tokenizer.count_tokens(user_content)
        + tokenizer.count_tokens(conf.output_format)
    )
    t_sep = 2 * tokenizer.count_tokens("\n\n")

    # Give 1 token less than needed
    with pytest.raises(PromptBudgetExceededError) as exc_info:
        preparer.prepare(gen_input, max_prompt_tokens=t_fixed + t_sep - 1)
    assert exc_info.value.pointer == "/data/maxPromptTokens"


def test_exact_budget_fixed_sections_no_evidence():
    preparer, tokenizer = _make_preparer()
    gen_input = GenerationInput(
        current_suggestion=_make_current(),
        similar_suggestions=[],
    )
    conf = SuggestionAnalysisPromptConfig()

    curr = gen_input.current_suggestion
    user_content = f"عنوان پیشنهاد: {curr.title}\nحوزه تخصصی: {curr.context_title}\nمسئله و چالش: {curr.problem}\nراهکار پیشنهادی: {curr.solution}"
    t_fixed = (
        tokenizer.count_tokens(conf.system_instruction)
        + tokenizer.count_tokens(user_content)
        + tokenizer.count_tokens(conf.output_format)
    )
    t_sep = 2 * tokenizer.count_tokens("\n\n")

    result = preparer.prepare(gen_input, max_prompt_tokens=t_fixed + t_sep)
    assert result.total_tokens == t_fixed + t_sep
    assert len(result.sections) == 3


def test_insufficient_evidence_budget_raises():
    preparer, tokenizer = _make_preparer()
    sug = _make_similar("101", problem="چالش بسیار طولانی " * 20)
    gen_input = GenerationInput(
        current_suggestion=_make_current(),
        similar_suggestions=[sug],
    )

    conf = SuggestionAnalysisPromptConfig()
    curr = gen_input.current_suggestion
    user_content = f"عنوان پیشنهاد: {curr.title}\nحوزه تخصصی: {curr.context_title}\nمسئله و چالش: {curr.problem}\nراهکار پیشنهادی: {curr.solution}"
    t_fixed = (
        tokenizer.count_tokens(conf.system_instruction)
        + tokenizer.count_tokens(user_content)
        + tokenizer.count_tokens(conf.output_format)
    )
    t_sep = 3 * tokenizer.count_tokens("\n\n")

    # Budget covers fixed + separators + only 10 tokens (not enough for sug)
    budget = t_fixed + t_sep + 10
    with pytest.raises(InsufficientEvidenceBudgetError) as exc_info:
        preparer.prepare(gen_input, max_prompt_tokens=budget)
    assert exc_info.value.pointer == "/data/similarSuggestions"


def test_exact_budget_for_single_item():
    preparer, tokenizer = _make_preparer()
    sug1 = _make_similar("101", similarity=0.95)
    sug2 = _make_similar("102", similarity=0.92)
    gen_input = GenerationInput(
        current_suggestion=_make_current(),
        similar_suggestions=[sug1, sug2],
    )

    conf = SuggestionAnalysisPromptConfig()
    curr = gen_input.current_suggestion
    user_content = f"عنوان پیشنهاد: {curr.title}\nحوزه تخصصی: {curr.context_title}\nمسئله و چالش: {curr.problem}\nراهکار پیشنهادی: {curr.solution}"
    t_fixed = (
        tokenizer.count_tokens(conf.system_instruction)
        + tokenizer.count_tokens(user_content)
        + tokenizer.count_tokens(conf.output_format)
    )
    t_sep = 3 * tokenizer.count_tokens("\n\n")

    # Tokens for item 1 with pre_context framing
    status_title = getattr(sug1.status, "title_fa", str(sug1.status))
    item1_content = f"[پیشنهاد مشابه 1] کد پیشنهاد: {sug1.id} | وضعیت: {status_title} | میزان تشابه: {sug1.similarity:.2f}\nعنوان: {sug1.title}\nمسئله: {sug1.problem}\nراهکار: {sug1.solution}"
    pre_header = "## سوابق پیشنهادات مشابه بازیابی‌شده:"
    item1_tokens = (
        tokenizer.count_tokens(pre_header)
        + tokenizer.count_tokens("\n\n")
        + tokenizer.count_tokens(item1_content)
    )

    exact_budget = t_fixed + t_sep + item1_tokens
    result = preparer.prepare(gen_input, max_prompt_tokens=exact_budget)

    assert "101" in result.prompt
    assert "102" not in result.prompt
    assert result.total_tokens <= exact_budget


# ==============================================================================
# 6.3 Rank Integrity & Knapsack Anti-Skip Tests
# ==============================================================================


def test_oversized_first_item_never_skipped():
    preparer, tokenizer = _make_preparer()
    sug1_large = _make_similar("101", problem="الف" * 200)
    sug2_small = _make_similar("102", problem="ب" * 10)
    gen_input = GenerationInput(
        current_suggestion=_make_current(),
        similar_suggestions=[sug1_large, sug2_small],
    )

    conf = SuggestionAnalysisPromptConfig()
    curr = gen_input.current_suggestion
    user_content = f"عنوان پیشنهاد: {curr.title}\nحوزه تخصصی: {curr.context_title}\nمسئله و چالش: {curr.problem}\nراهکار پیشنهادی: {curr.solution}"
    t_fixed = (
        tokenizer.count_tokens(conf.system_instruction)
        + tokenizer.count_tokens(user_content)
        + tokenizer.count_tokens(conf.output_format)
    )
    t_sep = 3 * tokenizer.count_tokens("\n\n")

    # Give budget enough for sug2_small, but not enough for sug1_large
    status_title2 = getattr(sug2_small.status, "title_fa", str(sug2_small.status))
    item2_content = f"[پیشنهاد مشابه 1] کد پیشنهاد: {sug2_small.id} | وضعیت: {status_title2} | میزان تشابه: {sug2_small.similarity:.2f}\nعنوان: {sug2_small.title}\nمسئله: {sug2_small.problem}\nراهکار: {sug2_small.solution}"
    pre_header = "## سوابق پیشنهادات مشابه بازیابی‌شده:"
    item2_tokens = (
        tokenizer.count_tokens(pre_header)
        + tokenizer.count_tokens("\n\n")
        + tokenizer.count_tokens(item2_content)
    )

    budget = t_fixed + t_sep + item2_tokens + 10

    # Must raise InsufficientEvidenceBudgetError and NEVER select sug2_small
    with pytest.raises(InsufficientEvidenceBudgetError):
        preparer.prepare(gen_input, max_prompt_tokens=budget)


def test_oversized_intermediate_item_stops_collection():
    preparer, tokenizer = _make_preparer()
    sug1 = _make_similar("101", problem="الف" * 10)
    sug2_large = _make_similar("102", problem="ب" * 300)
    sug3_small = _make_similar("103", problem="ج" * 10)
    gen_input = GenerationInput(
        current_suggestion=_make_current(),
        similar_suggestions=[sug1, sug2_large, sug3_small],
    )

    conf = SuggestionAnalysisPromptConfig()
    curr = gen_input.current_suggestion
    user_content = f"عنوان پیشنهاد: {curr.title}\nحوزه تخصصی: {curr.context_title}\nمسئله و چالش: {curr.problem}\nراهکار پیشنهادی: {curr.solution}"
    t_fixed = (
        tokenizer.count_tokens(conf.system_instruction)
        + tokenizer.count_tokens(user_content)
        + tokenizer.count_tokens(conf.output_format)
    )
    t_sep = 3 * tokenizer.count_tokens("\n\n")

    # Capacity enough for sug1 + a bit more, but not enough for sug2_large
    status_title1 = getattr(sug1.status, "title_fa", str(sug1.status))
    item1_content = f"[پیشنهاد مشابه 1] کد پیشنهاد: {sug1.id} | وضعیت: {status_title1} | میزان تشابه: {sug1.similarity:.2f}\nعنوان: {sug1.title}\nمسئله: {sug1.problem}\nراهکار: {sug1.solution}"
    pre_header = "## سوابق پیشنهادات مشابه بازیابی‌شده:"
    item1_tokens = (
        tokenizer.count_tokens(pre_header)
        + tokenizer.count_tokens("\n\n")
        + tokenizer.count_tokens(item1_content)
    )

    budget = t_fixed + t_sep + item1_tokens + 50
    result = preparer.prepare(gen_input, max_prompt_tokens=budget)

    # Asserts sug1 is present, but sug2 and sug3 are NOT present (break on sug2)
    assert "101" in result.prompt
    assert "102" not in result.prompt
    assert "103" not in result.prompt


# ==============================================================================
# 6.4 Prompt Formatting, Framing, & Structural Integrity Tests
# ==============================================================================


def test_section_assembly_order():
    preparer, _ = _make_preparer()
    gen_input = GenerationInput(
        current_suggestion=_make_current(title="عنوان یونیک تست"),
        similar_suggestions=[_make_similar("sug-unique-999")],
    )
    result = preparer.prepare(gen_input, max_prompt_tokens=50000)

    pos_system = result.prompt.find("شما دستیار هوشمند")
    pos_user = result.prompt.find("عنوان پیشنهاد: عنوان یونیک تست")
    pos_evidence = result.prompt.find("## سوابق پیشنهادات مشابه بازیابی‌شده:")
    pos_output = result.prompt.find("## قالب و ساختار خروجی مورد انتظار:")

    assert pos_system != -1
    assert pos_user != -1
    assert pos_evidence != -1
    assert pos_output != -1
    assert pos_system < pos_user < pos_evidence < pos_output


def test_zero_evidence_header_suppression():
    preparer, _ = _make_preparer()
    gen_input = GenerationInput(
        current_suggestion=_make_current(),
        similar_suggestions=[],
    )
    result = preparer.prepare(gen_input, max_prompt_tokens=50000)
    assert "## سوابق پیشنهادات مشابه بازیابی‌شده:" not in result.prompt
    assert len(result.sections) == 3


def test_separator_count():
    preparer, _ = _make_preparer()
    # 4 sections -> 3 double newlines between sections
    gen_input_with_ev = GenerationInput(
        current_suggestion=_make_current(),
        similar_suggestions=[_make_similar("101")],
    )
    result4 = preparer.prepare(gen_input_with_ev, max_prompt_tokens=50000)
    assert len(result4.sections) == 4

    # 3 sections -> 2 double newlines between sections
    gen_input_no_ev = GenerationInput(
        current_suggestion=_make_current(),
        similar_suggestions=[],
    )
    result3 = preparer.prepare(gen_input_no_ev, max_prompt_tokens=50000)
    assert len(result3.sections) == 3


# ==============================================================================
# 6.5 Safety Net & Truncation Invariant Tests
# ==============================================================================


def test_fixed_sections_never_truncated():
    preparer, _ = _make_preparer()
    conf = SuggestionAnalysisPromptConfig()
    curr = _make_current(title="تست عدم برش بخش‌های ثابت")
    gen_input = GenerationInput(
        current_suggestion=curr,
        similar_suggestions=[_make_similar("101"), _make_similar("102")],
    )
    result = preparer.prepare(gen_input, max_prompt_tokens=50000)

    # Fixed sections must match exactly
    assert conf.system_instruction in result.prompt
    assert "عنوان پیشنهاد: تست عدم برش بخش‌های ثابت" in result.prompt
    assert conf.output_format in result.prompt


def test_similar_suggestions_never_mid_sentence_truncated():
    preparer, tokenizer = _make_preparer()
    sug1 = _make_similar("101", solution="این راهکار نباید به هیچ عنوان نصفه شود")
    sug2 = _make_similar("102", solution="این راهکار دوم است")
    gen_input = GenerationInput(
        current_suggestion=_make_current(),
        similar_suggestions=[sug1, sug2],
    )
    result = preparer.prepare(gen_input, max_prompt_tokens=50000)

    # Both items must be fully present without broken sentences
    assert sug1.solution in result.prompt
    assert sug2.solution in result.prompt


def test_total_tokens_never_exceeds_budget():
    preparer, _ = _make_preparer()
    gen_input = GenerationInput(
        current_suggestion=_make_current(),
        similar_suggestions=[
            _make_similar("1"),
            _make_similar("2"),
            _make_similar("3"),
        ],
    )
    budget = 2500
    result = preparer.prepare(gen_input, max_prompt_tokens=budget)
    assert result.total_tokens <= budget


# ==============================================================================
# 6.6 Dependency Injection & Port Enforcement Tests
# ==============================================================================


def test_container_resolves_suggestion_prompt_preparer():
    container = Container()
    container.tokenizer.override(providers.Object(FakeTokenizer()))
    preparer = container.suggestion_prompt_preparer()
    assert isinstance(preparer, ISuggestionPromptPreparer)


def test_constructor_requires_collaborators():
    tok = FakeTokenizer()
    conf = SuggestionAnalysisPromptConfig()
    allocator = CapacityAllocator(DemandAllocator(), RedistributionAllocator())
    ctx_builder = ContextBuilder(
        tokenizer=tok,
        capacity_allocator=allocator,
        dispatcher=OverflowStrategyDispatcher(),
    )

    with pytest.raises(TypeError):
        SuggestionPromptPreparer(
            context_builder=cast(Any, None),
            tokenizer=tok,
            config=conf,
        )

    with pytest.raises(TypeError):
        SuggestionPromptPreparer(
            context_builder=ctx_builder,
            tokenizer=cast(Any, None),
            config=conf,
        )

    with pytest.raises(TypeError):
        SuggestionPromptPreparer(
            context_builder=ctx_builder,
            tokenizer=tok,
            config=cast(Any, None),
        )


# ==============================================================================
# 6.7 Tokenizer & Persian Unicode Smoke Tests
# ==============================================================================


def test_persian_zwnj_tokenization():
    tokenizer = FakeTokenizer()
    text = "پیشنهادهای بهینه‌سازی مصرف انرژی بررسی می‌شود."
    tokens = tokenizer.encode(text)
    assert len(tokens) == len(text)
    assert tokenizer.count_tokens(text) == len(text)


def test_persian_digits_and_symbols_in_preparer():
    preparer, _ = _make_preparer()
    gen_input = GenerationInput(
        current_suggestion=_make_current(
            title="پروژه شماره ۱۲۳۴۵",
            problem="مسئله با اعداد ۱ و ۲ و ۳",
            solution="راهکار ۴۵۶۷",
        ),
        similar_suggestions=[_make_similar("999", title="سابق ۹۹۹")],
    )
    result = preparer.prepare(gen_input, max_prompt_tokens=50000)
    assert "پروژه شماره ۱۲۳۴۵" in result.prompt
    assert "سابق ۹۹۹" in result.prompt
