"""Scenario budgets derive from the configured production tokenizer."""
from __future__ import annotations

from dataclasses import dataclass

from src.application.context.sections import (ChunksSection, HistorySection, OutputFormatSection,
                                              RoleSection, SystemInputSection, UserInputSection)
from src.application.prompt import PromptBuilder
from src.domain.enums import OverflowStrategy as Strategy
from src.domain.overflow_strategy_stack import OverflowStrategyStack
from . import dataset


@dataclass(frozen=True)
class Scenario:
    name: str
    purpose: str
    builder: PromptBuilder
    budget: int
    expected_strategy: str | None = None


def stack(*strategies: Strategy, restart: bool = False) -> OverflowStrategyStack:
    return OverflowStrategyStack(strategies, restart=restart, max_restarts=1 if restart else 0)


def make_scenario(name, tokenizer, text_summarizer, chunk_summarizer) -> Scenario:
    def single(section, budget, purpose, expected=None):
        return Scenario(name, purpose, PromptBuilder([section], seed_defaults=False), budget, expected)

    evidence = dataset.chunks()
    text = evidence[0].content
    tokens = tokenizer.count_tokens(text)
    if name in {"A_everything_fits", "J_ordering"}:
        sections = [RoleSection(dataset.ROLE), SystemInputSection(dataset.SYSTEM),
                    ChunksSection(evidence), HistorySection(dataset.history()[:2]),
                    UserInputSection(dataset.USER), OutputFormatSection(dataset.OUTPUT)]
        if name.startswith("J"):
            sections = [sections[i] for i in (2, 0, 3, 5, 1, 4)]
        builder = PromptBuilder(sections, seed_defaults=False)
        budget = sum(tokenizer.count_tokens(s.render()) for s in sections) + 64
        return Scenario(name, "No overflow; retain all evidence and serialize role groups in stable order.",
                        builder, budget)
    if name == "B_small_overflow":
        return single(UserInputSection(text, overflow_strategies=stack(Strategy.TRUNCATE)), tokens - 1,
                      "Exactly one token over capacity.", "TRUNCATE")
    if name == "C_truncate":
        return single(UserInputSection(text, overflow_strategies=stack(Strategy.TRUNCATE)), tokens // 3,
                      "Offset-exact prefix truncation.", "TRUNCATE")
    if name == "D_summarize":
        return single(UserInputSection(text, llm_summarizer=text_summarizer,
                                       overflow_strategies=stack(Strategy.SUMMARIZE, Strategy.TRUNCATE)),
                      100, "Single-text summary with full English LLM request.", "SUMMARIZE")
    if name == "E_ignore":
        section = ChunksSection(evidence, overflow_strategies=stack(Strategy.IGNORE))
        capacity = tokenizer.count_tokens(ChunksSection(evidence[:2]).render())
        return single(section, capacity, "Retain exactly the first two cited chunks; drop the tail.", "IGNORE")
    if name == "F_severe":
        sections = [RoleSection(dataset.ROLE, demand=0.8),
                    SystemInputSection(text, demand=0.1, overflow_strategies=stack(Strategy.TRUNCATE)),
                    ChunksSection(evidence, demand=0.05, importance=0.1, chunk_summarizer=chunk_summarizer,
                                  overflow_strategies=stack(Strategy.SUMMARIZE, Strategy.TRUNCATE,
                                                            restart=True)),
                    HistorySection(dataset.history(), demand=0.05,
                                   overflow_strategies=stack(Strategy.IGNORE)),
                    UserInputSection(dataset.USER, demand=0.0, importance=1.0)]
        return Scenario(name, "Stress redistribution, bounded restart, summary, no-op collection truncation "
                        "and whole-item fallback against a severe budget.",
                        PromptBuilder(sections, seed_defaults=False), 180)
    if name == "G_history":
        turns = dataset.history()
        capacity = tokenizer.count_tokens(HistorySection(turns[:3]).render())
        return single(HistorySection(turns, overflow_strategies=stack(Strategy.TRUNCATE, Strategy.IGNORE)),
                      capacity, "Keep the oldest three turns with roles; newer trailing turns are removed.",
                      "IGNORE")
    if name == "H_chunk_summaries":
        return single(ChunksSection(evidence, chunk_summarizer=chunk_summarizer,
                                    overflow_strategies=stack(Strategy.SUMMARIZE, Strategy.IGNORE)),
                      500, "Five independently oversized items, batches of two, aligned summaries and citations.",
                      "SUMMARIZE")
    if name.startswith("I_boundary_"):
        delta = {"equal": 0, "over": -1, "under": 1}[name.rsplit("_", 1)[1]]
        return single(UserInputSection(text), tokens + delta, "Token boundary relative to prepared need.")
    if name in {"I_empty", "I_character", "I_one_token", "I_zero_capacity", "I_tiny_capacity"}:
        value = {"I_empty": "", "I_character": "x", "I_one_token": "Hello",
                 "I_zero_capacity": text, "I_tiny_capacity": text}[name]
        budget = 0 if name in {"I_empty", "I_zero_capacity"} else 1
        return single(UserInputSection(value), budget, "Empty, one-token, or zero/tiny capacity behavior.")
    if name == "I_empty_sections":
        return Scenario(name, "Multiple empty sections reserve separators but produce no text.",
                        PromptBuilder(), 0)
    if name == "I_no_sections":
        return Scenario(name, "No registered sections.", PromptBuilder(seed_defaults=False), 0)
    raise ValueError(name)


SCENARIOS = (
    "A_everything_fits", "B_small_overflow", "C_truncate", "D_summarize", "E_ignore",
    "F_severe", "G_history", "H_chunk_summaries", "I_boundary_equal", "I_boundary_over",
    "I_boundary_under", "I_empty", "I_character", "I_one_token", "I_zero_capacity",
    "I_tiny_capacity", "I_empty_sections", "I_no_sections", "J_ordering",
)
