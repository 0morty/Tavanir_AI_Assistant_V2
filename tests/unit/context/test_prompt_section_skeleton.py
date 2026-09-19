import pytest

from src.application.context.sections.history_section import HistorySection
from src.application.context.sections.referenced_collection_section import (
    ReferencedCollectionSection,
)
from src.application.context.sections.chunks_section import ChunksSection
from src.application.context.sections import PromptSection
from src.application.interfaces import IPromptSection
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import GenerationChunk, HistoryMessage
from src.domain.enums import HistoryRole, OverflowStrategy
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class FakeTokenizer(Tokenizer):
    """Char-based tokenizer: every character counts as one token."""

    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        return [(i, (i, i + 1)) for i in range(len(text))]

    def count_tokens(self, text: str) -> int:
        return len(text)


class PlainTextSection(PromptSection):
    """A plain prompt section used to exercise the base default behavior."""

    def __init__(self, content: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._content = content

    @property
    def section_type(self) -> str:
        return "PLAIN-TEXT"

    def body(self) -> str:
        return self._content


def test_base_ships_default_fit_to_capacity():
    section = PlainTextSection("abcdefghij")
    assert isinstance(section, PromptSection)
    assert isinstance(section, IPromptSection)
    assert section.fit_to_capacity(
        "abcdefghij", 100, tokenizer=FakeTokenizer()
    ) == "abcdefghij"
    assert section.fit_to_capacity("abcdefghij", 3, tokenizer=FakeTokenizer()) == "abc"


def test_base_fit_to_capacity_honours_configured_stack():
    stack = OverflowStrategyStack([OverflowStrategy.IGNORE, OverflowStrategy.TRUNCATE])
    section = PlainTextSection("abcdefghij", overflow_strategies=stack)
    assert section.fit_to_capacity("abcdefghij", 3, tokenizer=FakeTokenizer()) == "abc"


def test_referenced_section_inherits_default_fit_to_capacity():
    from src.application.context.sections.output_format_section import (
        OutputFormatSection,
    )

    section = OutputFormatSection("abcdefghij")
    assert section.fit_to_capacity("abcdefghij", 3, tokenizer=FakeTokenizer()) == "abc"


def test_render_still_frames_running_through_base_compose():
    from src.application.context.sections.role_section import RoleSection

    assert RoleSection("assistant").render() == "assistant"


def test_collection_items_property_is_generic():
    assert ChunksSection([]).items == []
    assert HistorySection([]).items == []


def test_collection_no_longer_exposes_chunks_name():
    with pytest.raises(AttributeError):
        _ = ChunksSection([]).chunks


def _messages() -> list[HistoryMessage]:
    return [
        HistoryMessage(role=HistoryRole.USER, content="aa"),
        HistoryMessage(role=HistoryRole.SYSTEM, content="bb"),
    ]


class TaggedSection(ReferencedCollectionSection):
    """Concrete collection section passing base kwargs straight through."""

    @property
    def section_type(self) -> str:
        return "TAGGED"

    def item_content(self, item) -> str:
        return f"{item.role.value[0]}{item.content}"


def test_item_separator_joins_items_independently_of_frame_separator():
    section = TaggedSection(
        _messages(), separator=" <FRAME> ", item_separator=" | "
    )
    assert section.body() == "uaa | sbb"
    assert section.item_separator == " | "
    assert section.separator == " <FRAME> "


def test_default_item_separator_matches_previous_behavior():
    section = HistorySection(_messages())
    assert section.body() == "user: aa\n\nsystem: bb"


def test_referenced_collection_section_uses_item_separator_for_overflow():
    section = TaggedSection(_messages(), item_separator=",")
    result = section.fit_to_capacity(
        _messages(), 100, tokenizer=FakeTokenizer()
    )
    assert result == "uaa,sbb"