from src.domain.entities import Chunk, HistoryMessage
from src.domain.enums import HistoryRole
from src.application.prompt_architecture.prompt_builder import PromptBuilder
from src.application.prompt_architecture.prompt_section import PromptSection
from src.application.prompt_architecture.role_section import RoleSection
from src.application.prompt_architecture.string_section import StringSection


class RegulationSection(PromptSection):
    """A custom section introduced without touching any central enum."""

    @property
    def section_type(self) -> str:
        return "REGULATION"

    def body(self) -> str:
        return "Relevant regulations."


def test_default_builder_contains_canonical_sections_in_order():
    builder = PromptBuilder()
    assert [s.section_type for s in builder.sections] == [
        "ROLE",
        "HISTORY",
        "CHUNKS",
        "SYSTEM-INPUT",
        "SYSTEM-OUTPUT",
        "OUTPUT-FORMAT",
    ]


def test_empty_builder_renders_empty_string():
    assert PromptBuilder().render() == ""


def test_typed_setters_configure_default_sections():
    builder = PromptBuilder()
    builder.set_role("You are an assistant.")
    builder.set_history([HistoryMessage(role=HistoryRole.USER, content="Hello")])
    builder.set_chunks([Chunk(id="1", title="t", content="chunk content")])
    builder.set_system_input("system input")
    builder.set_system_output("system output")
    builder.set_output_format("Markdown")

    rendered = builder.render()

    assert "You are an assistant." in rendered
    assert "user: Hello" in rendered
    assert "Chunk 1:" in rendered
    assert "system input" in rendered
    assert "system output" in rendered
    assert "Markdown" in rendered
    assert rendered.startswith("You are an assistant.")


def test_typed_setters_replace_in_place_keeping_order():
    builder = PromptBuilder()
    builder.set_role("first role")
    builder.set_section("REGULATION", "content one")
    builder.set_role("second role")
    builder.set_section("REGULATION", "content two")

    assert [s.section_type for s in builder.sections] == [
        "ROLE",
        "HISTORY",
        "CHUNKS",
        "SYSTEM-INPUT",
        "SYSTEM-OUTPUT",
        "OUTPUT-FORMAT",
        "REGULATION",
    ]
    assert builder.get_section("ROLE").body() == "second role"
    assert builder.get_section("REGULATION").body() == "content two"


def test_set_section_wraps_raw_string_into_string_section():
    builder = PromptBuilder()
    builder.set_section("REGULATION", "some text")

    section = builder.get_section("regUlation")
    assert isinstance(section, StringSection)
    assert section.section_type == "REGULATION"
    assert "some text" in builder.render()


def test_set_section_accepts_custom_prompt_section_instance():
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
            builder.set_section(blank, "text")
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
    builder.set_section("METADATA", "meta")
    assert builder.has_section("metadata")
    assert not builder.has_section("UNKNOWN")
    assert builder.get_section("UNKNOWN") is None


def test_custom_sections_coexist_with_defaults():
    builder = PromptBuilder()
    builder.set_role("You are a legal analyst.")
    builder.set_section("REGULATION", "Regulation 1 content")
    builder.set_section("INSTRUCTIONS", "Be concise.")

    rendered = builder.render()
    assert rendered.index("You are a legal analyst.") < rendered.index("Regulation 1 content")
    assert rendered.index("Regulation 1 content") < rendered.index("Be concise.")


def test_seed_defaults_can_be_disabled():
    builder = PromptBuilder(seed_defaults=False)
    assert builder.sections == []
    builder.set_section("REGULATION", "text")
    assert [s.section_type for s in builder.sections] == ["REGULATION"]


def test_constructor_sections_are_merged():
    builder = PromptBuilder(sections=[RegulationSection()])
    assert builder.has_section("ROLE")
    assert builder.has_section("REGULATION")