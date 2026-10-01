"""Run a real configured vLLM completion; failure is an error, never a skip.

Run from the repository root:
    python -m tests.integration.context_builder_vllm.live_request
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from transformers import AutoTokenizer, PreTrainedTokenizerFast

from src.application.context import ContextBuilder, OverflowStrategyDispatcher
from src.application.context.allocation import CapacityAllocator, DemandAllocator, RedistributionAllocator
from src.application.context.sections import (
    ChunksSection, HistorySection, OutputFormatSection, RoleSection,
    SystemInputSection, UserInputSection,
)
from src.application.llm.llm_request_builder import LLMRequestBuilder
from src.application.prompt import PromptBuilder
from src.infrastructure.configs.llm_provider_configs import AsyncOpenAIClientFactory
from src.infrastructure.configs.settings import (
    generation_settings, llm_settings, suggestion_analysis_settings,
)
from src.infrastructure.services.llm.openai_llm_client import OpenAILLMClient
from src.infrastructure.services.tokenizers.qwen_tokenizer import QwenTokenizer
from . import dataset
from .provider import WireRecorder
from .trace import ROOT, TraceCollector, json_text


def save_artifacts(directory: Path, trace: TraceCollector, outcome: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    safe = trace.snapshot(outcome)
    for filename, value in (
        ('execution_result.json', safe),
        ('final_request.json', safe.get('request')),
        ('provider_response.json', {'status': safe['status'], 'response': safe.get('response')}),
        ('execution_trace.json', trace.events),
    ):
        (directory / filename).write_text(json_text(value) + '\n', encoding='utf-8')
    answer = safe.get('answer')
    (directory / 'generated_answer.txt').write_text(
        answer if answer is not None else 'NO GENERATED ANSWER: real provider request failed.\n',
        encoding='utf-8',
    )
    text = [
        '# Real vLLM execution result', '',
        f"Recorded: {safe['timestamp']}", '',
        f"**Status: {safe['status']}**", '',
        f"Model: `{safe['model']}`", '',
        f"Endpoint: `{safe['endpoint']}`", '',
        f"Real inference request attempted: **{safe['request_attempted']}**", '',
        f"HTTP request body sent according to transport events: **{safe['http_body_sent']}**", '',
        f"HTTP response received: **{safe['response_received']}**", '',
        'This command uses the production client and actual configured network endpoint. '
        'It does not use a mock transport, does not fall back to another model, and does not skip inference after a failed model-list check.', '',
        '## Token accounting', '', '```json', json_text(safe.get('tokens')), '```', '',
        'The context budget covers rendered text. Chat-template input and the configured '
        'completion allowance are listed separately. Provider usage is authoritative when returned.', '',
        '## Complete final request', '', '```json', json_text(safe.get('request')), '```', '',
        '## Complete provider response', '', '```json', json_text(safe.get('response')), '```', '',
        '## Final generated output', '',
        answer if answer is not None else 'No answer was generated because the real request failed.', '',
        '## Errors and transport evidence', '', '```json',
        json_text({'error_chain': safe.get('error_chain', []), 'http_calls': safe.get('http_calls', []),
                   'transport_events': safe.get('transport_events', [])}), '```', '',
    ]
    (directory / 'live_result.md').write_text('\n'.join(text), encoding='utf-8')


def run_live(directory: Path) -> dict:
    trace = TraceCollector(secrets=(llm_settings.VLLM_API_KEY,))
    trace.scenario = 'REAL_VLLM_REQUEST'
    outcome = {
        'timestamp': datetime.now(timezone.utc).isoformat(), 'status': 'FAILED',
        'model': generation_settings.LLM_MODEL,
        'endpoint': llm_settings.VLLM_BASE_URL + '/chat/completions',
        'request_attempted': False, 'http_body_sent': False, 'response_received': False,
        'answer': None, 'response': None, 'transport_events': [],
    }
    client = None
    sdk = None
    wire = WireRecorder(trace, mode='LIVE')

    async def observe_transport(name, info):
        event = trace.emit('HTTP_TRANSPORT', name=name, details=info)
        outcome['transport_events'].append(event)
        if name.endswith('send_request_body.complete'):
            outcome['http_body_sent'] = True

    async def attach_transport_observer(request):
        request.extensions['trace'] = observe_transport

    try:
        raw = AutoTokenizer.from_pretrained(generation_settings.TOKENIZER_MODEL,
                                            use_fast=True, local_files_only=True)
        if not isinstance(raw, PreTrainedTokenizerFast):
            raise TypeError('Configured tokenizer must be a fast tokenizer')
        tokenizer = QwenTokenizer(raw)
        with trace.instrument():
            trace.emit('PIPELINE_START', configuration={
                'model': generation_settings.LLM_MODEL, 'temperature': generation_settings.LLM_TEMPERATURE,
                'max_tokens': generation_settings.LLM_MAX_TOKENS,
                'timeout': generation_settings.LLM_TIMEOUT, 'tokenizer': generation_settings.TOKENIZER_MODEL,
                'context_budget': suggestion_analysis_settings.SUGGESTION_ANALYSIS_MAX_PROMPT_TOKENS,
            })
            builder = PromptBuilder([
                RoleSection(dataset.ROLE), SystemInputSection(dataset.SYSTEM),
                ChunksSection(dataset.chunks()), HistorySection(dataset.history()[:2]),
                UserInputSection(dataset.USER), OutputFormatSection(dataset.OUTPUT),
            ], seed_defaults=False)
            context = ContextBuilder(
                tokenizer=tokenizer,
                capacity_allocator=CapacityAllocator(DemandAllocator(), RedistributionAllocator()),
                dispatcher=OverflowStrategyDispatcher(),
            ).build(builder, suggestion_analysis_settings.SUGGESTION_ANALYSIS_MAX_PROMPT_TOKENS)
            request = LLMRequestBuilder().build(
                context, model=generation_settings.LLM_MODEL,
                temperature=generation_settings.LLM_TEMPERATURE,
                max_tokens=generation_settings.LLM_MAX_TOKENS,
            )
            chat_tokens = len(raw.apply_chat_template(request['messages'], tokenize=True, add_generation_prompt=True))
            outcome.update(request=request, context=trace.snapshot(context), tokens={
                'context_budget': context.budget_tokens, 'rendered_context': context.total_tokens,
                'local_chat_template_input': chat_tokens,
                'completion_allowance': generation_settings.LLM_MAX_TOKENS,
                'input_plus_completion_allowance': chat_tokens + generation_settings.LLM_MAX_TOKENS,
                'tokenizer': generation_settings.TOKENIZER_MODEL,
                'add_special_tokens_for_context': False,
            })
            trace.check('Rendered context fits configured budget', context.total_tokens <= context.budget_tokens, True)
            sdk = AsyncOpenAIClientFactory.create_client(generation_settings.LLM_PROVIDER, generation_settings.LLM_TIMEOUT)
            if generation_settings.LLM_PROVIDER.strip().lower() != 'vllm':
                raise ValueError('Real vLLM validation requires LLM_PROVIDER=vllm')
            wire.attach(sdk)
            sdk._client.event_hooks['request'].append(attach_transport_observer)
            client = OpenAILLMClient(sdk, model=generation_settings.LLM_MODEL,
                                     temperature=generation_settings.LLM_TEMPERATURE,
                                     max_tokens=generation_settings.LLM_MAX_TOKENS)
            outcome['request_attempted'] = True
            answer = asyncio.run(client.complete_chat(request['messages']))
            call = wire.calls[-1]
            outcome.update(answer=answer, response=call.get('response'), response_received=True)
            outcome['tokens']['provider_usage'] = call.get('response', {}).get('usage')
            trace.check('Actual HTTP body equals request builder output', call['payload'], request)
            trace.check('Real provider returned HTTP 200', call['status'], 200)
            trace.check('Real provider returned a nonempty answer', bool(answer.strip()), True)
            trace.check('Actual response content was extracted unchanged', answer,
                        call['response']['choices'][0]['message']['content'])
            if call['response']['choices'][0].get('finish_reason') == 'length':
                trace.emit('WARNING', reason='Real response reached configured completion token limit')
            outcome['status'] = 'PASS'
            trace.emit('PIPELINE_END', answer=answer, status='PASS')
    except Exception as error:
        wire.failed_requests(error)
        chain = []
        current = error
        seen = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            chain.append(trace.snapshot(current))
            current = current.__cause__ or current.__context__
        outcome['error_chain'] = chain
        trace.emit('ERROR', error_chain=chain, status='FAILED')
    finally:
        if client is not None:
            client.close()
        elif sdk is not None:
            asyncio.run(sdk.close())
        outcome['http_calls'] = wire.calls
        outcome['response_received'] = any('status' in call for call in wire.calls)
        if outcome['response'] is None and wire.calls:
            outcome['response'] = wire.calls[-1].get('response')
        save_artifacts(directory, trace, outcome)
    return outcome


if __name__ == '__main__':
    target = ROOT / 'tests/reports/context_builder_vllm/live_validation'
    result = run_live(target)
    print(json.dumps({key: result[key] for key in ('status', 'model', 'request_attempted', 'http_body_sent', 'response_received')}))
    print(f'Full live result: {target / "live_result.md"}')
    raise SystemExit(0 if result['status'] == 'PASS' else 1)
