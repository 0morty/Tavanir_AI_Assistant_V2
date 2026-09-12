import importlib

import pytest

from src.application.context import (
    ChunksSection,
    HistorySection,
    OutputFormatSection,
    RoleSection,
    Section,
    StringSection,
    SystemInputSection,
    SystemOutputSection,
    UserInputSection,
)
from src.domain.entities import Chunk, HistoryMessage
from src.domain.enums import HistoryRole
from src.application.prompt_architecture import PromptBuilder


def test_section_is_available_from_general_purpose_location():
    from src.application.context.section import Section as ModuleSection

    assert ModuleSection is Section
    assert issubclass(ChunksSection, Section)


def test_prompt_architecture_no_longer_owns_section():
    with pytest.raises(ImportError):
        importlib.import_module("src.application.prompt_architecture.prompt_section")

    with pytest.raises(AttributeError):
        importlib.import_module("src.application.prompt_architecture").Section


def test_predefined_sections_have_expected_default_importance():
    assert RoleSection("").importance == 0.5
    assert HistorySection([]).importance == 0.3
    assert ChunksSection([]).importance == 0.4
    assert SystemInputSection("").importance == 0.5
    assert SystemOutputSection("").importance == 0.5
    assert UserInputSection("").importance == 0.5
    assert OutputFormatSection("").importance == 0.1
    assert StringSection("REGULATION", "").importance == 0.5


def test_explicit_importance_overrides_default():
    assert ChunksSection([], importance=0.7).importance == 0.7
    assert HistorySection([], importance=0.2).importance == 0.2
    assert OutputFormatSection("", importance=0.0).importance == 0.0
    assert RoleSection("", importance=1.0).importance == 1.0


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
        lambda: StringSection("X", "", importance=1.01),
    ):
        with pytest.raises(ValueError):
            factory()


def test_boundary_values_are_accepted():
    assert ChunksSection([], importance=0.0).importance == 0.0
    assert ChunksSection([], importance=1.0).importance == 1.0


def test_arbitrary_importance_values_across_sections_are_allowed():
    sections = [
        ChunksSection([], importance=0.8),
        HistorySection([], importance=0.8),
        RoleSection("", importance=0.5),
    ]
    assert [s.importance for s in sections] == [0.8, 0.8, 0.5]
    assert sum(s.importance for s in sections) == pytest.approx(2.1)


def test_no_requirement_for_importance_to_sum_to_one():
    low = [
        StringSection("A", "", importance=0.2),
        StringSection("B", "", importance=0.1),
        StringSection("C", "", importance=0.1),
    ]
    high = [
        ChunksSection([], importance=0.8),
        HistorySection([], importance=0.8),
        RoleSection("", importance=0.5),
    ]
    assert sum(s.importance for s in low) != pytest.approx(1.0)
    assert sum(s.importance for s in high) != pytest.approx(1.0)


def test_importance_is_only_metadata_not_normalized():
    section = ChunksSection([], importance=0.7)
    assert section.importance == 0.7


def test_prompt_builder_behavior_remains_intact():
    builder = PromptBuilder()
    builder.set_role("You are an assistant.")
    builder.set_history([HistoryMessage(role=HistoryRole.USER, content="Hello")])
    builder.set_chunks(
        [Chunk(chunk_id="1", parent_id="p1", content="chunk content", metadata={})]
    )
    builder.set_system_input("system input")
    builder.set_system_output("system output")
    builder.set_output_format("Markdown")

    rendered = builder.render()

    assert [s.section_type for s in builder.sections] == [
        "ROLE",
        "HISTORY",
        "CHUNKS",
        "SYSTEM-INPUT",
        "SYSTEM-OUTPUT",
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