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
    assert result.missing == ("writer",)


def test_template_with_valid_and_unknown_properties_is_invalid():
    validator = TemplateValidator()

    result = validator.validate(
        "On page [page], written by [writer], it is stated:",
        details(("author", "str"), ("page", "int")),
    )

    assert result.valid is False
    assert result.missing == ("writer",)


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


def test_template_with_no_placeholders_is_valid():
    validator = TemplateValidator()

    result = validator.validate(
        "On page 10, written by Hamid Jafari, it is stated:",
        details(("page", "int")),
    )

    assert result.valid is True
    assert result.missing == ()


def test_result_is_a_frozen_validation_result():
    result = TemplateValidationResult(valid=False, missing=("writer",))

    assert result.valid is False
    assert result.missing == ("writer",)