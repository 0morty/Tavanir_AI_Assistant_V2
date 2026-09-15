from src.domain.context.summarizer import Summarizer
from src.infrastructure.services.summarizers import FAKE_SUMMARY_TEXT, FakeSummarizer


def test_fake_summarizer_implements_summarizer_port():
    assert isinstance(FakeSummarizer(), Summarizer)


def test_fake_summarizer_returns_static_summary_for_any_input():
    summarizer = FakeSummarizer()
    assert summarizer.summarize("") == FAKE_SUMMARY_TEXT
    assert summarizer.summarize("some text") == FAKE_SUMMARY_TEXT
    assert summarizer.summarize("other text") == FAKE_SUMMARY_TEXT


def test_fake_summary_text_is_constant():
    assert FAKE_SUMMARY_TEXT == "[fake-summarizer-output]"