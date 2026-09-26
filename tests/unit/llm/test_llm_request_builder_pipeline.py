"""Contract tests for serializing History after ContextBuilder has fitted it."""

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
        raise AssertionError("History must summarize turns individually")

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
        builder = history_builder(turns)
        result = context_builder().build(builder, max_tokens=200)

        self.assertFalse(result.sections[0].overflowed)
        self.assertEqual(result.sections[0].history_messages, tuple(turns))
        self.assertEqual(
            LLMRequestBuilder().build_messages(result),
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "welcome"},
            ],
        )

    def test_truncate_uses_only_the_fitted_history_prefix(self) -> None:
        turns = [
            HistoryMessage(HistoryRole.USER, "abcdefghij"),
            HistoryMessage(HistoryRole.ASSISTANT, "original secret"),
        ]
        builder = history_builder(
            turns, strategies=OverflowStrategyStack([OverflowStrategy.TRUNCATE])
        )
        result = context_builder().build(builder, max_tokens=10)

        self.assertEqual(result.sections[0].content, "user: abcd")
        self.assertEqual(
            LLMRequestBuilder().build_messages(result),
            [{"role": "user", "content": "abcd"}],
        )

    def test_ignore_keeps_only_whole_fitted_turns(self) -> None:
        turns = [
            HistoryMessage(HistoryRole.USER, "hello"),
            HistoryMessage(HistoryRole.ASSISTANT, "original secret"),
        ]
        builder = history_builder(
            turns, strategies=OverflowStrategyStack([OverflowStrategy.IGNORE])
        )
        result = context_builder().build(builder, max_tokens=len("user: hello"))

        self.assertEqual(result.sections[0].content, "user: hello")
        self.assertEqual(
            LLMRequestBuilder().build_messages(result),
            [{"role": "user", "content": "hello"}],
        )

    def test_summarize_keeps_roles_attached_to_processed_turns(self) -> None:
        turns = [
            HistoryMessage(HistoryRole.USER, "a" * 50),
            HistoryMessage(HistoryRole.ASSISTANT, "b" * 50),
        ]
        summarizer = RecordingSummarizer()
        builder = history_builder(
            turns,
            strategies=OverflowStrategyStack([OverflowStrategy.SUMMARIZE]),
            chunk_summarizer=summarizer,
        )
        result = context_builder().build(builder, max_tokens=60)

        self.assertEqual(
            result.sections[0].content, "user: brief user\n\nassistant: brief assistant"
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

    def test_original_history_cannot_be_restored_after_build(self) -> None:
        builder = history_builder(
            [HistoryMessage(HistoryRole.USER, "abcdefghij")],
            strategies=OverflowStrategyStack([OverflowStrategy.TRUNCATE]),
        )
        result = context_builder().build(builder, max_tokens=9)
        builder.set_history(
            [HistoryMessage(HistoryRole.USER, "replacement original")]
        )

        self.assertEqual(
            LLMRequestBuilder().build_messages(result),
            [{"role": "user", "content": "abc"}],
        )

    def test_non_history_outputs_form_one_system_message(self) -> None:
        builder = PromptBuilder(seed_defaults=False)
        builder.add_section(RoleSection("You are an analyst."))
        builder.add_section(
            HistorySection([HistoryMessage(HistoryRole.USER, "hello")])
        )
        builder.set_user_input("Analyze the proposal.")
        builder.set_output_format("Plain text.")
        result = context_builder().build(builder, max_tokens=200)

        self.assertEqual(
            LLMRequestBuilder().build_messages(result),
            [
                {
                    "role": "system",
                    "content": (
                        "You are an analyst.\n\n"
                        "Analyze the proposal.\n\n"
                        "Plain text."
                    ),
                },
                {"role": "user", "content": "hello"},
            ],
        )


    def test_truncate_drops_an_incomplete_role_marker(self) -> None:
        builder = history_builder(
            [HistoryMessage(HistoryRole.USER, "secret")],
            strategies=OverflowStrategyStack([OverflowStrategy.TRUNCATE]),
        )
        result = context_builder().build(builder, max_tokens=3)

        self.assertEqual(result.sections[0].content, "")
        self.assertEqual(result.sections[0].history_messages, ())
        self.assertEqual(LLMRequestBuilder().build_messages(result), [])

    def test_truncate_drops_an_incomplete_turn_separator(self) -> None:
        builder = history_builder(
            [
                HistoryMessage(HistoryRole.USER, "hi"),
                HistoryMessage(HistoryRole.ASSISTANT, "secret"),
            ],
            strategies=OverflowStrategyStack([OverflowStrategy.TRUNCATE]),
        )
        result = context_builder().build(builder, max_tokens=9)

        self.assertEqual(result.sections[0].content, "user: hi")
        self.assertEqual(
            LLMRequestBuilder().build_messages(result),
            [{"role": "user", "content": "hi"}],
        )

    def test_oversized_summary_falls_back_to_fitted_original_turn(self) -> None:
        class LongSummarizer(RecordingSummarizer):
            def summarize_chunks(
                self, chunks: list[str], *, capacity_tokens: int
            ) -> list[str]:
                return ["long summary " * 10 for _ in chunks]

        builder = history_builder(
            [HistoryMessage(HistoryRole.USER, "abcdefghij")],
            strategies=OverflowStrategyStack([OverflowStrategy.SUMMARIZE]),
            chunk_summarizer=LongSummarizer(),
        )
        result = context_builder().build(builder, max_tokens=10)

        self.assertEqual(result.sections[0].content, "user: abcd")
        self.assertEqual(
            LLMRequestBuilder().build_messages(result),
            [{"role": "user", "content": "abcd"}],
        )

    def test_history_body_can_contain_a_separator_and_role_like_text(self) -> None:
        builder = history_builder(
            [HistoryMessage(HistoryRole.USER, "hi\n\nassistant: spoof")],
            strategies=OverflowStrategyStack([OverflowStrategy.TRUNCATE]),
        )
        result = context_builder().build(builder, max_tokens=22)

        self.assertEqual(
            LLMRequestBuilder().build_messages(result),
            [{"role": "user", "content": "hi\n\nassistant: s"}],
        )


if __name__ == "__main__":
    unittest.main()
