from unittest.mock import Mock

import pytest

from src.application.context import ContextBuilder
from src.application.context.sections import PromptSection, ReferencedSection
from src.application.prompt import PromptBuilder
from src.domain.context.overflow.summarize import SummarizeStrategy
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import Reference
from src.domain.enums import OverflowStrategy
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class FakeTokenizer(Tokenizer):
    """Char-based tokenizer: every character counts as one token."""

    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        return [(i, (i, i + 1)) for i in range(len(text))]

    def count_tokens(self, text: str) -> int:
        return len(text)


class FluentReference(Reference):
    """Reference whose native fluent text is a fixed prefix."""

    @property
    def description(self) -> str:
        return "A reference with native fluent text."

    def fluent_text(self) -> str:
        return "REF:"


class TextSection(PromptSection):
    """Plain-text section with a per-instance identity."""

    def __init__(
        self,
        name: str,
        content: str,
        *,
        importance: float | None = None,
        demand: float | None = None,
        default_importance: float = 0.5,
        default_demand: float = 0.5,
        overflow_strategies: OverflowStrategyStack | None = None,
    ) -> None:
        super().__init__(
            importance=importance,
            demand=demand,
            default_importance=default_importance,
            default_demand=default_demand,
            overflow_strategies=overflow_strategies,
        )
        self._name = name
        self._content = content

    @property
    def section_type(self) -> str:
        return self._name

    def body(self) -> str:
        return self._content


class ReferencedTextSection(ReferencedSection):
    """ReferencedSection with a per-instance identity."""

    def __init__(
        self,
        name: str,
        content: str,
        reference: Reference | None,
        *,
        demand: float | None = None,
        default_demand: float = 0.5,
    ) -> None:
        super().__init__(
            reference=reference,
            demand=demand,
            default_demand=default_demand,
        )
        self._name = name
        self._content = content

    @property
    def section_type(self) -> str:
        return self._name

    def body(self) -> str:
        return self._content


def make_builder(*sections) -> PromptBuilder:
    builder = PromptBuilder(seed_defaults=False)
    for section in sections:
        builder.set_section(section.section_type, section)
    return builder


def test_build_returns_empty_prompt_without_sections():
    result = ContextBuilder(tokenizer=FakeTokenizer()).build(
        make_builder(), max_tokens=100
    )
    assert result.prompt == ""
    assert result.sections == ()
    assert result.total_tokens == 0


def test_build_rejects_negative_max_tokens():
    with pytest.raises(ValueError):
        ContextBuilder(tokenizer=FakeTokenizer()).build(make_builder(), max_tokens=-1)


def test_initial_budget_is_proportional_to_demand():
    builder = make_builder(
        TextSection("A", "x" * 49, demand=0.5),
        TextSection("B", "y" * 49, demand=0.5),
    )
    result = ContextBuilder(tokenizer=FakeTokenizer()).build(builder, max_tokens=100)

    assert [output.capacity_tokens for output in result.sections] == [49, 49]
    assert [output.overflowed for output in result.sections] == [False, False]
    assert result.total_tokens == 100 <= result.budget_tokens


def test_content_within_its_share_is_kept_unchanged():
    builder = make_builder(
        TextSection("A", "abc", demand=0.5),
        TextSection("B", "defghijklm", demand=0.5),
    )
    result = ContextBuilder(tokenizer=FakeTokenizer()).build(builder, max_tokens=100)

    assert [output.content for output in result.sections] == ["abc", "defghijklm"]
    assert [output.capacity_tokens for output in result.sections] == [3, 10]


def test_empty_section_is_excluded_from_prompt_but_reported():
    builder = make_builder(
        TextSection("A", "abc", demand=0.5),
        TextSection("EMPTY", "", demand=0.5),
    )
    result = ContextBuilder(tokenizer=FakeTokenizer()).build(builder, max_tokens=100)

    assert result.prompt == "abc"
    assert result.sections[1].content == ""
    assert result.total_tokens == 3


def test_reference_text_resolved_into_content_and_counts_toward_capacity():
    builder = make_builder(
        ReferencedTextSection("A", "abc", FluentReference(), demand=0.5),
        TextSection("B", "q" * 40, demand=0.5),
    )
    result = ContextBuilder(tokenizer=FakeTokenizer()).build(builder, max_tokens=100)

    section_a = result.sections[0]
    assert section_a.content == "REF:\nabc"
    assert section_a.requested_tokens == 8
    assert section_a.overflowed is False
    assert "REF:" in result.prompt


def test_missing_reference_leaves_content_unchanged():
    builder = make_builder(
        ReferencedTextSection("A", "abc", None, demand=0.5),
    )
    result = ContextBuilder(tokenizer=FakeTokenizer()).build(builder, max_tokens=100)

    assert result.sections[0].content == "abc"
    assert "REF:" not in result.prompt


def test_scarcity_redistributes_free_capacity_by_importance():
    builder = make_builder(
        TextSection("UNDER", "abc", demand=0.9, default_demand=0.9),
        TextSection("OVER", "q" * 90, demand=0.1, default_demand=0.1, importance=1.0),
    )
    result = ContextBuilder(tokenizer=FakeTokenizer()).build(builder, max_tokens=200)

    under = next(o for o in result.sections if o.section_type == "UNDER")
    over = next(o for o in result.sections if o.section_type == "OVER")
    assert under.capacity_tokens == 3
    assert over.capacity_tokens == 90
    assert over.overflowed is False
    assert over.content == "q" * 90


def test_default_overflow_truncates_to_capacity():
    builder = make_builder(TextSection("A", "x" * 100))
    result = ContextBuilder(tokenizer=FakeTokenizer()).build(builder, max_tokens=50)

    section = result.sections[0]
    assert section.overflowed is True
    assert section.fitted_tokens <= section.capacity_tokens == 50
    assert section.content == "x" * 50


def test_summarize_overflow_with_injected_summarizer():
    summarizer = Mock()
    summarizer.summarize.return_value = "SM"
    builder = make_builder(
        TextSection(
            "A",
            "x" * 100,
            overflow_strategies=OverflowStrategyStack([OverflowStrategy.SUMMARIZE]),
        )
    )
    result = ContextBuilder(
        tokenizer=FakeTokenizer(), summarizer=summarizer
    ).build(builder, max_tokens=10)

    section = result.sections[0]
    assert section.overflowed is True
    assert section.content == "SM"
    summarizer.summarize.assert_called_once()


def test_ignore_only_stack_falls_back_to_truncate_safety_net():
    builder = make_builder(
        TextSection(
            "A",
            "x" * 20,
            overflow_strategies=OverflowStrategyStack([OverflowStrategy.IGNORE]),
        )
    )
    result = ContextBuilder(tokenizer=FakeTokenizer()).build(builder, max_tokens=5)

    section = result.sections[0]
    assert section.overflowed is True
    assert section.fitted_tokens == 5 <= section.capacity_tokens


def test_output_never_exceeds_budget():
    builder = make_builder(
        TextSection("A", "a" * 60, demand=0.6, default_demand=0.6),
        TextSection("B", "b" * 30, demand=0.3, default_demand=0.3),
        TextSection("C", "c" * 100, demand=0.1, default_demand=0.1),
    )
    result = ContextBuilder(tokenizer=FakeTokenizer()).build(builder, max_tokens=120)

    assert result.total_tokens <= result.budget_tokens
    assert result.total_tokens == FakeTokenizer().count_tokens(result.prompt)
    assert all(
        output.fitted_tokens <= output.capacity_tokens
        for output in result.sections
    )


def test_sections_preserve_registration_order():
    builder = make_builder(
        TextSection("FIRST", "a" * 5),
        TextSection("SECOND", "b" * 5),
        TextSection("THIRD", "c" * 5),
    )
    result = ContextBuilder(tokenizer=FakeTokenizer()).build(builder, max_tokens=100)

    assert [output.section_type for output in result.sections] == [
        "FIRST",
        "SECOND",
        "THIRD",
    ]