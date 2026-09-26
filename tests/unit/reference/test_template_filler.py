from contextlib import contextmanager
from dataclasses import dataclass

from src.application.reference.template_filler import (
    fill_with_fallback,
    substitute_placeholders,
)
from src.domain.entities import Reference


@contextmanager
def raises(exc_type):
    try:
        yield
    except exc_type:
        return
    raise AssertionError(f"{exc_type.__name__} was not raised")


@dataclass
class PageReference(Reference):
    page: int = 10
    author: str = "Hamid Jafari"

    @property
    def description(self) -> str:
        return "Where the content is from."


def reference(**overrides) -> PageReference:
    return PageReference(**overrides)


def test_substitute_fills_known_placeholders():
    ref = reference()

    text = substitute_placeholders(
        "On page [page], written by [author], it is stated:", ref
    )

    assert text == "On page 10, written by Hamid Jafari, it is stated:"


def test_substitute_fills_repeated_placeholders():
    ref = reference()

    text = substitute_placeholders("[author] said: [author]", ref)

    assert text == "Hamid Jafari said: Hamid Jafari"


def test_substitute_preserves_template_without_placeholders():
    ref = reference()

    assert substitute_placeholders("On page 10.", ref) == "On page 10."


def test_substitute_rejects_placeholder_absent_from_details():
    ref = reference()

    with raises(ValueError):
        substitute_placeholders("Written by [writer], it is stated:", ref)


def test_substitute_raises_when_placeholder_value_is_unavailable():
    ref = reference(author=None)

    with raises(ValueError):
        substitute_placeholders("Written by [author]:", ref)


def test_fill_with_fallback_replaces_unavailable_placeholder_with_empty():
    ref = reference()

    text = fill_with_fallback("Written by [writer], it is stated:", ref)

    assert text == "Written by , it is stated:"


def test_fill_with_fallback_still_substitutes_available_placeholders():
    ref = reference()

    text = fill_with_fallback(
        "On page [page], written by [writer]:", ref
    )

    assert text == "On page 10, written by :"


def test_fill_with_fallback_handles_mixed_known_and_unknown():
    ref = reference()

    text = fill_with_fallback(
        "[page] [unknown] [author] [unknown]", ref
    )

    assert text == "10  Hamid Jafari "