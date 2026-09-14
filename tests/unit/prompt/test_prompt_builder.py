from src.domain.entities import Chunk, HistoryMessage
from src.domain.enums import HistoryRole
from src.application.interfaces import ISection
from src.application.context.sections.role_section import RoleSection
from src.application.prompt.prompt_builder import PromptBuilder


class RegulationSection(ISection):
    """A custom section introduced without touching any central enum."""

    def __init__(self, content: str = "Relevant regulations.") -> None:
        self._content = content

    @property
    def section_type(self) -> str:
        return "REGULATION"

    def body(self) -> str:
        return self._content


class InstructionsSection(ISection):
    """Another developer-designed custom section."""

    def __init__(self, content: str) -> None:
        self._content = content

    @property
    def section_type(self) -> str:
        return "INSTRUCTIONS"

    def body(self) -> str:
        return self._content


def test_default_builder_contains_canonical_sections_in_order():
    builder = PromptBuilder()
    expected = [
        "ROLE",
        "HISTORY",
        "CHUNKS",
        "SYSTEM-INPUT",
        "USER-INPUT",
        "OUTPUT-FORMAT",
    ]
    assert [s.section_type for s in builder.sections] == expected


def test_empty_builder_renders_empty_string():
    assert PromptBuilder().render() == ""


def test_typed_setters_configure_default_sections():
    builder = PromptBuilder()
    builder.set_role("You are an assistant.")
    builder.set_history([HistoryMessage(role=HistoryRole.USER, content="Hello")])
    builder.set_chunks([Chunk(chunk_id="1", parent_id="p1", content="chunk content", metadata={})])
    builder.set_system_input("system input")
    builder.set_output_format("Markdown")

    rendered = builder.render()

    assert "You are an assistant." in rendered
    assert "user: Hello" in rendered
    assert "Chunk 1:" in rendered
    assert "system input" in rendered
    assert "Markdown" in rendered
    assert rendered.startswith("You are an assistant.")


def test_typed_setters_replace_in_place_keeping_order():
    builder = PromptBuilder()
    builder.set_role("first role")
    builder.set_section("REGULATION", RegulationSection("content one"))
    builder.set_role("second role")
    builder.set_section("REGULATION", RegulationSection("content two"))

    assert [s.section_type for s in builder.sections] == [
        "ROLE",
        "HISTORY",
        "CHUNKS",
        "SYSTEM-INPUT",
        "USER-INPUT",
        "OUTPUT-FORMAT",
        "REGULATION",
    ]
    assert builder.get_section("ROLE").body() == "second role"
    assert builder.get_section("REGULATION").body() == "content two"


def test_set_section_rejects_non_section_value():
    builder = PromptBuilder()
    try:
        builder.set_section("REGULATION", "some text")
    except TypeError:
        pass
    else:
        raise AssertionError("Expected TypeError for non-Section value")


def test_set_section_accepts_custom_section_instance():
    builder = PromptBuilder()
    builder.set_section("REGULATION", RegulationSection())

    assert builder.get_section("REGULATION").body() == "Relevant regulations."
    assert "Relevant regulations." in builder.render()


def test_set_section_rejects_identity_mismatch():
    builder = PromptBuilder()
    try:
        builder.set_section("REGULATION", RoleSection("role"))
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError on identity mismatch")


def test_set_section_rejects_blank_name():
    builder = PromptBuilder()
    for blank in ("", "   "):
        try:
            builder.set_section(blank, RegulationSection())
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected ValueError for name {blank!r}")


def test_add_section_appends_and_rejects_duplicates():
    builder = PromptBuilder()
    builder.add_section(RegulationSection())
    assert builder.has_section("REGULATION")

    try:
        builder.add_section(RegulationSection())
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError on duplicate add_section")


def test_get_and_has_section():
    builder = PromptBuilder()
    builder.set_section("REGULATION", RegulationSection())
    assert builder.has_section("regulation")
    assert not builder.has_section("UNKNOWN")
    assert builder.get_section("UNKNOWN") is None


def test_custom_sections_coexist_with_defaults():
    builder = PromptBuilder()
    builder.set_role("You are a legal analyst.")
    builder.set_section("REGULATION", RegulationSection("Regulation 1 content"))
    builder.set_section("INSTRUCTIONS", InstructionsSection("Be concise."))

    rendered = builder.render()
    assert rendered.index("You are a legal analyst.") < rendered.index("Regulation 1 content")
    assert rendered.index("Regulation 1 content") < rendered.index("Be concise.")


def test_seed_defaults_can_be_disabled():
    builder = PromptBuilder(seed_defaults=False)
    assert builder.sections == []
    builder.set_section("REGULATION", RegulationSection())
    assert [s.section_type for s in builder.sections] == ["REGULATION"]


def test_constructor_sections_are_merged():
    builder = PromptBuilder(sections=[RegulationSection()])
    assert builder.has_section("ROLE")
    assert builder.has_section("REGULATION")