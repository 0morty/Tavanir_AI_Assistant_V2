"""Unit tests for serializing processed context into chat messages.

Importing the allocation chain first avoids the repository's existing
package-import cycle when PromptBuilder is imported directly.
"""

import src.application.context.allocation.expansion_request  # noqa: F401,PLC0415

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
    history_messages: tuple[HistoryMessage, ...] | None = None,
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
        items=history_messages,
    )


def _result(
    *outputs: SectionOutput, section_separator: str = "\n\n"
) -> ContextBuilderResult:
    return ContextBuilderResult(
        prompt="MUST-NOT-BE-USED",
        sections=outputs,
        budget_tokens=100,
        total_tokens=0,
        section_separator=section_separator,
    )


def _builder_with_history() -> PromptBuilder:
    builder = PromptBuilder()
    builder.set_history(HISTORY_TURNS)
    return builder


def test_history_becomes_separate_messages_in_order():
    result = _result(
        _output("ROLE", "You are an analyst."),
        _output(
            "HISTORY",
            "user: سلام وقت بخیر\n\nassistant: سلام، من دستیار هوشمند هستم",
            history_messages=tuple(HISTORY_TURNS),
        ),
        _output("SYSTEM-INPUT", "Base on the material only."),
    )

    messages = LLMRequestBuilder().build_messages(result)

    assert [m["role"] for m in messages] == [
        "system", "user", "assistant", "user"
    ]
    assert [m["content"] for m in messages[1:]] == [
        turn.content for turn in HISTORY_TURNS
    ]


def test_assistant_role_spelling_is_correct():
    assert HistoryRole.ASSISTANT.value == "assistant"
    result = _result(
        _output("ROLE", "You are an analyst."),
        _output("HISTORY", "fitted history", history_messages=tuple(HISTORY_TURNS)),
    )

    roles = [m["role"] for m in LLMRequestBuilder().build_messages(result)]

    assert "assistant" in roles
    assert "assistance" not in roles


def test_history_is_not_merged_into_system_message():
    result = _result(
        _output("ROLE", "You are an analyst."),
        _output(
            "HISTORY",
            "user: سلام وقت بخیر\n\nassistant: سلام، من دستیار هوشمند هستم",
            history_messages=tuple(HISTORY_TURNS),
        ),
    )

    messages = LLMRequestBuilder().build_messages(result)

    assert "سلام وقت بخیر" not in messages[0]["content"]
    assert "user:" not in messages[0]["content"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]


def test_non_history_sections_use_fitted_content_not_raw_rerender():
    result = _result(
        _output("ROLE", "FITTED-ROLE"),
        _output("SYSTEM-INPUT", "FITTED-SYSTEM-INPUT"),
    )

    messages = LLMRequestBuilder().build_messages(result)

    assert messages == [
        {"role": "system", "content": "FITTED-ROLE\n\nFITTED-SYSTEM-INPUT"}
    ]


def test_context_builder_result_prompt_is_never_used():
    result = _result(
        _output("ROLE", "You are an analyst."),
        _output(
            "HISTORY",
            "user: سلام وقت بخیر",
            history_messages=(HISTORY_TURNS[0],),
        ),
    )

    flattened = "\n".join(
        message["content"] for message in LLMRequestBuilder().build_messages(result)
    )

    assert result.prompt == "MUST-NOT-BE-USED"
    assert "MUST-NOT-BE-USED" not in flattened


def test_result_order_is_preserved_for_non_history_sections():
    result = _result(
        _output("ROLE", "R"),
        _output("SYSTEM-INPUT", "S"),
        _output("OUTPUT-FORMAT", "O"),
    )

    messages = LLMRequestBuilder().build_messages(result)

    assert messages[0]["content"] == "R\n\nS\n\nO"


def test_result_separator_is_used_for_non_history_sections():
    result = _result(
        _output("ROLE", "R"),
        _output("SYSTEM-INPUT", "S"),
        section_separator="\n--\n",
    )

    assert LLMRequestBuilder().build_messages(result) == [
        {"role": "system", "content": "R\n--\nS"}
    ]


def test_no_history_yields_only_system_message():
    result = _result(_output("ROLE", "You are an analyst."))

    assert LLMRequestBuilder().build_messages(result) == [
        {"role": "system", "content": "You are an analyst."}
    ]


def test_every_batch_item_is_independent():
    a = LLMRequestBuilder().build_messages(
        _result(_output("ROLE", "Analyst A"))
    )
    b = LLMRequestBuilder().build_messages(
        _result(
            _output("ROLE", "Analyst B"),
            _output(
                "HISTORY",
                "user: سلام وقت بخیر",
                history_messages=(HISTORY_TURNS[0],),
            ),
        )
    )

    assert a == [{"role": "system", "content": "Analyst A"}]
    assert [m["role"] for m in b] == ["system", "user"]
    assert b[1] == {"role": "user", "content": "سلام وقت بخیر"}


def test_build_returns_full_openai_compatible_body():
    result = _result(
        _output("ROLE", "You are an analyst."),
        _output("HISTORY", "fitted history", history_messages=tuple(HISTORY_TURNS)),
    )

    body = LLMRequestBuilder().build(
        result,
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
    result = _result(
        _output("ROLE", "You are an analyst."),
        _output(
            "HISTORY",
            "system: note",
            history_messages=(
                HistoryMessage(role=HistoryRole.SYSTEM, content="note"),
            ),
        ),
    )

    messages = LLMRequestBuilder().build_messages(result)

    assert [m["role"] for m in messages] == ["system", "system"]
    assert messages[1] == {"role": "system", "content": "note"}


def test_processed_history_metadata_is_required():
    result = _result(_output("HISTORY", "user: fitted"))

    try:
        LLMRequestBuilder().build_messages(result)
    except ValueError as exc:
        assert "processed HISTORY" in str(exc) or "Processed HISTORY" in str(exc)
    else:
        raise AssertionError("Missing processed history must be rejected")


def test_history_section_received_is_the_same_object():
    builder = _builder_with_history()
    history = builder.get_section("HISTORY")
    assert isinstance(history, HistorySection)
    assert [item.content for item in history.items] == [
        turn.content for turn in HISTORY_TURNS
    ]


def test_user_input_and_evidence_are_user_messages_with_output_schema_in_system():
    result = _result(
        _output("SYSTEM-INPUT", "Instructions"),
        _output("USER-INPUT", "Current suggestion"),
        _output("SIMILAR-SUGGESTIONS", "Evidence [similar 001]"),
        _output("OUTPUT-FORMAT", "Return JSON"),
    )

    assert LLMRequestBuilder().build_messages(result) == [
        {"role": "system", "content": "Instructions\n\nReturn JSON"},
        {"role": "user", "content": "Current suggestion\n\nEvidence [similar 001]"},
    ]
