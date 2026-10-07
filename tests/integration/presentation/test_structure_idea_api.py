"""HTTP-to-provider idea generation through the real DI and Section pipeline."""

import json
from dataclasses import dataclass, field

import httpx
import pytest
from openai import AsyncOpenAI
from transformers import AutoTokenizer

from src.containers import Container
from src.infrastructure.configs.settings import generation_settings, security_settings
from src.infrastructure.services.llm import OpenAILLMClient
from src.infrastructure.services.tokenizers.qwen_tokenizer import QwenTokenizer
from src.main import create_app


URL = "/api/v1/suggestions/expand-suggestion"
VALID_OUTPUT = (
    "{title}\nOccupancy lighting\n***\n"
    "{current problem}\nLights stay on in empty rooms.\n***\n"
    "{solutions}\nInstall occupancy sensors.\n***\n"
    "{advantage}\nPotentially lower consumption.\n***\n"
    "{disadvantage}\nInstallation cost is unknown."
)


@dataclass
class MockProvider:
    output: str = VALID_OUTPUT
    mode: str = "success"
    requests: list[dict] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        self.requests.append(json.loads(request.content))
        if self.mode == "connection_error":
            raise httpx.ConnectError("Mock provider unavailable", request=request)
        if self.mode == "api_error":
            return httpx.Response(503, json={"error": {"message": "Provider unavailable"}})
        return httpx.Response(
            200,
            json={
                "id": "chat-idea-test",
                "object": "chat.completion",
                "created": 0,
                "model": generation_settings.LLM_MODEL,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": self.output},
                    "finish_reason": "stop",
                }],
            },
        )


@pytest.fixture(scope="module")
def tokenizer():
    raw = AutoTokenizer.from_pretrained(
        generation_settings.TOKENIZER_MODEL, use_fast=True, local_files_only=True
    )
    return QwenTokenizer(raw)


@pytest.fixture
def endpoint(tokenizer):
    provider = MockProvider()
    sdk = AsyncOpenAI(
        api_key="test-only-key",
        base_url="http://provider.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider.handle)),
    )
    adapter = OpenAILLMClient(
        sdk,
        model=generation_settings.LLM_MODEL,
        temperature=generation_settings.LLM_TEMPERATURE,
        max_tokens=generation_settings.LLM_MAX_TOKENS,
    )
    container = Container()
    # Replace only external dependencies. Use case, sections, allocation,
    # ContextBuilder, message serialization, parser, and HTTP handlers are real.
    container.tokenizer.override(tokenizer)
    container.llm_client.override(adapter)
    container.wire(packages=["src.presentation.routers"])
    app = create_app(is_mock=False)
    try:
        yield app, provider, container
    finally:
        container.unwire()
        adapter.close()


async def post(endpoint, payload, *, headers=None):
    app, _, _ = endpoint
    if headers is None:
        headers = {security_settings.API_KEY_NAME: security_settings.API_KEY}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(URL, headers=headers, json=payload)


@pytest.mark.asyncio
async def test_http_endpoint_invokes_provider_and_returns_five_parsed_fields(endpoint):
    app, provider, _ = endpoint
    response = await post(endpoint, {"description": "  Install occupancy sensors.  "})
    assert response.status_code == 200
    assert response.json() == {
        "status": 200,
        "data": {
            "title": "Occupancy lighting",
            "currentProblem": "Lights stay on in empty rooms.",
            "solution": "Install occupancy sensors.",
            "advantage": "Potentially lower consumption.",
            "disadvantage": "Installation cost is unknown.",
        },
    }
    assert "X-Request-Id" in response.headers
    assert len(provider.requests) == 1
    body = provider.requests[0]
    assert body["model"] == generation_settings.LLM_MODEL
    assert body["temperature"] == generation_settings.LLM_TEMPERATURE
    assert body["max_tokens"] == generation_settings.LLM_MAX_TOKENS
    assert "response_format" not in body
    assert [message["role"] for message in body["messages"]] == ["system", "user"]
    assert body["messages"][1]["content"] == "Install occupancy sensors."
    system = body["messages"][0]["content"]
    assert VALID_OUTPUT.split("\n")[0] in system
    expected_format = (
        "{title}\nعنوان نمونه\n***\n"
        "{current problem}\nشرح نمونهٔ مشکل فعلی\n***\n"
        "{solutions}\nراهکارهای پیشنهادی نمونه\n***\n"
        "{advantage}\nمزیت نمونه\n***\n"
        "{disadvantage}\nعیب یا خطر نمونه"
    )
    assert expected_format in system
    assert "خروجی JSON، عنوان‌های مارک‌داون، بلوک کد" in system
    assert "Install occupancy sensors." not in system
    assert URL in app.openapi()["paths"]


@pytest.mark.asyncio
async def test_512_real_model_tokens_are_accepted_even_when_more_than_512_characters(endpoint, tokenizer):
    description = ("sensor " * 512).strip()
    assert len(description) > 512
    assert tokenizer.count_tokens(description) == 512
    response = await post(endpoint, {"description": description})
    assert response.status_code == 200
    assert endpoint[1].requests[0]["messages"][1]["content"] == description


@pytest.mark.asyncio
async def test_513_real_model_tokens_return_422_without_provider_call(endpoint, tokenizer):
    description = ("sensor " * 513).strip()
    assert tokenizer.count_tokens(description) == 513
    response = await post(endpoint, {"description": description})
    assert response.status_code == 422
    error = response.json()["errors"][0]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["source"]["pointer"] == "/data/description"
    assert endpoint[1].requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {}, {"description": ""}, {"description": " \t\n"},
    {"description": None}, {"description": 123}, {"description": []},
    {"description": "Sensor lighting", "extra": "not allowed"},
])
async def test_invalid_http_input_uses_validation_error_envelope(endpoint, payload):
    response = await post(endpoint, payload)
    assert response.status_code == 422
    expected_code = "MISSING_REQUIRED_FIELD" if payload == {} else "VALIDATION_ERROR"
    assert response.json()["errors"][0]["code"] == expected_code
    assert endpoint[1].requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("headers,code", [
    ({}, "API_KEY_MISSING"),
    ({security_settings.API_KEY_NAME: "invalid-test-key"}, "API_KEY_INVALID"),
])
async def test_existing_api_key_auth_is_inherited(endpoint, headers, code):
    response = await post(endpoint, {"description": "Sensor lighting"}, headers=headers)
    assert response.status_code == 401
    assert response.json()["errors"][0]["code"] == code
    assert endpoint[1].requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("output", [
    '{"title": "Invalid JSON response"}',
    VALID_OUTPUT.replace("{solutions}", "{solution}"),
    VALID_OUTPUT.replace("\n***\n", "\n---\n", 1),
    "```text\n" + VALID_OUTPUT + "\n```",
    "",
])
async def test_malformed_llm_output_returns_generation_error(endpoint, output):
    endpoint[1].output = output
    response = await post(endpoint, {"description": "Sensor lighting"})
    assert response.status_code == 500
    assert response.json()["errors"][0]["code"] == "GENERATION_FAILED"
    assert len(endpoint[1].requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,status_code,code", [
    ("connection_error", 503, "LLM_CONNECTION_FAILED"),
    ("api_error", 502, "LLM_API_ERROR"),
])
async def test_existing_provider_error_translation_is_preserved(endpoint, mode, status_code, code):
    endpoint[1].mode = mode
    response = await post(endpoint, {"description": "Sensor lighting"})
    assert response.status_code == status_code
    assert response.json()["errors"][0]["code"] == code
    assert len(endpoint[1].requests) == 1


@pytest.mark.asyncio
async def test_undersized_prompt_budget_is_processed_then_rejected_before_llm(endpoint):
    endpoint[2].structure_idea_use_case.add_kwargs(max_prompt_tokens=80)
    response = await post(endpoint, {"description": "Sensor lighting"})
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "PROMPT_BUDGET_EXCEEDED"
    assert endpoint[1].requests == []


def test_openapi_preserves_existing_contract_and_documents_provider_errors(endpoint):
    operation = endpoint[0].openapi()["paths"][URL]["post"]
    assert {"200", "401", "422", "500", "502", "503"} <= operation["responses"].keys()
    assert operation["security"]
    schemas = endpoint[0].openapi()["components"]["schemas"]
    request = schemas["StructureIdeaRequest"]
    assert request["required"] == ["description"]
    assert request["additionalProperties"] is False
    assert "maxLength" not in request["properties"]["description"]
    assert set(schemas["StructuredIdeaDataResponse"]["properties"]) == {
        "title", "currentProblem", "solution", "advantage", "disadvantage"
    }
