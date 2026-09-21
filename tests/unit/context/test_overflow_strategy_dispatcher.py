import pytest

from src.application.context import OverflowStrategyDispatcher
from src.application.context.sections import CompressibleSection
from src.application.context.sections.prompt_section import PromptSection
from src.domain.context.summarizer import Summarizer
from src.domain.context.tokenizer import Tokenizer
from src.domain.enums import OverflowStrategy


class FakeTokenizer(Tokenizer):
    """Char-based tokenizer: every character counts as one token."""

    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        return [(i, (i, i + 1)) for i in range(len(text))]

    def count_tokens(self, text: str) -> int:
        return len(text)


class RecordingSummarizer(Summarizer):
    def __init__(self) -> None:
        self.received_texts: list[str] = []

    def summarize(self, text: str) -> str:
        self.received_texts.append(text)
        return "recorded-summary"


class SpySection(CompressibleSection):
    """Records which CompressibleSection operations the dispatcher invoked."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.truncate_result: str | None = "truncated"
        self.summarize_result: str | None = "summarized"
        self.ignore_result: str | None = "ignored"

    def truncate(self, content, capacity_tokens, *, tokenizer) -> str | None:
        self.calls.append("truncate")
        return self.truncate_result

    def summarize(self, content, capacity_tokens) -> str | None:
        self.calls.append("summarize")
        return self.summarize_result

    def ignore(self, content, capacity_tokens, *, tokenizer) -> str | None:
        self.calls.append("ignore")
        return self.ignore_result


def test_dispatcher_maps_truncate_to_section_truncate():
    section = SpySection()
    result = OverflowStrategyDispatcher().apply(
        section,
        OverflowStrategy.TRUNCATE,
        "content",
        10,
        tokenizer=FakeTokenizer(),
    )
    assert result == "truncated"
    assert section.calls == ["truncate"]


def test_dispatcher_maps_summarize_to_section_summarize():
    section = SpySection()
    result = OverflowStrategyDispatcher().apply(
        section,
        OverflowStrategy.SUMMARIZE,
        "content",
        10,
        tokenizer=FakeTokenizer(),
    )
    assert result == "summarized"
    assert section.calls == ["summarize"]


def test_dispatcher_maps_ignore_to_section_ignore():
    section = SpySection()
    result = OverflowStrategyDispatcher().apply(
        section,
        OverflowStrategy.IGNORE,
        "content",
        10,
        tokenizer=FakeTokenizer(),
    )
    assert result == "ignored"
    assert section.calls == ["ignore"]


def test_dispatcher_passes_through_none_when_section_summarize_unavailable():
    section = SpySection()
    section.summarize_result = None
    result = OverflowStrategyDispatcher().apply(
        section,
        OverflowStrategy.SUMMARIZE,
        "content",
        10,
        tokenizer=FakeTokenizer(),
    )
    assert result is None
    assert section.calls == ["summarize"]


def test_dispatcher_invokes_domain_strategy_through_plain_section():
    dispatcher = OverflowStrategyDispatcher()

    class Plain(PromptSection):
        @property
        def section_type(self) -> str:
            return "PLAIN"

        def body(self) -> str:
            return "abcdefghij"

    section = Plain("abcdefghij", summarizer=RecordingSummarizer())
    assert (
        dispatcher.apply(
            section,
            OverflowStrategy.TRUNCATE,
            "abcdefghij",
            3,
            tokenizer=FakeTokenizer(),
        )
        == "abc"
    )
    assert (
        dispatcher.apply(
            section,
            OverflowStrategy.SUMMARIZE,
            "abcdefghij",
            3,
            tokenizer=FakeTokenizer(),
        )
        == "recorded-summary"
    )
    assert (
        dispatcher.apply(
            section,
            OverflowStrategy.IGNORE,
            "abcdefghij",
            3,
            tokenizer=FakeTokenizer(),
        )
        is None
    )


def test_dispatcher_rejects_unknown_strategy():
    with pytest.raises(ValueError):
        OverflowStrategyDispatcher().apply(
            SpySection(),
            "unknown",  # type: ignore[arg-type]
            "content",
            10,
            tokenizer=FakeTokenizer(),
        )