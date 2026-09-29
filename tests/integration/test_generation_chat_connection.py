"""Final Generation runs through a real SDK adapter with a local HTTP mock."""

import json

import httpx
import pytest
from openai import AsyncOpenAI

from src.application.context import ContextBuilder, OverflowStrategyDispatcher
from src.application.context.allocation import (
    CapacityAllocator,
    DemandAllocator,
    RedistributionAllocator,
)
from src.application.dtos import (
    CurrentSuggestionInput,
    GenerationInput,
    SimilarSuggestionInput,
)
from src.application.exceptions import LLMUnknownCitationError
from src.application.interfaces.i_llm_client import ILLMClient
from src.application.llm import LLMRequestBuilder
from src.application.prompt import SuggestionAnalysisPromptConfig, SuggestionPromptPreparer
from src.application.use_cases.generate_suggestion_use_case import (
    GenerateSuggestionUseCase,
)
from src.domain.context.tokenizer import Tokenizer
from src.domain.enums import SuggestionStatus
from src.infrastructure.services.llm import OpenAILLMClient
from src.infrastructure.services.llm.output_parser import GenerationOutputParser


class CharacterTokenizer(Tokenizer):
    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        return [(ord(char), (index, index + 1)) for index, char in enumerate(text)]

    def count_tokens(self, text: str) -> int:
        return len(text)


def generation_input() -> GenerationInput:
    return GenerationInput(
        current_suggestion=CurrentSuggestionInput(
            title="مدیریت شبکه برق",
            problem="افت ولتاژ در شبکه توزیع منطقه",
            solution="نصب کنترلگر هوشمند برای تنظیم ولتاژ",
        ),
        similar_suggestions=[
            SimilarSuggestionInput(
                id="SUG-1",
                status=SuggestionStatus.APPROVED,
                title="کنترل ولتاژ شبکه",
                problem="افت ولتاژ در خطوط توزیع",
                solution="استفاده از کنترلگر مرکزی",
                similarity=0.9,
            ),
            SimilarSuggestionInput(
                id="SUG-2",
                status=SuggestionStatus.PENDING,
                title="پایش شبکه توزیع",
                problem="پایش ناکافی شبکه توزیع",
                solution="افزودن سنسورهای ولتاژ",
                similarity=0.8,
            ),
        ],
    )


def preparer() -> SuggestionPromptPreparer:
    tokenizer = CharacterTokenizer()
    return SuggestionPromptPreparer(
        context_builder=ContextBuilder(
            tokenizer=tokenizer,
            capacity_allocator=CapacityAllocator(
                DemandAllocator(), RedistributionAllocator()
            ),
            dispatcher=OverflowStrategyDispatcher(),
        ),
        tokenizer=tokenizer,
        config=SuggestionAnalysisPromptConfig(),
    )


@pytest.mark.asyncio
async def test_final_generation_sends_roles_and_returns_original_cited_item():
    input_data = generation_input()
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        content = json.dumps(
            {
                "answer": "این پیشنهاد نیاز به بررسی بیشتر دارد.",
                "citations": ["[similar 002]", "[similar 002]"],
                "uncertainty": "داده‌های اجرایی محدود است.",
            },
            ensure_ascii=False,
        )
        return httpx.Response(
            200,
            json={
                "id": "chat-test",
                "object": "chat.completion",
                "created": 0,
                "model": "test-model",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": content},
                     "finish_reason": "stop"}
                ],
            },
        )

    sdk = AsyncOpenAI(
        api_key="test-key",
        base_url="http://provider.test/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    client = OpenAILLMClient(sdk, model="test-model", temperature=0.2, max_tokens=300)
    try:
        use_case = GenerateSuggestionUseCase(
            prompt_preparer=preparer(),
            request_builder=LLMRequestBuilder(),
            llm_client=client,
            output_parser=GenerationOutputParser(),
            max_prompt_tokens=10000,
        )
        result = await use_case.execute(input_data)
    finally:
        client.close()

    assert result.answer == "این پیشنهاد نیاز به بررسی بیشتر دارد."
    assert result.citations == [input_data.similar_suggestions[1]]
    assert result.citations[0] is input_data.similar_suggestions[1]
    assert result.uncertainty == "داده‌های اجرایی محدود است."
    assert len(requests) == 1
    assert requests[0]["model"] == "test-model"
    assert [message["role"] for message in requests[0]["messages"]] == ["system", "user"]
    assert "مدیریت شبکه برق" in requests[0]["messages"][1]["content"]
    assert "[similar 002]" in requests[0]["messages"][1]["content"]
    assert "مدیریت شبکه برق" not in requests[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_generation_rejects_citation_removed_by_prompt_fitting():
    class ScriptedClient(ILLMClient):
        def complete(self, prompt: str) -> str:
            raise AssertionError("The synchronous helper API must not be used")

        async def complete_chat(self, messages):
            return '{"answer":"yes","citations":["[similar 002]"]}'

    input_data = generation_input()
    prompt_preparer = preparer()
    full = prompt_preparer.prepare_with_citations(input_data, 10000)
    narrowed_budget = full.context.total_tokens - 25
    narrowed = prompt_preparer.prepare_with_citations(input_data, narrowed_budget)
    assert list(narrowed.citation_map) == ["[similar 001]"]
    assert narrowed.citation_map["[similar 001]"] is input_data.similar_suggestions[0]

    use_case = GenerateSuggestionUseCase(
        prompt_preparer=prompt_preparer,
        request_builder=LLMRequestBuilder(),
        llm_client=ScriptedClient(),
        output_parser=GenerationOutputParser(),
        max_prompt_tokens=narrowed_budget,
    )
    with pytest.raises(LLMUnknownCitationError):
        await use_case.execute(input_data)


def test_generation_requires_injected_collaborators():
    with pytest.raises(TypeError):
        GenerateSuggestionUseCase()
