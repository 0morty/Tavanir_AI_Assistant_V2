"""Unit tests for LLMRequestBuilder (ContextBuilderResult -> chat messages).

Import order note: this project has a pre-existing import cycle when
``src.application.prompt`` or ``src.application.context.sections`` are
imported before the allocation chain; load ``expansion_request`` first.
"""

import src.application.context.allocation.expansion_request  # noqa: F401,PLC0415  (cycle guard)

from src.application.context.sections.history_section import HistorySection
from src.application.dtos import ContextBuilderResult, SectionOutput
from src.application.llm.llm_request_builder import LLMRequestBuilder
from src.application.prompt.prompt_builder import PromptBuilder
from src.domain.entities import HistoryMessage
from src.domain.enums import HistoryRole

HISTORY_TURNS = [
    HistoryMessage(role=HistoryRole.USER, content="سلام وقت بخیر"),
    HistoryMessage(role=HistoryRole.ASSISTANT, content="سلام، من دستیار هوشمند هستم"),
    HistoryMessage(role=HistoryRole.USER, content="در مورد این موضوع توضیح بده"),
]


def _output(
    section_type: str,
    content: str,
    *,
    requested: int = 1,
    capacity: int = 1,
    fitted: int = 1,
    overflowed: bool = False,
) -> SectionOutput:
    return SectionOutput(
        section_type=section_type,
        content=content,
        requested_tokens=requested,
        capacity_tokens=capacity,
        fitted_tokens=fitted,
        overflowed=overflowed,
    )


def _result(*outputs: SectionOutput) -> ContextBuilderResult:
    return ContextBuilderResult(
        prompt="MUST-NOT-BE-USED",
        sections=outputs,
        budget_tokens=100,
        total_tokens=0,
    )


def _builder_with_history() -> PromptBuilder:
    builder = PromptBuilder()
    builder.set_history(HISTORY_TURNS)
    return builder


def test_history_becomes_separate_messages_in_order():
    builder = _builder_with_history()
    result = _result(
        _output("ROLE", "You are an analyst."),
        _output("SYSTEM-INPUT", "Base on the material only."),
    )

    messages = LLMRequestBuilder().build_messages(result, builder)

    assert [m["role"] for m in messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert [m["content"] for m in messages[1:]] == [
        h.content for h in HISTORY_TURNS
    ]


def test_assistant_role_spelling_is_correct():
    assert HistoryRole.ASSISTANT.value == "assistant"
    builder = _builder_with_history()
    messages = LLMRequestBuilder().build_messages(
        _result(_output("ROLE", "You are an analyst.")), builder
    )
    roles = [m["role"] for m in messages]
    assert "assistant" in roles
    assert "assistance" not in roles


def test_history_is_not_merged_into_system_message():
    builder = _builder_with_history()
    result = _result(
        _output("ROLE", "You are an analyst."),
        _output("HISTORY", "user: سلام وقت بخیر\n\nassistant: سلام، من دستیار هوشمند هستم"),
    )

    messages = LLMRequestBuilder().build_messages(result, builder)

    system_content = messages[0]["content"]
    assert "سلام وقت بخیر" not in system_content
    assert "user:" not in system_content
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]


def test_non_history_sections_use_fitted_content_not_raw_rerender():
    builder = PromptBuilder()
    builder.set_role("RAW ROLE TEXT")
    builder.set_system_input("RAW SYSTEM INPUT")

    result = _result(
        _output("ROLE", "FITTED-ROLE"),
        _output("SYSTEM-INPUT", "FITTED-SYSTEM-INPUT"),
    )

    messages = LLMRequestBuilder().build_messages(result, builder)

    assert len(messages) == 1
    system_content = messages[0]["content"]
    assert system_content == "FITTED-ROLE\n\nFITTED-SYSTEM-INPUT"
    assert "RAW ROLE TEXT" not in system_content
    assert "RAW SYSTEM INPUT" not in system_content


def test_context_builder_result_prompt_is_never_used():
    builder = _builder_with_history()
    result = _result(
        _output("ROLE", "You are an analyst."),
        _output("HISTORY", "user: سلام وقت بخیر"),
    )
    assert result.prompt == "MUST-NOT-BE-USED"

    messages = LLMRequestBuilder().build_messages(result, builder)

    flattened = "\n".join(m["content"] for m in messages)
    assert "MUST-NOT-BE-USED" not in flattened


def test_registration_order_is_preserved_for_non_history_sections():
    builder = PromptBuilder()
    builder.set_role("R")
    builder.set_system_input("S")
    builder.set_output_format("O")

    result = _result(
        _output("OUTPUT-FORMAT", "O"),
        _output("ROLE", "R"),
        _output("SYSTEM-INPUT", "S"),
    )

    messages = LLMRequestBuilder().build_messages(result, builder)

    assert messages[0]["content"] == "R\n\nS\n\nO"


def test_no_history_yields_only_system_message():
    builder = PromptBuilder()
    builder.set_role("You are an analyst.")

    messages = LLMRequestBuilder().build_messages(
        _result(_output("ROLE", "You are an analyst.")), builder
    )

    assert messages == [{"role": "system", "content": "You are an analyst."}]


def test_every_batch_item_is_independent():
    builder_a = PromptBuilder()
    builder_a.set_role("Analyst A")
    builder_b = PromptBuilder()
    builder_b.set_role("Analyst B")
    builder_b.set_history(HISTORY_TURNS[:1])

    a = LLMRequestBuilder().build_messages(
        _result(_output("ROLE", "Analyst A")), builder_a
    )
    b = LLMRequestBuilder().build_messages(
        _result(_output("ROLE", "Analyst B")), builder_b
    )

    assert a == [{"role": "system", "content": "Analyst A"}]
    assert [m["role"] for m in b] == ["system", "user"]
    assert b[1] == {"role": "user", "content": "سلام وقت بخیر"}


def test_build_returns_full_openai_compatible_body():
    builder = _builder_with_history()
    result = _result(_output("ROLE", "You are an analyst."))

    body = LLMRequestBuilder().build(
        result,
        builder,
        model="/models/LLM",
        temperature=0.2,
        max_tokens=1024,
    )

    assert body == {
        "model": "/models/LLM",
        "messages": [
            {"role": "system", "content": "You are an analyst."},
            {"role": "user", "content": "سلام وقت بخیر"},
            {"role": "assistant", "content": "سلام، من دستیار هوشمند هستم"},
            {"role": "user", "content": "در مورد این موضوع توضیح بده"},
        ],
        "temperature": 0.2,
        "max_tokens": 1024,
    }


def test_history_system_role_uses_system_value():
    builder = PromptBuilder()
    builder.set_history([HistoryMessage(role=HistoryRole.SYSTEM, content="note")])

    messages = LLMRequestBuilder().build_messages(
        _result(_output("ROLE", "You are an analyst.")), builder
    )

    assert [m["role"] for m in messages] == ["system", "system"]
    assert messages[1] == {"role": "system", "content": "note"}


def test_history_section_received_is_the_same_object():
    builder = _builder_with_history()
    history = builder.get_section("HISTORY")
    assert isinstance(history, HistorySection)
    assert [item.content for item in history.items] == [
        h.content for h in HISTORY_TURNS
    ]