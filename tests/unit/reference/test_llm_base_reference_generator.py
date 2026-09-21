from contextlib import contextmanager
from dataclasses import dataclass

from src.application.reference import (
    LLMBaseReferenceGenerator,
    ReferenceGenerationPrompts,
)
from src.application.reference.template_validator import (
    TemplateValidationResult,
    TemplateValidator,
)
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import Reference


@contextmanager
def raises(exc_type):
    try:
        yield
    except exc_type:
        return
    raise AssertionError(f"{exc_type.__name__} was not raised")


class FakeTokenizer(Tokenizer):
    """Char-based tokenizer: every character counts as one token."""

    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        return [(i, (i, i + 1)) for i in range(len(text))]

    def count_tokens(self, text: str) -> int:
        return len(text)


class FakeLLM:
    """Records every prompt and serves canned completions in order.

    When the canned list is exhausted the last response is repeated, so a
    single always-invalid template can be reused across all attempts.
    """

    def __init__(self, *responses: str) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._responses:
            return self._last
        self._last = self._responses.pop(0)
        return self._last


@dataclass
class PageReference(Reference):
    page: int = 10
    author: str = "Hamid Jafari"

    @property
    def description(self) -> str:
        return "Where the content is from."


@dataclass
class EmptyReference(Reference):
    page: int | None = None

    @property
    def description(self) -> str:
        return "Nothing available."


_VALID_TEMPLATE = "On page [page], written by [author], it is stated:"
_INVALID_TEMPLATE = "On page [page], written by [writer], it is stated:"

_PROMPTS = ReferenceGenerationPrompts()


def make_generator(*responses: str, **kwargs) -> tuple[LLMBaseReferenceGenerator, FakeLLM]:
    client = FakeLLM(*responses)
    generator = LLMBaseReferenceGenerator(
        client,
        tokenizer=FakeTokenizer(),
        **kwargs,
    )
    return generator, client


def test_valid_template_stops_after_one_attempt():
    generator, client = make_generator(_VALID_TEMPLATE)

    text = generator.generate(PageReference())

    assert text == "On page 10, written by Hamid Jafari, it is stated:"
    assert len(client.prompts) == 1


def test_first_attempt_prompt_has_no_error_section():
    generator, client = make_generator(_VALID_TEMPLATE)
    generator.generate(PageReference())

    prompt = client.prompts[0]
    assert _PROMPTS.error_heading not in prompt


def test_prompt_sections_appear_in_expected_order():
    generator, client = make_generator(_VALID_TEMPLATE)
    generator.generate(PageReference())

    prompt = client.prompts[0]
    positions = [
        prompt.index(part)
        for part in (
            _PROMPTS.role,
            _PROMPTS.system_input,
            "| property name | type |",
            _PROMPTS.output_format,
        )
    ]
    assert positions == sorted(positions)


def test_retry_includes_validator_error_in_next_prompt():
    generator, client = make_generator(_INVALID_TEMPLATE, _VALID_TEMPLATE)

    text = generator.generate(PageReference())

    assert text == "On page 10, written by Hamid Jafari, it is stated:"
    assert len(client.prompts) == 2

    retry_prompt = client.prompts[1]
    message = TemplateValidationResult(valid=False, missing=("writer",)).error_message()
    assert _PROMPTS.error_heading in retry_prompt
    assert message in retry_prompt


def test_multiple_retries_accumulate_latest_error():
    template = "Written by [ghost]:"
    message = "Template references unavailable properties: ghost."

    generator, client = make_generator(template, template, _VALID_TEMPLATE)

    text = generator.generate(PageReference())

    assert text == "On page 10, written by Hamid Jafari, it is stated:"
    assert len(client.prompts) == 3
    assert message in client.prompts[2]


def test_invalid_after_final_attempt_uses_fallback_fill():
    template = "Written by [ghost], it is stated:"

    generator, client = make_generator(template, template, template)

    text = generator.generate(PageReference())

    assert text == "Written by , it is stated:"
    assert len(client.prompts) == 3


def test_max_attempts_is_configurable():
    template = "Written by [ghost]:"

    generator, client = make_generator(template, max_attempts=5)

    text = generator.generate(PageReference())

    assert len(client.prompts) == 5
    assert text == "Written by :"


def test_rejects_invalid_max_attempts():
    with raises(ValueError):
        make_generator(_VALID_TEMPLATE, max_attempts=0)


def test_rejects_negative_max_tokens():
    with raises(ValueError):
        make_generator(_VALID_TEMPLATE, max_tokens=-1)


def test_reference_without_properties_skips_llm():
    generator, client = make_generator(_VALID_TEMPLATE)

    text = generator.generate(EmptyReference())

    assert text == ""
    assert not client.prompts


def test_injected_validator_is_used():
    class StrictValidator(TemplateValidator):
        def validate(self, template, details):
            return TemplateValidationResult(valid=False, missing=("forced",))

    validator = StrictValidator()
    generator, client = make_generator(_VALID_TEMPLATE, validator=validator)

    generator.generate(PageReference())

    assert len(client.prompts) == 3


def test_validation_error_message_is_empty_when_valid():
    result = TemplateValidationResult(valid=True, missing=())
    assert result.error_message() == ""


def test_validation_error_message_reports_missing_properties():
    result = TemplateValidationResult(valid=False, missing=("writer",))
    assert result.error_message() == "Template references unavailable properties: writer."