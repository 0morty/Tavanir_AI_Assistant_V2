from src.application.context.sections import ErrorSection, PropertiesSection
from src.domain.entities import ReferenceDetails


def details(*properties: tuple[str, str]) -> ReferenceDetails:
    return ReferenceDetails(properties=tuple(properties))


def test_error_section_identity_is_error():
    assert ErrorSection("boom").section_type == "ERROR"


def test_error_section_renders_its_content():
    assert ErrorSection("boom").render() == "boom"


def test_error_section_with_empty_content_renders_empty():
    assert ErrorSection("").render() == ""


def test_error_section_default_tuning_is_in_range():
    section = ErrorSection("boom")
    assert 0.0 <= section.importance <= 1.0
    assert 0.0 <= section.demand <= 1.0


def test_properties_section_identity_is_properties():
    assert PropertiesSection(details(("chapter", "str"))).section_type == "PROPERTIES"


def test_properties_section_renders_markdown_table():
    section = PropertiesSection(
        details(("chapter", "str"), ("author", "str"))
    )

    assert section.body() == (
        "| property name | type |\n"
        "|---------------|------|\n"
        "| chapter | str |\n"
        "| author | str |"
    )


def test_properties_section_preserves_property_order():
    section = PropertiesSection(details(("page", "int"), ("title", "str")))

    assert section.body().splitlines()[2:] == ["| page | int |", "| title | str |"]


def test_properties_section_with_no_properties_renders_empty():
    assert PropertiesSection(details()).render() == ""


def test_properties_section_only_lists_available_properties():
    section = PropertiesSection(details(("chapter", "str"), ("page", "int")))

    assert "chapter" in section.body()
    assert "page" in section.body()