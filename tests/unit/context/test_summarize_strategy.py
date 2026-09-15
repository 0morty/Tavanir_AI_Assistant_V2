from src.domain.context.overflow.strategy import OverflowStrategy
from src.domain.context.overflow.summarize import SummarizeStrategy
from src.domain.context.summarizer import Summarizer
from src.infrastructure.services.summarizers import FAKE_SUMMARY_TEXT, FakeSummarizer


class RecordingSummarizer(Summarizer):
    def __init__(self) -> None:
        self.received_texts: list[str] = []

    def summarize(self, text: str) -> str:
        self.received_texts.append(text)
        return "recorded-summary"


def test_summarize_strategy_is_an_overflow_strategy():
    strategy = SummarizeStrategy(FakeSummarizer())
    assert isinstance(strategy, OverflowStrategy)


def test_summarize_strategy_delegates_to_injected_summarizer():
    summarizer = RecordingSummarizer()
    strategy = SummarizeStrategy(summarizer)

    result = strategy.apply("section content", capacity=100)

    assert result == "recorded-summary"
    assert summarizer.received_texts == ["section content"]


def test_summarize_strategy_returns_static_fake_summary_deterministically():
    strategy = SummarizeStrategy(FakeSummarizer())

    first = strategy.apply("long original text", capacity=50)
    second = strategy.apply("a completely different text", capacity=10)

    assert first == FAKE_SUMMARY_TEXT
    assert second == FAKE_SUMMARY_TEXT
    assert first == second


def test_summarize_strategy_ignores_capacity_for_now():
    strategy = SummarizeStrategy(FakeSummarizer())
    assert strategy.apply("content", capacity=1) == FAKE_SUMMARY_TEXT


def test_summarize_strategy_requires_a_summarizer():
    try:
        SummarizeStrategy()  # type: ignore[call-arg]
    except TypeError:
        pass
    else:
        raise AssertionError("SummarizeStrategy must require a Summarizer")