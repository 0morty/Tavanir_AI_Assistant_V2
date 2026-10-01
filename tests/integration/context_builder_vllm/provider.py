"""Wire observation for the real SDK, plus explicit controlled provider doubles."""
from __future__ import annotations

import asyncio
import json
import re
import time

import httpx
from openai import AsyncOpenAI

from src.infrastructure.configs.llm_provider_configs import AsyncOpenAIClientFactory
from src.infrastructure.configs.settings import generation_settings, llm_settings
from src.infrastructure.services.llm.openai_llm_client import OpenAILLMClient
from .dataset import FACTS
from .trace import TraceCollector


class WireRecorder:
    def __init__(self, trace: TraceCollector, *, mode: str) -> None:
        self.trace = trace
        self.mode = mode
        self.calls: list[dict] = []
        self._pending: dict[int, tuple[dict, float]] = {}

    async def request(self, request) -> None:
        body = json.loads(request.content) if request.content else None
        record = {"provider": "vllm" if self.mode == "LIVE" else "controlled-http-double",
                  "mode": self.mode, "endpoint": str(request.url), "method": request.method,
                  "payload": body, "scenario": self.trace.scenario}
        self.calls.append(record)
        self._pending[id(request)] = (record, time.perf_counter())
        self.trace.emit("VLLM_REQUEST", component="HTTP", function="send", **record)

    async def response(self, response) -> None:
        await response.aread()
        record, started = self._pending.pop(id(response.request))
        try:
            body = response.json()
        except ValueError:
            body = response.text
        record.update(status=response.status_code, response=body,
                      latency_seconds=time.perf_counter() - started)
        self.trace.emit("VLLM_RESPONSE", component="HTTP", function="receive", **record)

    def attach(self, sdk: AsyncOpenAI) -> None:
        # Test-only observation on the actual factory-created pooled HTTP client.
        sdk._client.event_hooks["request"].append(self.request)
        sdk._client.event_hooks["response"].append(self.response)

    def failed_requests(self, error: Exception) -> None:
        for record, started in self._pending.values():
            record.update(error=self.trace.snapshot(error), latency_seconds=time.perf_counter() - started)
            self.trace.emit("HTTP_ERROR", component="HTTP", **record)
        self._pending.clear()


def completion(content: str, *, index: int = 0) -> dict:
    return {"index": index, "message": {"role": "assistant", "content": content},
            "finish_reason": "stop"}


class ControlledProvider:
    """No network: deterministic summaries, shuffled batch responses and fault injection."""
    def __init__(self, *, fault: str | None = None) -> None:
        self.fault = fault
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        self.requests.append(payload)
        if self.fault == "unavailable":
            raise httpx.ConnectError("Controlled provider is unavailable", request=request)
        if self.fault == "invalid_response":
            return httpx.Response(200, json={"choices": []})
        if self.fault == "unauthorized":
            return httpx.Response(401, json={"error": {"message": "Controlled authentication failure"}})
        batch = request.url.path.endswith("/batch")
        if batch and self.fault == "batch_404":
            return httpx.Response(404, json={"error": {"message": "Batch endpoint unavailable"}})
        conversations = payload["messages"] if batch else [payload["messages"]]
        choices = []
        for index, conversation in enumerate(conversations):
            prompt = "\n".join(message["content"] for message in conversation)
            matches = re.findall(r"Evidence ([A-E])\.", prompt)
            label = matches[0] if matches else None
            content = (f"Evidence {label}. {FACTS[label]}" if label else
                       "Pilot maintenance improvements and measure reliability before wider adoption.")
            if self.fault == "empty_summary":
                content = " "
            if self.fault == "oversized_summary":
                content = prompt
            choices.append(completion(content, index=index))
        if batch:
            choices.reverse()  # Production adapter must restore the indexed order.
        return httpx.Response(200, json={"id": "controlled-completion", "object": "chat.completion",
                                        "created": 0, "model": payload["model"], "choices": choices})


def controlled_client(trace: TraceCollector, *, fault: str | None = None):
    provider = ControlledProvider(fault=fault)
    recorder = WireRecorder(trace, mode="CONTROLLED")
    sdk = AsyncOpenAI(api_key="controlled-not-a-secret", base_url="http://controlled.invalid/v1",
                      max_retries=0,
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider)))
    recorder.attach(sdk)
    client = OpenAILLMClient(sdk, model=generation_settings.LLM_MODEL, temperature=0.0, max_tokens=96)
    return client, recorder, provider


def live_client(trace: TraceCollector):
    recorder = WireRecorder(trace, mode="LIVE")
    sdk = AsyncOpenAIClientFactory.create_client("vllm", generation_settings.LLM_TIMEOUT)
    recorder.attach(sdk)
    return (OpenAILLMClient(sdk, model=generation_settings.LLM_MODEL,
                            temperature=0.0, max_tokens=96), recorder)


async def preflight(trace: TraceCollector) -> dict:
    trace.scenario = "vllm_preflight"
    state = {"reachable": "NO", "configured_model": generation_settings.LLM_MODEL,
             "endpoint": llm_settings.VLLM_BASE_URL + "/chat/completions", "ready": False}
    recorder = WireRecorder(trace, mode="LIVE")
    sdk = None
    try:
        sdk = AsyncOpenAIClientFactory.create_client("vllm", min(5.0, generation_settings.LLM_TIMEOUT))
        # A lightweight preflight should not consume the production retry interval.
        sdk.max_retries = 0
        recorder.attach(sdk)
        models = await sdk.models.list()
        state.update(reachable="YES", models=models.model_dump(mode="json"))
        selected = next((model for model in models.data if model.id == generation_settings.LLM_MODEL), None)
        state["ready"] = selected is not None
        if selected is None:
            state["reason"] = "Configured model is not advertised; no substitute model selected."
        else:
            state["max_model_len"] = getattr(selected, "max_model_len", None)
    except Exception as error:
        recorder.failed_requests(error)
        state["reason"] = trace.snapshot(error)
    finally:
        if sdk is not None:
            await sdk.close()
    trace.emit("PREFLIGHT", **state)
    return state


def send_chat(client: OpenAILLMClient, messages: list[dict[str, str]]) -> str:
    return asyncio.run(client.complete_chat(messages))
