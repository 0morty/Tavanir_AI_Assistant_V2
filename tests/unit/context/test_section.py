import importlib

import pytest

from src.application.context import (
    ChunksSection,
    HistorySection,
    OutputFormatSection,
    RoleSection,
    SystemInputSection,
    UserInputSection,
)
from src.application.context.sections import PromptSection
from src.application.interfaces import IPromptSection
from src.domain.entities import GenerationChunk, HistoryMessage
from src.domain.enums import HistoryRole, OverflowStrategy
from src.domain.overflow_strategy_stack import OverflowStrategyStack
from src.application.prompt import PromptBuilder


def test_section_interface_is_available_from_interfaces():
    from src.application.interfaces import IPromptSection
    from src.application.interfaces.i_prompt_section import (
        IPromptSection as ModuleIPromptSection,
    )

    assert ModuleIPromptSection is IPromptSection
    assert issubclass(ChunksSection, IPromptSection)


def test_section_skeleton_implements_interface():
    from src.application.context.sections.prompt_section import (
        PromptSection as ModulePromptSection,
    )

    assert ModulePromptSection is PromptSection
    assert issubclass(PromptSection, IPromptSection)
    assert issubclass(ChunksSection, PromptSection)


def test_context_no_longer_owns_section_interface():
    with pytest.raises(ImportError):
        importlib.import_module("src.application.context.section")

    with pytest.raises(AttributeError):
        importlib.import_module("src.application.context").Section


def test_prompt_no_longer_owns_section():
    with pytest.raises(ImportError):
        importlib.import_module("src.application.prompt.prompt_section")

    with pytest.raises(AttributeError):
        importlib.import_module("src.application.prompt").Section


def test_predefined_sections_have_expected_default_importance():
    assert RoleSection("").importance == 0.5
    assert HistorySection([]).importance == 0.3
    assert ChunksSection([]).importance == 0.4
    assert SystemInputSection("").importance == 0.5
    assert UserInputSection("").importance == 0.5
    assert OutputFormatSection("").importance == 0.1


def test_predefined_sections_have_expected_default_demand():
    assert RoleSection("").demand == 0.3
    assert HistorySection([]).demand == 0.4
    assert ChunksSection([]).demand == 0.5
    assert SystemInputSection("").demand == 0.5
    assert UserInputSection("").demand == 0.4
    assert OutputFormatSection("").demand == 0.2


def test_explicit_importance_overrides_default():
    assert ChunksSection([], importance=0.7).importance == 0.7
    assert HistorySection([], importance=0.2).importance == 0.2
    assert OutputFormatSection("", importance=0.0).importance == 0.0
    assert RoleSection("", importance=1.0).importance == 1.0


def test_explicit_demand_overrides_default():
    assert ChunksSection([], demand=0.9).demand == 0.9
    assert HistorySection([], demand=0.1).demand == 0.1
    assert OutputFormatSection("", demand=0.0).demand == 0.0
    assert RoleSection("", demand=1.0).demand == 1.0


def test_importance_below_zero_is_rejected():
    for factory in (
        lambda: ChunksSection([], importance=-0.1),
        lambda: HistorySection([], importance=-1.0),
        lambda: RoleSection("", importance=-0.01),
    ):
        with pytest.raises(ValueError):
            factory()


def test_importance_above_one_is_rejected():
    for factory in (
        lambda: ChunksSection([], importance=1.1),
        lambda: HistorySection([], importance=2.0),
        lambda: RoleSection("", importance=1.01),
    ):
        with pytest.raises(ValueError):
            factory()


def test_demand_below_zero_is_rejected():
    for factory in (
        lambda: ChunksSection([], demand=-0.1),
        lambda: HistorySection([], demand=-1.0),
        lambda: RoleSection("", demand=-0.01),
    ):
        with pytest.raises(ValueError):
            factory()


def test_demand_above_one_is_rejected():
    for factory in (
        lambda: ChunksSection([], demand=1.1),
        lambda: HistorySection([], demand=2.0),
        lambda: RoleSection("", demand=1.01),
    ):
        with pytest.raises(ValueError):
            factory()


def test_boundary_values_are_accepted():
    assert ChunksSection([], importance=0.0).importance == 0.0
    assert ChunksSection([], importance=1.0).importance == 1.0
    assert ChunksSection([], demand=0.0).demand == 0.0
    assert ChunksSection([], demand=1.0).demand == 1.0


def test_arbitrary_importance_values_across_sections_are_allowed():
    sections = [
        ChunksSection([], importance=0.8),
        HistorySection([], importance=0.8),
        RoleSection("", importance=0.5),
    ]
    assert [s.importance for s in sections] == [0.8, 0.8, 0.5]
    assert sum(s.importance for s in sections) == pytest.approx(2.1)


def test_arbitrary_demand_values_across_sections_are_allowed():
    sections = [
        ChunksSection([], demand=0.8),
        HistorySection([], demand=0.8),
        RoleSection("", demand=0.5),
    ]
    assert [s.demand for s in sections] == [0.8, 0.8, 0.5]
    assert sum(s.demand for s in sections) == pytest.approx(2.1)


def test_no_requirement_for_importance_to_sum_to_one():
    low = [
        RoleSection("", importance=0.2),
        SystemInputSection("", importance=0.1),
        UserInputSection("", importance=0.1),
    ]
    high = [
        ChunksSection([], importance=0.8),
        HistorySection([], importance=0.8),
        RoleSection("", importance=0.5),
    ]
    assert sum(s.importance for s in low) != pytest.approx(1.0)
    assert sum(s.importance for s in high) != pytest.approx(1.0)


def test_no_requirement_for_demand_to_sum_to_one():
    low = [
        RoleSection("", demand=0.2),
        SystemInputSection("", demand=0.1),
        UserInputSection("", demand=0.1),
    ]
    high = [
        ChunksSection([], demand=0.8),
        HistorySection([], demand=0.8),
        RoleSection("", demand=0.5),
    ]
    assert sum(s.demand for s in low) != pytest.approx(1.0)
    assert sum(s.demand for s in high) != pytest.approx(1.0)


def test_importance_is_only_metadata_not_normalized():
    section = ChunksSection([], importance=0.7)
    assert section.importance == 0.7


def test_demand_is_only_metadata_not_normalized():
    section = ChunksSection([], demand=0.7)
    assert section.demand == 0.7


def test_importance_and_demand_are_independent():
    section = ChunksSection([], importance=0.2, demand=0.9)
    assert section.importance == 0.2
    assert section.demand == 0.9


def test_predefined_sections_use_default_overflow_strategies():
    expected = OverflowStrategyStack()
    for section in (
        RoleSection(""),
        HistorySection([]),
        ChunksSection([]),
        SystemInputSection(""),
        UserInputSection(""),
        OutputFormatSection(""),
    ):
        stack = section.overflow_strategies
        assert isinstance(stack, OverflowStrategyStack)
        assert stack == expected


def test_overflow_strategies_can_be_overridden():
    custom = OverflowStrategyStack(
        [
            OverflowStrategy.SUMMARIZE,
            OverflowStrategy.TRUNCATE,
            OverflowStrategy.IGNORE,
        ],
        restart=True,
        max_restarts=1,
    )
    section = ChunksSection([], overflow_strategies=custom)
    assert section.overflow_strategies is custom


def test_overflow_strategies_rejects_non_stack():
    with pytest.raises(TypeError):
        ChunksSection([], overflow_strategies=[OverflowStrategy.TRUNCATE])


def test_section_default_overflow_strategies_can_be_overridden_by_subclass():
    class CustomSection(PromptSection):
        def __init__(self) -> None:
            super().__init__(
                default_overflow_strategies=OverflowStrategyStack(
                    [OverflowStrategy.SUMMARIZE]
                )
            )

        @property
        def section_type(self) -> str:
            return "CUSTOM"

        def body(self) -> str:
            return ""

    assert CustomSection().overflow_strategies == OverflowStrategyStack(
        [OverflowStrategy.SUMMARIZE]
    )
    assert CustomSection().overflow_strategies != OverflowStrategyStack()


def test_prompt_builder_behavior_remains_intact():
    builder = PromptBuilder()
    builder.set_role("You are an assistant.")
    builder.set_history([HistoryMessage(role=HistoryRole.USER, content="Hello")])
    builder.set_chunks(
        [GenerationChunk(chunk_id="1", content="chunk content")]
    )
    builder.set_system_input("system input")
    builder.set_output_format("Markdown")

    rendered = builder.render()

    assert [s.section_type for s in builder.sections] == [
        "ROLE",
        "HISTORY",
        "CHUNKS",
        "SYSTEM-INPUT",
        "USER-INPUT",
        "OUTPUT-FORMAT",
    ]
    assert rendered.startswith("You are an assistant.")
    assert "Chunk 1:" in rendered
    assert "Markdown" in rendered


def test_prompt_builder_registers_sections_with_default_importance():
    builder = PromptBuilder()
    assert builder.get_section("CHUNKS").importance == pytest.approx(0.4)
    assert builder.get_section("HISTORY").importance == pytest.approx(0.3)
    assert builder.get_section("OUTPUT-FORMAT").importance == pytest.approx(0.1)

    assert builder.get_section("CHUNKS").demand == pytest.approx(0.5)
    assert builder.get_section("HISTORY").demand == pytest.approx(0.4)
    assert builder.get_section("OUTPUT-FORMAT").demand == pytest.approx(0.2)

    assert builder.get_section("USER-INPUT").importance == pytest.approx(0.5)
    assert builder.get_section("USER-INPUT").demand == pytest.approx(0.4)