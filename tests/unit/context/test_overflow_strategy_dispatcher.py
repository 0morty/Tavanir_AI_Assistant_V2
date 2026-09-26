from src.application.context import OverflowStrategyDispatcher
from src.application.context.sections import CompressibleSection, PromptSection
from src.application.dtos import SectionProcessingResult
from src.domain.context.summarizer import Summarizer
from src.domain.context.tokenizer import Tokenizer
from src.domain.enums import OverflowStrategy


class FakeTokenizer(Tokenizer):
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
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.truncate_result = SectionProcessingResult("truncated")
        self.summarize_result = SectionProcessingResult("summarized")
        self.ignore_result = SectionProcessingResult("ignored")

    def truncate(self, content, capacity_tokens, *, tokenizer):
        self.calls.append("truncate")
        return self.truncate_result

    def summarize(self, content, capacity_tokens):
        self.calls.append("summarize")
        return self.summarize_result

    def ignore(self, content, capacity_tokens, *, tokenizer):
        self.calls.append("ignore")
        return self.ignore_result


def test_dispatcher_maps_each_strategy_to_its_section_operation():
    prepared = SectionProcessingResult("content")
    for strategy, expected in [
        (OverflowStrategy.TRUNCATE, "truncate"),
        (OverflowStrategy.SUMMARIZE, "summarize"),
        (OverflowStrategy.IGNORE, "ignore"),
    ]:
        section = SpySection()
        result = OverflowStrategyDispatcher().apply(
            section, strategy, prepared, 10, tokenizer=FakeTokenizer()
        )
        assert result.content == {"truncate": "truncated", "summarize": "summarized", "ignore": "ignored"}[expected]
        assert section.calls == [expected]


def test_dispatcher_passes_through_none_when_unavailable():
    section = SpySection()
    section.summarize_result = None
    assert OverflowStrategyDispatcher().apply(
        section, OverflowStrategy.SUMMARIZE, SectionProcessingResult("content"), 10,
        tokenizer=FakeTokenizer(),
    ) is None
    assert section.calls == ["summarize"]


def test_dispatcher_invokes_plain_section_transformations():
    class Plain(PromptSection):
        @property
        def section_type(self) -> str:
            return "PLAIN"

        def body(self) -> str:
            return "abcdefghij"

    summarizer = RecordingSummarizer()
    section = Plain(summarizer=summarizer)
    prepared = section.prepare()
    dispatcher = OverflowStrategyDispatcher()
    assert dispatcher.apply(
        section, OverflowStrategy.TRUNCATE, prepared, 3,
        tokenizer=FakeTokenizer(),
    ).content == "abc"
    assert dispatcher.apply(
        section, OverflowStrategy.SUMMARIZE, prepared, 3,
        tokenizer=FakeTokenizer(),
    ).content == "recorded-summary"
    assert summarizer.received_texts == ["abcdefghij"]
    assert dispatcher.apply(
        section, OverflowStrategy.IGNORE, prepared, 3,
        tokenizer=FakeTokenizer(),
    ) is None


def test_dispatcher_rejects_unknown_strategy():
    try:
        OverflowStrategyDispatcher().apply(
            SpySection(), "unknown", SectionProcessingResult("content"), 10,
            tokenizer=FakeTokenizer(),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Unknown strategy must fail")
