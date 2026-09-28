from src.application.reference import (
    TemplateValidationResult,
    TemplateValidator,
    extract_placeholders,
)
from src.domain.entities import ReferenceDetails


def details(*properties: tuple[str, str]) -> ReferenceDetails:
    return ReferenceDetails(properties=tuple(properties))


def test_template_with_only_valid_properties_passes():
    validator = TemplateValidator()
    template = "در فصل [chapter] ام و در صفحه [page]، نویسنده [author] می گوید:"

    result = validator.validate(
        template,
        details(("chapter", "int"), ("page", "int"), ("author", "str")),
    )

    assert result.valid is True
    assert result.missing == ()


def test_template_with_unknown_property_is_invalid():
    validator = TemplateValidator()

    result = validator.validate(
        "On page [page], written by [writer], it is stated:",
        details(("page", "int")),
    )

    assert result.valid is False
    assert result.missing == ()
    assert result.unknown == ("writer",)


def test_template_with_valid_and_unknown_properties_is_invalid():
    validator = TemplateValidator()

    result = validator.validate(
        "On page [page], written by [writer], it is stated:",
        details(("author", "str"), ("page", "int")),
    )

    assert result.valid is False
    assert result.missing == ("author",)
    assert result.unknown == ("writer",)


def test_repeated_valid_placeholder_is_not_reported_missing():
    validator = TemplateValidator()

    result = validator.validate(
        "On page [page], see page [page] and page [page].",
        details(("page", "int")),
    )

    assert result.valid is True
    assert result.missing == ()


def test_extract_placeholders_deduplicates_in_first_seen_order():
    assert extract_placeholders("[page] [page] [author] [page]") == (
        "page",
        "author",
    )


def test_none_valued_property_is_valid_when_it_exists_in_details():
    validator = TemplateValidator()

    result = validator.validate(
        "[chapter] [page] [author]",
        details(
            ("chapter", "int"),
            ("page", "int"),
            ("author", "NoneType"),
        ),
    )

    assert result.valid is True
    assert result.missing == ()


def test_template_with_no_placeholders_is_invalid_for_nonempty_schema():
    result = TemplateValidator().validate(
        "MyReference contains a title and page.",
        details(("title", "str"), ("page", "int")),
    )
    assert result.valid is False
    assert result.missing == ("title", "page")
    assert result.unknown == ()


def test_missing_declared_property_is_invalid():
    result = TemplateValidator().validate(
        'Regulation "[title]" on page [page].',
        details(("title", "str"), ("article", "str"), ("page", "int")),
    )
    assert result.valid is False
    assert result.missing == ("article",)
    assert result.unknown == ()


def test_unknown_and_missing_are_reported_separately():
    result = TemplateValidator().validate(
        "The reference is about [name] on page [number].",
        details(("title", "str"), ("page", "int")),
    )
    assert result.valid is False
    assert result.missing == ("title", "page")
    assert result.unknown == ("name", "number")
    assert "unavailable properties: name, number" in result.error_message()
    assert "required properties: title, page" in result.error_message()


def test_empty_schema_accepts_empty_template():
    result = TemplateValidator().validate("", details())
    assert result.valid is True
    assert result.missing == ()
    assert result.unknown == ()


def test_result_is_a_frozen_validation_result():
    result = TemplateValidationResult(valid=False, unknown=("writer",))
    assert result.valid is False
    assert result.unknown == ("writer",)
