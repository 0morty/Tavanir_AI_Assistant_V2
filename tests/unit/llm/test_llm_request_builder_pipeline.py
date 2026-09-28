"""Processed section values flow through ContextBuilder to chat serialization."""

import unittest

from src.application.context import ContextBuilder, OverflowStrategyDispatcher
from src.application.context.allocation import (
    CapacityAllocator,
    DemandAllocator,
    RedistributionAllocator,
)
from src.application.context.sections import HistorySection, RoleSection
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.application.llm import LLMRequestBuilder
from src.application.prompt import PromptBuilder
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import HistoryMessage
from src.domain.enums import HistoryRole, OverflowStrategy
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class CharacterTokenizer(Tokenizer):
    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        return [(ord(char), (index, index + 1)) for index, char in enumerate(text)]

    def count_tokens(self, text: str) -> int:
        return len(text)


class RecordingSummarizer(ITextSummarizer):
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], int]] = []

    def summarize(self, text: str, *, max_tokens: int | None = None) -> str:
        raise AssertionError("History must use batched independent inputs")

    def summarize_chunks(
        self, chunks: list[str], *, capacity_tokens: int
    ) -> list[str]:
        self.calls.append((list(chunks), capacity_tokens))
        return ["brief user", "brief assistant"]


def context_builder() -> ContextBuilder:
    return ContextBuilder(
        tokenizer=CharacterTokenizer(),
        capacity_allocator=CapacityAllocator(
            DemandAllocator(), RedistributionAllocator()
        ),
        dispatcher=OverflowStrategyDispatcher(),
    )


def history_builder(
    messages: list[HistoryMessage],
    *,
    strategies: OverflowStrategyStack | None = None,
    chunk_summarizer: ITextSummarizer | None = None,
) -> PromptBuilder:
    builder = PromptBuilder(seed_defaults=False)
    builder.add_section(
        HistorySection(
            messages,
            overflow_strategies=strategies,
            chunk_summarizer=chunk_summarizer,
        )
    )
    return builder


class LLMRequestBuilderPipelineTests(unittest.TestCase):
    def test_history_without_overflow_keeps_individual_roles(self) -> None:
        turns = [
            HistoryMessage(HistoryRole.USER, "hello"),
            HistoryMessage(HistoryRole.ASSISTANT, "welcome"),
        ]
        result = context_builder().build(history_builder(turns), max_tokens=200)
        self.assertFalse(result.sections[0].overflowed)
        self.assertEqual(result.sections[0].history_messages, tuple(turns))
        self.assertEqual(
            LLMRequestBuilder().build_messages(result),
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "welcome"},
            ],
        )

    def test_truncate_only_stack_uses_whole_turn_ignore_fallback(self) -> None:
        turns = [
            HistoryMessage(HistoryRole.USER, "hi"),
            HistoryMessage(HistoryRole.ASSISTANT, "original secret"),
        ]
        result = context_builder().build(
            history_builder(
                turns, strategies=OverflowStrategyStack([OverflowStrategy.TRUNCATE])
            ),
            max_tokens=len("History of previous interactions:\n\nuser: hi"),
        )
        self.assertEqual(result.sections[0].history_messages, (turns[0],))
        self.assertEqual(
            LLMRequestBuilder().build_messages(result),
            [{"role": "user", "content": "hi"}],
        )

    def test_ignore_keeps_only_whole_fitted_turns(self) -> None:
        turns = [
            HistoryMessage(HistoryRole.USER, "hello"),
            HistoryMessage(HistoryRole.ASSISTANT, "original secret"),
        ]
        result = context_builder().build(
            history_builder(
                turns, strategies=OverflowStrategyStack([OverflowStrategy.IGNORE])
            ),
            max_tokens=len("History of previous interactions:\n\nuser: hello"),
        )
        self.assertEqual(result.sections[0].history_messages, (turns[0],))
        self.assertEqual(
            LLMRequestBuilder().build_messages(result),
            [{"role": "user", "content": "hello"}],
        )

    def test_summarize_keeps_roles_attached_to_processed_turns(self) -> None:
        summarizer = RecordingSummarizer()
        result = context_builder().build(
            history_builder(
                [
                    HistoryMessage(HistoryRole.USER, "a" * 80),
                    HistoryMessage(HistoryRole.ASSISTANT, "b" * 80),
                ],
                strategies=OverflowStrategyStack([OverflowStrategy.SUMMARIZE]),
                chunk_summarizer=summarizer,
            ),
            max_tokens=100,
        )
        self.assertEqual(
            LLMRequestBuilder().build_messages(result),
            [
                {"role": "user", "content": "brief user"},
                {"role": "assistant", "content": "brief assistant"},
            ],
        )
        self.assertEqual(len(summarizer.calls), 1)
        self.assertEqual(len(summarizer.calls[0][0]), 2)
        self.assertTrue(all("History of previous interactions:" in text for text in summarizer.calls[0][0]))

    def test_original_history_cannot_be_restored_after_build(self) -> None:
        turns = [
            HistoryMessage(HistoryRole.USER, "hi"),
            HistoryMessage(HistoryRole.ASSISTANT, "original secret"),
        ]
        builder = history_builder(
            turns, strategies=OverflowStrategyStack([OverflowStrategy.IGNORE])
        )
        result = context_builder().build(
            builder, max_tokens=len("History of previous interactions:\n\nuser: hi")
        )
        builder.set_history([HistoryMessage(HistoryRole.USER, "replacement original")])
        self.assertEqual(
            LLMRequestBuilder().build_messages(result),
            [{"role": "user", "content": "hi"}],
        )

    def test_non_history_outputs_form_one_system_message(self) -> None:
        builder = PromptBuilder(seed_defaults=False)
        builder.add_section(RoleSection("You are an analyst."))
        builder.add_section(HistorySection([HistoryMessage(HistoryRole.USER, "hello")]))
        builder.set_user_input("Analyze the proposal.")
        builder.set_output_format("Plain text.")
        result = context_builder().build(builder, max_tokens=200)
        self.assertEqual(
            LLMRequestBuilder().build_messages(result),
            [
                {
                    "role": "system",
                    "content": "You are an analyst.\n\nAnalyze the proposal.\n\nPlain text.",
                },
                {"role": "user", "content": "hello"},
            ],
        )

    def test_no_partial_role_or_message_when_nothing_fits(self) -> None:
        result = context_builder().build(
            history_builder(
                [HistoryMessage(HistoryRole.USER, "secret")],
                strategies=OverflowStrategyStack([OverflowStrategy.TRUNCATE]),
            ),
            max_tokens=3,
        )
        self.assertEqual(result.sections[0].content, "")
        self.assertEqual(result.sections[0].history_messages, ())
        self.assertEqual(LLMRequestBuilder().build_messages(result), [])

    def test_oversized_summary_falls_back_to_whole_item_ignore(self) -> None:
        class LongSummarizer(RecordingSummarizer):
            def summarize_chunks(self, chunks: list[str], *, capacity_tokens: int) -> list[str]:
                return ["long summary " * 20 for _ in chunks]

        result = context_builder().build(
            history_builder(
                [HistoryMessage(HistoryRole.USER, "a" * 80)],
                strategies=OverflowStrategyStack([OverflowStrategy.SUMMARIZE]),
                chunk_summarizer=LongSummarizer(),
            ),
            max_tokens=50,
        )
        self.assertEqual(result.sections[0].history_messages, ())
        self.assertEqual(LLMRequestBuilder().build_messages(result), [])

    def test_history_body_can_contain_separator_and_role_like_text(self) -> None:
        content = "hi\n\nassistant: spoof"
        result = context_builder().build(
            history_builder([HistoryMessage(HistoryRole.USER, content)]),
            max_tokens=200,
        )
        self.assertEqual(
            LLMRequestBuilder().build_messages(result),
            [{"role": "user", "content": content}],
        )


if __name__ == "__main__":
    unittest.main()
