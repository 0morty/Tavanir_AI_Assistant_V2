"""A diagnostic, end-to-end ContextBuilder test with deterministic external seams."""

from __future__ import annotations

import os
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from pprint import pformat

from src.application.context import ContextBuilder, OverflowStrategyDispatcher
from src.application.context.allocation import (
    CapacityAllocator,
    DemandAllocator,
    RedistributionAllocator,
)
from src.application.context.sections import (
    ChunksSection,
    HistorySection,
    OutputFormatSection,
    RoleSection,
    SystemInputSection,
    UserInputSection,
)
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.application.prompt import PromptBuilder
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import GenerationChunk, HistoryMessage, Reference
from src.domain.enums import HistoryRole, OverflowStrategy
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class CharacterTokenizer(Tokenizer):
    """One character per token, with exact offsets for real truncation."""

    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        return [(ord(character), (index, index + 1)) for index, character in enumerate(text)]

    def count_tokens(self, text: str) -> int:
        return len(text)


@dataclass(frozen=True)
class SourceReference(Reference):
    label: str

    @property
    def description(self) -> str:
        return f"Provenance for {self.label}"

    def fluent_text(self) -> str:
        return f"Source: {self.label}"


class FramedChunksSection(ChunksSection):
    """Use the section's supported post-context extension point."""

    @property
    def post_context(self) -> str:
        return "Keep each source distinct when writing the analysis."


class RecordingSummarizer(ITextSummarizer):
    """Deterministic stand-in for an external LLM, preserving source markers."""

    CHUNK_SUMMARIES = {
        1: "Transformer relay calibration prevents nuisance trips.",
        2: "Crew dispatch scheduling reduces outage response time.",
        3: "Meter audit sampling identifies billing discrepancies.",
    }

    def __init__(self) -> None:
        self.text_calls: list[tuple[str, int | None, str]] = []
        self.chunk_calls: list[tuple[tuple[str, ...], int, tuple[str, ...]]] = []

    def summarize(self, text: str, *, max_tokens: int | None = None) -> str:
        result = (
            "Assess the feeder switching proposal using the cited evidence; "
            "state uncertainty about expected reliability gains."
        )
        self.text_calls.append((text, max_tokens, result))
        return result

    def summarize_chunks(self, chunks: list[str], *, capacity_tokens: int) -> list[str]:
        results = []
        for chunk in chunks:
            match = re.search(r"Chunk (\d+):", chunk)
            if match is None:
                raise ValueError("A prepared chunk lost its numbered marker")
            number = int(match.group(1))
            results.append(f"Chunk {number}: {self.CHUNK_SUMMARIES[number]}")
        self.chunk_calls.append((tuple(chunks), capacity_tokens, tuple(results)))
        return results


class RecordingDemandAllocator(DemandAllocator):
    def __init__(self) -> None:
        self.calls = []

    def allocate(self, demands, budget_tokens):
        result = super().allocate(demands, budget_tokens)
        self.calls.append((dict(demands), budget_tokens, dict(result)))
        return result


class RecordingRedistributionAllocator(RedistributionAllocator):
    def __init__(self) -> None:
        self.calls = []

    def redistribute(self, free_capacity_tokens, requests):
        result = super().redistribute(free_capacity_tokens, requests)
        self.calls.append((free_capacity_tokens, tuple(requests), result))
        return result


class RecordingCapacityAllocator(CapacityAllocator):
    def __init__(self, demand_allocator, redistribution_allocator) -> None:
        super().__init__(demand_allocator, redistribution_allocator)
        self.calls = []

    def allocate(self, requests, budget_tokens):
        result = super().allocate(requests, budget_tokens)
        self.calls.append((tuple(requests), budget_tokens, result))
        return result


@dataclass(frozen=True)
class StrategyAttempt:
    section: object
    strategy: OverflowStrategy
    before: object
    after: object
    capacity: int


class RecordingDispatcher(OverflowStrategyDispatcher):
    def __init__(self) -> None:
        self.attempts: list[StrategyAttempt] = []

    def apply(self, section, strategy, content, capacity_tokens, *, tokenizer):
        result = super().apply(
            section, strategy, content, capacity_tokens, tokenizer=tokenizer
        )
        self.attempts.append(
            StrategyAttempt(section, strategy, content, result, capacity_tokens)
        )
        return result


def _report_block(lines: list[str], number: int, name: str, fields: dict) -> None:
    lines.extend(("=" * 72, f"STEP {number} - {name}", "=" * 72))
    for key, value in fields.items():
        rendered = value if isinstance(value, str) else pformat(value, width=100, sort_dicts=False)
        lines.append(f"{key}:")
        lines.extend(f"    {line}" for line in rendered.splitlines() or [""])
    lines.append("")


def _make_scenario(summarizer: RecordingSummarizer):
    chunks = [
        GenerationChunk(
            "relay-calibration",
            "Relay calibration logs show intermittent transformer trips after routine "
            "load transfers. Engineers propose reviewing threshold settings, checking "
            "event traces, and recording false trip rates before changing protection. " * 2,
            SourceReference("relay maintenance log"),
        ),
        GenerationChunk(
            "crew-dispatch",
            "Dispatch records show delayed crew assignment during evening feeder "
            "outages. A regional roster and escalation rule could shorten response "
            "time while preserving the existing safety handoff and approval trail. " * 2,
            SourceReference("outage dispatch review"),
        ),
        GenerationChunk(
            "meter-audit",
            "Meter audit sampling found inconsistent reads near billing cycle close. "
            "The audit team recommends targeted validation, retained raw readings, "
            "and a documented exception queue before any invoice correction. " * 2,
            SourceReference("meter audit memorandum"),
        ),
    ]
    messages = [
        HistoryMessage(HistoryRole.USER, "We need to compare last quarter's feeder events with the proposed switching plan and document reliability assumptions."),
        HistoryMessage(HistoryRole.ASSISTANT, "The previous review asked for explicit safety checks before changing any live feeder configuration."),
        HistoryMessage(HistoryRole.USER, "Operations later requested a separate estimate for evening dispatch delay and crew availability."),
        HistoryMessage(HistoryRole.ASSISTANT, "The draft analysis identified missing outage duration data and asked for a confidence statement."),
    ]
    builder = PromptBuilder(seed_defaults=False)
    sections = [
        RoleSection(
            "You are an engineering analyst. Explain evidence and uncertainty "
            "without presenting the model output as a final operational decision.",
            demand=0.15,
        ),
        HistorySection(
            messages,
            demand=0.20,
            overflow_strategies=OverflowStrategyStack(
                [OverflowStrategy.TRUNCATE, OverflowStrategy.IGNORE]
            ),
        ),
        FramedChunksSection(
            chunks,
            demand=0.30,
            chunk_summarizer=summarizer,
            overflow_strategies=OverflowStrategyStack([OverflowStrategy.SUMMARIZE]),
        ),
        SystemInputSection(
            "Evaluate the proposed feeder switching process against maintenance "
            "evidence. State what the relay logs establish, identify data gaps, "
            "and separate reliability estimates from observed outcomes. Require "
            "operator review before any physical switching or protection change. " * 2,
            demand=0.10,
            overflow_strategies=OverflowStrategyStack([OverflowStrategy.TRUNCATE]),
        ),
        UserInputSection(
            "Please assess a staged feeder switching proposal. Explain whether "
            "relay calibration evidence supports the change, whether evening "
            "crew dispatch could affect response times, and where the meter audit "
            "limits confidence in the expected benefit. Include open questions. " * 2,
            reference=SourceReference("engineering review request"),
            demand=0.15,
            llm_summarizer=summarizer,
            overflow_strategies=OverflowStrategyStack([OverflowStrategy.SUMMARIZE]),
        ),
        OutputFormatSection(
            "Return a concise analysis with evidence, uncertainty, and cited "
            "sources; leave the organizational decision to reviewers.",
            demand=0.10,
        ),
    ]
    for section in sections:
        builder.set_section(section.section_type, section)
    return builder, sections, chunks, messages


def test_context_builder_complete_pipeline_with_execution_report(tmp_path):
    tokenizer = CharacterTokenizer()
    summarizer = RecordingSummarizer()
    builder, sections, chunks, messages = _make_scenario(summarizer)
    snapshots = {section.section_type: section.prepare() for section in sections}
    original_items = {section.section_type: deepcopy(section.items)
                      for section in sections if hasattr(section, "items")}
    demand = RecordingDemandAllocator()
    redistribution = RecordingRedistributionAllocator()
    allocator = RecordingCapacityAllocator(demand, redistribution)
    dispatcher = RecordingDispatcher()
    context_builder = ContextBuilder(
        tokenizer=tokenizer, capacity_allocator=allocator, dispatcher=dispatcher
    )
    budget = 1200
    failures = []
    checks_run = 0
    passed_checks = 0
    result = None
    lines = [
        "CONTEXTBUILDER EXECUTION REPORT",
        "Tokenizer: deterministic character tokenizer; one character equals one test token.",
        "Summarizer: deterministic external-LLM stand-in; production context, allocation, and dispatch remain active.",
        "Duration: omitted to keep the report deterministic.",
        "Preparation snapshots below are compared with the actual inputs seen by the dispatcher.",
        "",
    ]

    def check(condition, *, step, section, expected, actual, reason):
        nonlocal checks_run, passed_checks
        checks_run += 1
        if condition:
            passed_checks += 1
        else:
            source = snapshots.get(section)
            latest = next(
                (attempt for attempt in reversed(dispatcher.attempts)
                 if attempt.section.section_type == section), None
            )
            source_section = next(
                (candidate for candidate in sections if candidate.section_type == section), None
            )
            output = next(
                (item for item in result.sections if item.section_type == section), None
            ) if result is not None else None
            failures.append(
                f"Step: {step}\nSection: {section}\nExpected: {expected}\n"
                f"Actual: {actual}\nReason: {reason}\n"
                f"Relevant input: {source.content if source else 'all sections'}\n"
                f"Relevant output: {output.content if output else 'see strategy attempts'}\n"
                f"Token metrics: prepared={len(source.content) if source else 'per-section table'}, "
                f"capacity={output.capacity_tokens if output else 'see allocation'}, "
                f"fitted={output.fitted_tokens if output else 'see strategy attempts'}\n"
                f"Applied strategy: {latest.strategy.name if latest else 'none'}\n"
                f"Configuration: {source_section.overflow_strategies if source_section else 'all sections'}"
            )

    _report_block(lines, 1, "SECTION CONSTRUCTION AND REGISTRATION", {
        "Section order": [section.section_type for section in builder.sections],
        "Section classes": [type(section).__name__ for section in sections],
        "Budget tokens": budget,
        "Configuration": [(section.section_type, section.demand, section.importance,
                           [strategy.name for strategy in section.overflow_strategies.strategies])
                          for section in sections],
    })
    for section in sections:
        prepared = snapshots[section.section_type]
        _report_block(lines, 2, f"REFERENCE INJECTION AND PREPARATION: {section.section_type}", {
            "Section class": type(section).__name__,
            "Original body": section.body(),
            "Pre-context": repr(section.pre_context),
            "Post-context": repr(section.post_context),
            "Section reference": section.reference.fluent_text() if hasattr(section, "reference") and section.reference else "none",
            "Item references": [item.reference.fluent_text() if getattr(item, "reference", None) else "none" for item in prepared.items or ()],
            "Complete prepared content": prepared.content,
            "Prepared item inputs": prepared.item_inputs,
            "Prepared tokens": tokenizer.count_tokens(prepared.content),
            "Validation": "compared with allocation and strategy inputs below",
        })

    try:
        result = context_builder.build(builder, max_tokens=budget)
    except Exception as error:
        failures.append(
            f"Step: ContextBuilder.build\nSection: current pipeline section\n"
            f"Expected: successful ContextBuilderResult\nActual: {type(error).__name__}: {error}\n"
            "Reason: production pipeline raised; preceding preparation and recorded attempts are shown."
        )

    if allocator.calls:
        requests, usable_budget, allocation = allocator.calls[0]
        initial = demand.calls[0][2]
        free, expansion_requests, redistributed = redistribution.calls[0]
        _report_block(lines, 3, "TOKEN CALCULATION AND CAPACITY ALLOCATION", {
            "Separator": repr(builder.SECTION_SEPARATOR),
            "Separator reservation": budget - usable_budget,
            "Usable budget": usable_budget,
            "Requests (section, demand, importance, prepared tokens)":
                [(r.key, r.demand, r.importance, r.needed_tokens) for r in requests],
            "Initial demand shares": initial,
            "Free capacity before redistribution": free,
            "Expansion requests": [(r.requested_tokens, r.weight) for r in expansion_requests],
            "Redistributed awards": [r.allocated_tokens for r in redistributed.allocations],
            "Final section capacities": dict(allocation.capacities),
            "Unused capacity": allocation.unused_tokens,
            "Validation": "checked against section outputs and usable budget below",
        })
        check(usable_budget == budget - (len(sections) - 1) * len(builder.SECTION_SEPARATOR),
              step=3, section="all", expected="separator reservation subtracted", actual=usable_budget,
              reason="capacity must include prompt separators")
        check(all(r.needed_tokens == len(snapshots[r.key].content) for r in requests),
              step=3, section="all", expected="prepared token counts", actual=requests,
              reason="allocation must count references and context before fitting")

    for index, attempt in enumerate(dispatcher.attempts, start=1):
        before = attempt.before
        after = attempt.after
        before_tokens = len(before.content)
        after_tokens = len(after.content) if after is not None else None
        accepted = after is not None and after_tokens <= attempt.capacity
        details = {
            "Section class": type(attempt.section).__name__,
            "Section identifier": attempt.section.section_type,
            "Operation / strategy": attempt.strategy.name,
            "Configured strategy order": [s.name for s in attempt.section.overflow_strategies.strategies],
            "Input tokens": before_tokens,
            "Capacity tokens": attempt.capacity,
            "Remaining capacity before": attempt.capacity - before_tokens,
            "Original section body": attempt.section.body(),
            "Pre-context": repr(attempt.section.pre_context),
            "Post-context": repr(attempt.section.post_context),
            "Prepared input": before.content,
            "Actual per-item processing inputs": before.item_inputs,
            "Actual summarizer input": (
                summarizer.chunk_calls[-1][0] if before.items is not None and summarizer.chunk_calls
                else summarizer.text_calls[-1][0] if before.items is None and summarizer.text_calls
                else "not applicable"
            ) if attempt.strategy is OverflowStrategy.SUMMARIZE else "not applicable",
            "Output": after.content if after is not None else "not applicable",
            "Output tokens": after_tokens,
            "Token delta": before_tokens - after_tokens if after_tokens is not None else "not applicable",
            "Remaining capacity after": attempt.capacity - after_tokens if after_tokens is not None else "not applicable",
            "Selected by ContextBuilder": accepted,
            "Validation": "fits" if accepted else "continue to next strategy or safety fallback",
        }
        if attempt.strategy is OverflowStrategy.SUMMARIZE and after is not None:
            details.update({
                "Source item count": len(before.items or ()),
                "Output item count": len(after.items or ()),
                "Item token counts before": [len(text) for text in before.item_inputs or ()],
                "Item token counts after": [len(text) for text in after.item_inputs or ()],
                "Per-item token savings": [len(source) - len(summary) for source, summary in
                                           zip(before.item_inputs or (), after.item_inputs or ())],
                "Summarized item outputs": [item.content for item in after.items or ()],
                "Tokens saved": before_tokens - after_tokens,
                "Reduction percentage": f"{100 * (before_tokens - after_tokens) / before_tokens:.2f}%" if before_tokens else "0.00%",
                "Capacity satisfied": accepted,
                "Per-item processing": "independent inputs, one batch call" if before.items is not None else "single complete text",
                "Per-item accounting note": (
                    "Each item input repeats the section frame; aggregate tokens count that frame once."
                    if before.items is not None else "not applicable"
                ),
                "Item IDs before": [getattr(item, "chunk_id", None) for item in before.items or ()],
                "Item IDs after": [getattr(item, "chunk_id", None) for item in after.items or ()],
            })
        if attempt.strategy is OverflowStrategy.TRUNCATE and after is not None:
            details.update({
                "Truncation required": before_tokens > attempt.capacity,
                "Behavior": "NO-OP: collection truncation is unsupported" if before.items is not None else "prefix truncation",
                "Input equals output": before == after,
                "Original section changed": attempt.section.prepare() != snapshots[attempt.section.section_type],
                "Tokens removed": before_tokens - after_tokens,
                "Reduction percentage": f"{100 * (before_tokens - after_tokens) / before_tokens:.2f}%" if before_tokens else "0.00%",
            })
        if attempt.strategy is OverflowStrategy.IGNORE and after is not None:
            kept = len(after.items or ())
            details.update({
                "Original item count": len(before.items or ()),
                "Removed items": [getattr(item, "chunk_id", getattr(item, "content", "")) for item in (before.items or ())[kept:]],
                "Remaining items": [getattr(item, "chunk_id", getattr(item, "content", "")) for item in after.items or ()],
                "Tokens removed": before_tokens - after_tokens,
                "Remaining items unchanged": after.items == (before.items or ())[:kept],
                "Ordering preserved": after.items == (before.items or ())[:kept],
                "Capacity satisfied": accepted,
            })
        _report_block(lines, 4, f"STRATEGY ATTEMPT {index}", details)

    if result is not None:
        by_type = {output.section_type: output for output in result.sections}
        by_attempt = {name: [attempt for attempt in dispatcher.attempts
                             if attempt.section.section_type == name]
                      for name in by_type}
        _report_block(lines, 5, "RESULT CONSTRUCTION AND FINAL VALIDATION", {
            "Section separator": repr(result.section_separator),
            "Section order": [output.section_type for output in result.sections],
            "Sections (type, original tokens, capacity, final tokens, overflow)":
                [(o.section_type, o.requested_tokens, o.capacity_tokens, o.fitted_tokens, o.overflowed)
                 for o in result.sections],
            "Final section contents": [(o.section_type, o.content) for o in result.sections],
            "Final collection item IDs": [(o.section_type, [getattr(item, "chunk_id", None) for item in o.items])
                                          for o in result.sections if o.items is not None],
            "Final prompt": result.prompt,
            "Final total tokens": result.total_tokens,
            "Total capacity": result.budget_tokens,
            "Remaining capacity": result.budget_tokens - result.total_tokens,
            "Original source items unchanged": all(section.items == original_items[section.section_type]
                                                   for section in sections if hasattr(section, "items")),
        })
        expected_order = [section.section_type for section in sections]
        check([o.section_type for o in result.sections] == expected_order,
              step=5, section="all", expected=expected_order,
              actual=[o.section_type for o in result.sections], reason="registry order must propagate")
        check(all(o.requested_tokens == len(snapshots[o.section_type].content) and
                  o.fitted_tokens == len(o.content) and o.fitted_tokens <= o.capacity_tokens
                  for o in result.sections), step=5, section="all",
              expected="consistent counts, every section within capacity",
              actual=[(o.section_type, o.requested_tokens, o.fitted_tokens, o.capacity_tokens) for o in result.sections],
              reason="prepared and final token accounting must agree")
        check(result.prompt == builder.assemble({o.section_type: o.content for o in result.sections})
              and result.total_tokens == len(result.prompt) <= budget,
              step=5, section="all", expected="assembled prompt within budget",
              actual=(result.total_tokens, budget), reason="final assembly must use fitted sections")
        check(all(section.prepare() == snapshots[section.section_type] for section in sections)
              and all(section.items == original_items[section.section_type]
                      for section in sections if hasattr(section, "items")),
              step=5, section="all", expected="original sections and items unchanged",
              actual=[section.section_type for section in sections], reason="processing must return values")
        check([a.strategy for a in by_attempt["HISTORY"]] ==
              [OverflowStrategy.TRUNCATE, OverflowStrategy.IGNORE],
              step=4, section="HISTORY", expected="TRUNCATE then IGNORE",
              actual=[a.strategy.name for a in by_attempt["HISTORY"]], reason="collection no-op must fall through")
        if len(by_attempt["HISTORY"]) == 2:
            first, second = by_attempt["HISTORY"]
            check(first.after is first.before and second.after.items == tuple(messages[:len(second.after.items)])
                  and 0 < len(second.after.items) < len(messages),
                  step=4, section="HISTORY", expected="no-op then trailing-item removal",
                  actual=(first.after == first.before, second.after.items),
                  reason="ignore must keep an unchanged prefix")
            check(by_type["HISTORY"].items == second.after.items and by_type["HISTORY"].content == second.after.content,
                  step=5, section="HISTORY", expected="ignore result in ContextBuilderResult",
                  actual=by_type["HISTORY"].items, reason="transformed items must propagate")
        check([a.strategy for a in by_attempt["CHUNKS"]] == [OverflowStrategy.SUMMARIZE]
              and len(summarizer.chunk_calls) == 1,
              step=4, section="CHUNKS", expected="one collection summarization",
              actual=[a.strategy.name for a in by_attempt["CHUNKS"]],
              reason="batch summarizer should receive independent inputs")
        if summarizer.chunk_calls:
            inputs, target, summaries = summarizer.chunk_calls[0]
            check(inputs == snapshots["CHUNKS"].item_inputs and len(inputs) == len(chunks)
                  and all(f"Chunk {i}:" in item and "Source:" in item
                          and "Relevant context chunks:" in item
                          and "Keep each source distinct" in item
                          for i, item in enumerate(inputs, 1))
                  and all(term in text.casefold() for term, text in
                          zip(("relay calibration", "dispatch records", "meter audit"), inputs)),
                  step=4, section="CHUNKS", expected="complete framed, referenced, ordered item inputs",
                  actual=inputs, reason="summarizer must see each prepared item separately")
            check([item.chunk_id for item in by_type["CHUNKS"].items] == [item.chunk_id for item in chunks]
                  and [item.reference for item in by_type["CHUNKS"].items] == [item.reference for item in chunks]
                  and [item.content for item in by_type["CHUNKS"].items] == list(summaries)
                  and by_type["CHUNKS"].fitted_tokens < by_type["CHUNKS"].requested_tokens
                  and by_type["CHUNKS"].fitted_tokens <= target,
                  step=5, section="CHUNKS", expected="ordered one-to-one reduced items within capacity",
                  actual=[(item.chunk_id, item.content) for item in by_type["CHUNKS"].items],
                  reason="summaries must propagate without item loss or mixing")
        check(len(summarizer.text_calls) == 1 and
              summarizer.text_calls[0][0] == snapshots["USER-INPUT"].content and
              "Source: engineering review request" in summarizer.text_calls[0][0],
              step=4, section="USER-INPUT", expected="complete reference-enriched summarization input",
              actual=summarizer.text_calls, reason="text summarization must use prepared content")
        check([a.strategy for a in by_attempt["SYSTEM-INPUT"]] == [OverflowStrategy.TRUNCATE]
              and by_type["SYSTEM-INPUT"].content == snapshots["SYSTEM-INPUT"].content[:by_type["SYSTEM-INPUT"].capacity_tokens],
              step=4, section="SYSTEM-INPUT", expected="exact prepared-text prefix truncation",
              actual=by_type["SYSTEM-INPUT"].content,
              reason="truncation must include prepared text and fit capacity")
        check(not by_attempt["ROLE"] and not by_attempt["OUTPUT-FORMAT"],
              step=4, section="ROLE/OUTPUT-FORMAT", expected="no overflow strategies",
              actual=[len(by_attempt["ROLE"]), len(by_attempt["OUTPUT-FORMAT"])],
              reason="fitting content should pass through")

        original_tokens = sum(len(snapshot.content) for snapshot in snapshots.values())
        final_section_tokens = sum(o.fitted_tokens for o in result.sections)
        counts = {strategy: sum(a.strategy is strategy for a in dispatcher.attempts)
                  for strategy in OverflowStrategy}
        _report_block(lines, 6, "PIPELINE SUMMARY", {
            "Total sections": len(sections),
            "Sections processed by strategies": sum(bool(by_attempt[name]) for name in by_type),
            "Strategies applied": len(dispatcher.attempts),
            "Summarize operations": counts[OverflowStrategy.SUMMARIZE],
            "Truncate operations": counts[OverflowStrategy.TRUNCATE],
            "Ignore operations": counts[OverflowStrategy.IGNORE],
            "Original section tokens": original_tokens,
            "Final section tokens": final_section_tokens,
            "Section tokens saved": original_tokens - final_section_tokens,
            "Section reduction": f"{100 * (original_tokens - final_section_tokens) / original_tokens:.2f}%",
            "Final prompt tokens including separators": result.total_tokens,
            "Final capacity": budget,
            "Remaining capacity": budget - result.total_tokens,
            "Per-section summary": [(o.section_type, o.requested_tokens, o.fitted_tokens,
                                     o.requested_tokens - o.fitted_tokens,
                                     [a.strategy.name for a in by_attempt[o.section_type]])
                                    for o in result.sections],
            "Architectural observation": (
                "Chunk references reach the summarizer inputs and remain on output item "
                "objects, but the summarized CHUNKS prompt text omits those citations."
                if "Source:" in snapshots["CHUNKS"].content and
                   "Source:" not in by_type["CHUNKS"].content else
                "Chunk references are present in the final CHUNKS prompt text."
            ),
        })

    lines.extend(("=" * 72, "VALIDATION AND FAILURE DIAGNOSTICS", "=" * 72))
    lines.append(f"Assertions passed: {passed_checks}")
    lines.append(f"Assertions failed: {checks_run - passed_checks}")
    lines.append(f"Execution errors: {len(failures) - (checks_run - passed_checks)}")
    lines.append(f"Pipeline result: {'FAIL' if failures else 'PASS'}")
    for failure in failures:
        lines.extend(("-" * 72, failure))
    report = "\n".join(lines) + "\n"
    report_path = Path(os.environ.get("CONTEXT_BUILDER_REPORT_PATH", str(tmp_path / "context_builder_pipeline_report.txt")))
    report_path.write_text(report, encoding="utf-8")
    print(f"Execution report: {report_path}\n{report}")
    assert report.isascii(), "The execution report must contain English-only ASCII test data"
    assert not failures, report
