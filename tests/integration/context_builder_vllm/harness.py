"""Composition and independent assertions for the production pipeline."""
from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import platform
import subprocess
import sys
from pathlib import Path

from transformers import AutoTokenizer, PreTrainedTokenizerFast

from src.application.context import ContextBuilder, OverflowStrategyDispatcher
from src.application.context.allocation import CapacityAllocator, DemandAllocator, RedistributionAllocator
from src.application.context.sections import ChunksSection, UserInputSection
from src.application.exceptions import ChunkSummarizationError, LLMAPIError, LLMConnectionError
from src.application.llm.llm_request_builder import LLMRequestBuilder
from src.application.prompt import PromptBuilder
from src.domain.enums import OverflowStrategy
from src.infrastructure.configs.settings import generation_settings, llm_settings
from src.infrastructure.services.summarizers.chunk_prompt_builder import ChunkPromptBuilder, ChunkSummarizationPrompts
from src.infrastructure.services.summarizers.llm_chunk_summarizer import LLMChunkSummarizer
from src.infrastructure.services.summarizers.llm_summarizer import LLMSummarizer, SummarizationPrompts
from src.infrastructure.services.tokenizers.qwen_tokenizer import QwenTokenizer
from . import dataset
from .provider import controlled_client, live_client, preflight, send_chat
from .scenarios import SCENARIOS, make_scenario, stack
from .trace import ROOT, TraceCollector


def context_builder(tokenizer) -> ContextBuilder:
    return ContextBuilder(tokenizer=tokenizer,
                          capacity_allocator=CapacityAllocator(DemandAllocator(), RedistributionAllocator()),
                          dispatcher=OverflowStrategyDispatcher())


def summarizers(client):
    chunk = LLMChunkSummarizer(client, batch_size=2, max_attempts=2,
                              builder=ChunkPromptBuilder(ChunkSummarizationPrompts(
                                  role="You summarize one independent English maintenance record.",
                                  system_input="Preserve its evidence letter, key numbers and uncertainty. "
                                               "Do not combine this record with another record.",
                                  output_format="Return one English sentence of at most 30 words.")))
    text = LLMSummarizer(client, prompts=SummarizationPrompts(
        role="You summarize English engineering evidence faithfully.",
        system_input="Keep the evidence letter and key observed result. Return one short sentence.",
        output_format="Return only the English summary.",
        max_tokens_instruction="Use at most {max_tokens} tokens."))
    return text, chunk


class PipelineAudit:
    def __init__(self, *, live: bool) -> None:
        self.live_requested = live
        self.completed = False
        self.trace = TraceCollector(secrets=(llm_settings.VLLM_API_KEY,))
        self.preflight: dict = {"reachable": "NOT CHECKED", "ready": False,
                                "reason": "Live mode was not requested."}
        self.results: dict[str, dict] = {}
        self.failures: list[dict] = []
        self.raw = AutoTokenizer.from_pretrained(generation_settings.TOKENIZER_MODEL,
                                                use_fast=True, local_files_only=True)
        if not isinstance(self.raw, PreTrainedTokenizerFast):
            raise TypeError("Configured production tokenizer must be fast")
        self.tokenizer = QwenTokenizer(self.raw)
        tokenizer_file = Path(generation_settings.TOKENIZER_MODEL) / "tokenizer.json"
        import_probe = subprocess.run(
            [sys.executable, "-c", "from src.application.prompt import PromptBuilder"],
            cwd=ROOT, text=True, capture_output=True, timeout=30,
        )
        self.metadata = {
            "prompt_first_import_probe": {"exit_code": import_probe.returncode,
                                          "stderr": import_probe.stderr},
            "test": "ContextBuilder to vLLM full execution audit", "python": platform.python_version(),
            "platform": platform.platform(),
            "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "versions": {name: importlib.metadata.version(name) for name in
                         ("pytest", "openai", "httpx", "transformers", "tokenizers")},
            "model": generation_settings.LLM_MODEL, "provider": generation_settings.LLM_PROVIDER,
            "endpoint": llm_settings.VLLM_BASE_URL + "/chat/completions",
            "tokenizer": {"implementation": "QwenTokenizer", "raw_implementation": type(self.raw).__name__,
                          "model": generation_settings.TOKENIZER_MODEL, "use_fast": True,
                          "local_files_only": True, "add_special_tokens": False,
                          "return_offsets_mapping": True, "special_tokens": self.raw.special_tokens_map,
                          "chat_template": self.raw.chat_template,
                          "sha256": hashlib.sha256(tokenizer_file.read_bytes()).hexdigest()},
            "generation": {"temperature": 0.0, "max_tokens": 96, "timeout": generation_settings.LLM_TIMEOUT,
                           "max_retries": llm_settings.MAX_RETRIES},
            "accounting": "ContextBuilder counts rendered text without chat-template tokens. "
                          "It reserves (registered sections - 1) separator token counts, then allocates once. "
                          "Chat-template tokens and the 96 output tokens are reported separately.",
        }

    def run(self) -> None:
        with self.trace.instrument():
            self.trace.emit("PIPELINE_START", metadata=self.metadata)
            if self.live_requested:
                self.preflight = asyncio.run(preflight(self.trace))
            for name in SCENARIOS:
                self._isolated(name, live=False)
            self.negative_cases()
            if self.preflight["ready"]:
                for name in SCENARIOS:
                    self._isolated(name, live=True)
            else:
                self.trace.emit("WARNING", reason=self.preflight["reason"],
                                decision="Real final inference NOT EXECUTED; controlled calls do not prove live integration.")
            self.completed = True
            self.trace.scenario = "final"
            self.trace.emit("PIPELINE_END", results=self.results, failures=self.failures,
                            live_preflight=self.preflight, status=self.status)

    @property
    def status(self) -> str:
        if self.failures:
            return "FAILED"
        if not self.completed:
            return "INCOMPLETE: audit did not finish"
        if not self.preflight["ready"]:
            return "PARTIAL: live inference NOT EXECUTED"
        live_results = [v for k, v in self.results.items() if k.startswith("LIVE/")]
        return "PASS" if any(v.get("inference") == "EXECUTED" for v in live_results) else "PARTIAL"

    def _isolated(self, name: str, *, live: bool) -> None:
        key = ("LIVE/" if live else "CONTROLLED/") + name
        self.trace.scenario = key
        try:
            self.run_scenario(name, live=live)
        except Exception as error:
            failure = {"scenario": key, "error": self.trace.snapshot(error)}
            self.failures.append(failure)
            self.trace.emit("ERROR", classification="UNEXPECTED FAILURE", **failure)
            self.results.setdefault(key, {}).update(status="FAIL", error=failure["error"])

    def run_scenario(self, name: str, *, live: bool) -> None:
        trace = self.trace
        client, wire = live_client(trace) if live else controlled_client(trace)[:2]
        try:
            text_summarizer, chunk_summarizer = summarizers(client)
            scenario = make_scenario(name, self.tokenizer, text_summarizer, chunk_summarizer)
            builder = scenario.builder
            before = trace.snapshot(builder)
            original = {section.section_type: section.prepare() for section in builder.sections}
            trace.emit("SCENARIO", name=name, purpose=scenario.purpose, context_limit=scenario.budget)
            for section in builder.sections:
                prepared = original[section.section_type]
                trace.emit("SECTION_CREATED", section_type=section.section_type, configuration=section,
                           input=prepared, initial_tokens=self.tokenizer.count_tokens(prepared.content))
            start = len(trace.events)
            result = context_builder(self.tokenizer).build(builder, scenario.budget)
            build_events = trace.events[start:]
            trace.emit("CONTEXTBUILDER_RESULT", output=result)
            trace.check("Registered section order survives ContextBuilder", [s.section_type for s in result.sections],
                        [s.section_type for s in builder.sections])
            trace.check("Source sections and items remain unchanged", trace.snapshot(builder), before)
            count = len(self.raw.encode(result.prompt, add_special_tokens=False))
            trace.check("Final token total matches independently invoked configured HF tokenizer", result.total_tokens, count)
            trace.check("Final rendered context respects the context budget", count <= scenario.budget, True)
            separator_tokens = self.tokenizer.count_tokens(builder.SECTION_SEPARATOR)
            reserved = max(0, len(builder.sections) - 1) * separator_tokens
            remaining = max(0, scenario.budget - reserved)
            trace.emit("ALLOCATION_START", phase="post-build accounting reconciliation",
                       source_step=next(e["step"] for e in build_events if e["event"] == "CALL" and e["function"] == "ContextBuilder.build"),
                       context_limit=scenario.budget, reserved_tokens=reserved,
                       usable_capacity=remaining)
            for output in result.sections:
                remaining -= output.fitted_tokens
                trace.check(f"{output.section_type} fits its allocation", output.fitted_tokens <= output.capacity_tokens, True)
                trace.check(f"{output.section_type} exact token accounting", output.fitted_tokens,
                            len(self.raw.encode(output.content, add_special_tokens=False)))
                trace.check(f"{output.section_type} overflow flag", output.overflowed,
                            output.requested_tokens > output.capacity_tokens)
                if not output.overflowed:
                    trace.check(f"{output.section_type} unfitted content preserved", output.content,
                                original[output.section_type].content)
                trace.emit("ALLOCATION_DECISION", section=output.section_type,
                           original_tokens=output.requested_tokens, available_tokens=output.capacity_tokens,
                           consumed_tokens=output.fitted_tokens, saved_tokens=output.requested_tokens-output.fitted_tokens,
                           remaining_tokens=remaining, overflow=output.overflowed,
                           overflow_amount=max(0, output.requested_tokens-output.capacity_tokens))
                if output.section_type == "CHUNKS":
                    ids = [item.chunk_id for item in output.items]
                    source_ids = [item.chunk_id for item in original["CHUNKS"].items]
                    trace.check("Chunk order remains an original prefix", ids, source_ids[:len(ids)])
                    trace.check("Citations remain aligned with retained evidence", list(output.citation_ids),
                                list(original["CHUNKS"].citation_ids[:len(ids)]))
            operations = self.record_transformations(build_events)
            if scenario.expected_strategy:
                trace.check("Required overflow strategy was actually dispatched",
                            scenario.expected_strategy in operations, True)
            self.scenario_assertions(name, result, original, build_events, wire, live=live)
            request_start = len(trace.events)
            trace.emit("REQUEST_BUILD_START", input=result)
            request = LLMRequestBuilder().build(result, model=generation_settings.LLM_MODEL,
                                                temperature=0.0, max_tokens=96)
            request_events = trace.events[request_start:]
            trace.emit("REQUEST_BUILT", input=result, output=request)
            trace.check("Request construction does not render, refit, retrieve or tokenize content",
                        [e["function"] for e in request_events if e["event"] == "CALL" and
                         e["component"] != "src.application.llm.llm_request_builder" and
                         not e["function"].endswith("history_messages")], [])
            expected = self.expected_messages(result)
            trace.check("Exact system/history/user grouping and fitted contents survive serialization",
                        request["messages"], expected)
            trace.check("All mock prompt text is English/ASCII", all(m["content"].isascii() for m in expected), True)
            chat_tokens = len(self.raw.apply_chat_template(expected, tokenize=True, add_generation_prompt=True)) if expected else 0
            state = {"status": "PASS", "context": trace.snapshot(result), "request": request,
                     "chat_template_tokens": chat_tokens, "output_reservation": 96,
                     "context_builder": "EXECUTED", "request_builder": "EXECUTED", "inference": "NOT EXECUTED",
                     "reason": "Controlled run validates HTTP serialization; not real inference."}
            self.results[trace.scenario] = state
            trace.emit("TOKEN_ACCOUNTING", context_tokens=count, chat_template_tokens=chat_tokens,
                       output_reserved=96, total_provider_reservation=chat_tokens + 96,
                       decision="ContextBuilder's text budget excludes provider chat framing and completion tokens.")
            if expected:
                if live and self.preflight.get("max_model_len"):
                    trace.check("Provider window includes chat framing and output reservation",
                                chat_tokens + 96 <= self.preflight["max_model_len"], True)
                wire_start = len(wire.calls)
                state["inference"] = "ATTEMPTED" if live else "CONTROLLED ONLY"
                try:
                    response = send_chat(client, request["messages"])
                except Exception as error:
                    wire.failed_requests(error)
                    state["inference"] = "FAILED" if live else "CONTROLLED FAILURE"
                    if len(wire.calls) > wire_start:
                        state["wire_request"] = wire.calls[-1]["payload"]
                        if "response" in wire.calls[-1]:
                            state["response"] = wire.calls[-1]["response"]
                    raise
                sent = wire.calls[wire_start:]
                trace.check("Exactly one final HTTP request", len(sent), 1)
                trace.check("Actual serialized HTTP payload equals LLMRequestBuilder output", sent[0]["payload"], request)
                trace.check("Final HTTP succeeded", sent[0]["status"], 200)
                choices = sent[0]["response"]["choices"]
                trace.check("Response includes choices", bool(choices), True)
                trace.check("Response role is assistant", choices[0]["message"]["role"], "assistant")
                trace.check("Adapter extracts response content exactly", response, choices[0]["message"]["content"])
                trace.check("Response content is nonempty", bool(response.strip()), True)
                state.update(inference="EXECUTED" if live else "CONTROLLED ONLY", response=sent[0]["response"],
                             wire_request=sent[0]["payload"], extracted_content=response)
                if live:
                    state.pop("reason", None)
                if choices[0].get("finish_reason") == "length":
                    trace.emit("WARNING", reason="Provider response reached the explicit 96-token output cap.")
            else:
                state["reason"] = "Empty boundary scenario produces no messages; production client rejects empty chats."
            trace.emit("SCENARIO_END", state=state)
        finally:
            client.close()

    @staticmethod
    def expected_messages(result) -> list[dict[str, str]]:
        # Independent contract oracle: user evidence has its own message group.
        groups = {"system": [], "user": []}
        history = []
        for output in result.sections:
            if output.section_type == "HISTORY":
                history += [{"role": item.role.value, "content": item.content} for item in output.items]
            elif output.content:
                role = "user" if output.section_type in {"USER-INPUT", "SIMILAR-SUGGESTIONS"} else "system"
                groups[role].append(output.content)
        system = [{"role": "system", "content": result.section_separator.join(groups["system"])}] if groups["system"] else []
        user = [{"role": "user", "content": result.section_separator.join(groups["user"])}] if groups["user"] else []
        return system + history + user

    def record_transformations(self, events: list[dict]) -> list[str]:
        calls = {e["call_id"]: e for e in events if e["event"] == "CALL"}
        strategies = []
        for event in events:
            if event["event"] != "RETURN" or event["call_id"] not in calls:
                continue
            call = calls[event["call_id"]]
            args = call["arguments"]
            if event["function"] == "OverflowStrategyDispatcher.apply":
                content, output = args["content"], event["result"]
                strategy = str(args["strategy"]).upper()
                strategies.append(strategy)
                original_tokens = self.tokenizer.count_tokens(content["content"])
                final_tokens = self.tokenizer.count_tokens(output["content"]) if output else None
                self.trace.emit("STRATEGY_SELECTED", source_step=call["step"], strategy=strategy,
                                input=content, output=output, original_tokens=original_tokens,
                                available_tokens=args["capacity_tokens"], final_tokens=final_tokens,
                                tokens_saved=original_tokens-final_tokens if output else None,
                                saving_ratio=(original_tokens-final_tokens)/original_tokens if output and original_tokens else None,
                                decision="accepted" if output is not None and final_tokens <= args["capacity_tokens"] else "continue stack")
                if strategy == "TRUNCATE" and content["items"] is None:
                    encoding = self.raw(content["content"], add_special_tokens=False, return_offsets_mapping=True)
                    capacity = args["capacity_tokens"]
                    boundary = encoding["offset_mapping"][capacity-1][1] if capacity > 0 else 0
                    expected = content["content"][:boundary]
                    self.trace.check("TRUNCATE uses an exact original token-offset prefix", output["content"], expected)
                    self.trace.emit("TRUNCATION_RESULT", cutoff_character=boundary, target_tokens=capacity,
                                    original_tokens=original_tokens, final_tokens=final_tokens,
                                    removed_tokens=original_tokens-final_tokens, preserved=expected,
                                    discarded=content["content"][boundary:])
                elif strategy == "IGNORE" and output is not None:
                    self.trace.emit("IGNORE_DECISION", retained=output["items"],
                                    discarded=content["items"][len(output["items"]):],
                                    recovered_tokens=original_tokens-final_tokens,
                                    reason="Trailing whole items removed to fit allocated capacity")
            elif event["function"] == "LLMChunkSummarizer.summarize_chunks" and event["result"] is not None:
                chunks, summaries = args["chunks"], event["result"]
                self.trace.check("One returned summary per independent item", len(summaries), len(chunks))
                for index, (source, summary) in enumerate(zip(chunks, summaries)):
                    before, after = self.tokenizer.count_tokens(source), self.tokenizer.count_tokens(summary)
                    self.trace.emit("SUMMARIZATION_MAPPING", source_step=call["step"], item_index=index,
                                    input=source, output=summary, original_tokens=before, summary_tokens=after,
                                    tokens_saved=before-after, saving_ratio=(before-after)/before if before else 0)
        return strategies

    def scenario_assertions(self, name, result, original, events, wire, *, live):
        trace = self.trace
        if name in {"A_everything_fits", "J_ordering", "I_boundary_equal", "I_boundary_under"}:
            trace.check("Fit scenario has no overflow", any(s.overflowed for s in result.sections), False)
        if name in {"B_small_overflow", "I_boundary_over"}:
            trace.check("One-token overflow is detected", result.sections[0].requested_tokens-result.sections[0].capacity_tokens, 1)
        if name == "E_ignore":
            trace.check("Correct evidence prefix retained", [item.chunk_id for item in result.sections[0].items], ["chunk-A", "chunk-B"])
        if name == "G_history":
            trace.check("History fitting removes newest turns first", result.sections[0].items, tuple(dataset.history()[:3]))
            trace.emit("HISTORY_PROCESSING", input=dataset.history(), output=result.sections[0].history_messages)
        if name == "H_chunk_summaries" and not live:
            output = result.sections[0]
            trace.check("All five independent summaries fit and remain aligned", [i.chunk_id for i in output.items],
                        [f"chunk-{label}" for label in dataset.FACTS])
            trace.check("Each summary belongs to its own source", [i.content for i in output.items],
                        [f"Evidence {label}. {fact}" for label, fact in dataset.FACTS.items()])
            trace.check("Production batching is 2, 2, 1", [len(c["payload"]["messages"]) for c in wire.calls], [2, 2, 1])
        if name == "F_severe":
            calls = [e for e in events if e["event"] == "CALL"]
            trace.check("Severe overflow dispatches all three strategies",
                        {str(e["arguments"]["strategy"]).upper() for e in calls if e["function"] == "OverflowStrategyDispatcher.apply"},
                        {"SUMMARIZE", "TRUNCATE", "IGNORE"})
            trace.check("Strategy restart loop is bounded", sum(e["function"] == "OverflowStrategyDispatcher.apply" for e in calls) <= 12, True)
            trace.emit("OBSERVATION", classification="expected behavior",
                       detail="ContextBuilder allocates once. Redistribution loops internally. Overflow retries operate on the original prepared input, not a cumulative summary.")

    def expect_error(self, name, expected_type, action):
        self.trace.scenario = "NEGATIVE/" + name
        try:
            action()
        except expected_type as error:
            self.trace.emit("EXPECTED_FAILURE", expected=expected_type.__name__, actual=error,
                            recovery="Failure isolated; remaining scenarios continue.")
            self.trace.check("Expected failure type", isinstance(error, expected_type), True)
        except Exception as error:
            self.failures.append({"scenario": self.trace.scenario, "error": self.trace.snapshot(error)})
            self.trace.emit("ERROR", classification="UNEXPECTED FAILURE", error=error)
        else:
            failure = {"scenario": self.trace.scenario, "error": "Expected exception was not raised"}
            self.failures.append(failure)
            self.trace.emit("ERROR", classification="UNEXPECTED FAILURE", **failure)

    def negative_cases(self):
        self.expect_error("invalid_section", ValueError, lambda: UserInputSection("English", demand=1.1))
        self.expect_error("impossible_budget", ValueError,
                          lambda: context_builder(self.tokenizer).build(PromptBuilder(), -1))

        class FailingTokenizer(QwenTokenizer):
            def count_tokens(self, text):
                raise RuntimeError("Controlled tokenizer failure")

        self.expect_error("tokenizer_failure", RuntimeError,
                          lambda: context_builder(FailingTokenizer(self.raw)).build(PromptBuilder(), 20))
        for fault, expected_type in (("unavailable", LLMConnectionError), ("invalid_response", LLMAPIError)):
            self.trace.scenario = "NEGATIVE/" + fault
            client, wire, _ = controlled_client(self.trace, fault=fault)
            try:
                def invoke():
                    try:
                        return send_chat(client, [{"role": "user", "content": "English failure probe"}])
                    except Exception as error:
                        wire.failed_requests(error)
                        raise
                self.expect_error(fault, expected_type, invoke)
            finally:
                client.close()
        self.trace.scenario = "NEGATIVE/empty_summary"
        client, _, provider = controlled_client(self.trace, fault="empty_summary")
        try:
            _, summarizer = summarizers(client)
            self.expect_error("empty_summary", ChunkSummarizationError,
                              lambda: summarizer.summarize_chunks(["Evidence A. Calibration results."], capacity_tokens=50))
            self.trace.check("Empty summary retries stop at configured maximum", len(provider.requests), 2)
        finally:
            client.close()
        self.trace.scenario = "NEGATIVE/batch_404_fallback"
        client, wire, _ = controlled_client(self.trace, fault="batch_404")
        try:
            _, summarizer = summarizers(client)
            sources = [f"Evidence {label}. {fact}" for label, fact in list(dataset.FACTS.items())[:2]]
            returned = summarizer.summarize_chunks(sources, capacity_tokens=100)
            self.trace.check("404 batch fallback preserves item order", returned, sources)
            self.trace.check("404 fallback makes two individual requests", [c["status"] for c in wire.calls], [404, 200, 200])
            self.trace.emit("EXPECTED_FAILURE", expected="404 batch endpoint", actual=404,
                            recovery="Production adapter used concurrent individual completions.")
        finally:
            client.close()
