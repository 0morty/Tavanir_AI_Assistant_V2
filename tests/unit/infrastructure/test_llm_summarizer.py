import pytest

from src.application.context import ContextBuilder
from src.application.interfaces.i_llm_summarizer import ILLMSummarizer
from src.infrastructure.services.summarizers import (
    LLMSummarizer,
    SummarizationPrompts,
)


class RecordingLLM:
    """Records every prompt and serves canned completions in order."""

    def __init__(self, *responses: str) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._responses:
            return ""
        return self._responses.pop(0)


class NoCallLLM:
    """Fails if any completion is requested."""

    def complete(self, prompt: str) -> str:
        raise AssertionError("complete must not be called")


def test_llm_summarizer_implements_illm_summarizer_port():
    assert isinstance(LLMSummarizer(RecordingLLM()), ILLMSummarizer)


def test_llm_summarizer_requires_an_llm_client():
    with pytest.raises(TypeError):
        LLMSummarizer()


def test_llm_summarizer_delegates_to_llm_client():
    llm = RecordingLLM("   خلاصه نهایی ")
    summarizer = LLMSummarizer(llm)

    result = summarizer.summarize("متن طولانی برای خلاصه")

    assert result == "خلاصه نهایی"
    assert len(llm.prompts) == 1
    prompt = llm.prompts[0]
    assert "متن طولانی برای خلاصه" in prompt


def test_llm_summarizer_surfaces_token_budget_in_prompt():
    llm = RecordingLLM("short")
    summarizer = LLMSummarizer(llm)

    summarizer.summarize("some text", max_tokens=120)

    assert "120" in llm.prompts[0]


def test_llm_summarizer_without_budget_omits_token_instruction():
    llm = RecordingLLM("short")
    summarizer = LLMSummarizer(llm)

    summarizer.summarize("some text")

    assert "120" not in llm.prompts[0]


def test_llm_summarizer_returns_empty_for_empty_input():
    summarizer = LLMSummarizer(NoCallLLM())

    assert summarizer.summarize("") == ""
    assert summarizer.summarize("   ") == ""


def test_llm_summarizer_honours_custom_prompts():
    llm = RecordingLLM("out")
    prompts = SummarizationPrompts(
        role="r",
        system_input="s",
        output_format="o",
        max_tokens_instruction="{max_tokens} tokens max",
    )
    summarizer = LLMSummarizer(llm, prompts=prompts)

    summarizer.summarize("text", max_tokens=7)

    prompt = llm.prompts[0]
    assert "r" in prompt
    assert "s" in prompt
    assert "o" in prompt
    assert "7 tokens max" in prompt
    assert "text" in prompt