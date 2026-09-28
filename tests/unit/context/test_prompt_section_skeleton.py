from src.application.context import OverflowStrategyDispatcher
from src.application.context.sections import CompressibleSection, PromptSection
from src.application.context.sections.chunks_section import ChunksSection
from src.application.context.sections.history_section import HistorySection
from src.application.context.sections.referenced_collection_section import (
    ReferencedCollectionSection,
)
from src.application.interfaces import IPromptSection
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import GenerationChunk, HistoryMessage
from src.domain.enums import HistoryRole, OverflowStrategy
from src.domain.overflow_strategy_stack import OverflowStrategyStack
from src.infrastructure.services.summarizers import FakeSummarizer


class FakeTokenizer(Tokenizer):
    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        return [(i, (i, i + 1)) for i in range(len(text))]

    def count_tokens(self, text: str) -> int:
        return len(text)


class PlainTextSection(PromptSection):
    def __init__(self, content: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._content = content

    @property
    def section_type(self) -> str:
        return "PLAIN-TEXT"

    def body(self) -> str:
        return self._content


class TaggedSection(ReferencedCollectionSection):
    @property
    def section_type(self) -> str:
        return "TAGGED"

    def item_content(self, item) -> str:
        return f"{item.role.value[0]}{item.content}"


def _messages() -> list[HistoryMessage]:
    return [
        HistoryMessage(HistoryRole.USER, "aa"),
        HistoryMessage(HistoryRole.SYSTEM, "bb"),
    ]


def test_skeleton_implements_compressible_plain_text_defaults():
    section = PlainTextSection("abcdefghij", summarizer=FakeSummarizer())
    assert isinstance(section, (PromptSection, IPromptSection, CompressibleSection))
    prepared = section.prepare()
    assert section.truncate(prepared, 100, tokenizer=FakeTokenizer()).content == "abcdefghij"
    assert section.truncate(prepared, 3, tokenizer=FakeTokenizer()).content == "abc"
    assert section.summarize(prepared, 3).content == "[fake-summarizer-output]"
    assert section.ignore(prepared, 3, tokenizer=FakeTokenizer()) is None
    assert section.prepare() == prepared


def test_dispatch_honours_configured_strategy_priority():
    stack = OverflowStrategyStack([OverflowStrategy.IGNORE, OverflowStrategy.TRUNCATE])
    section = PlainTextSection("abcdefghij", overflow_strategies=stack)
    prepared = section.prepare()
    dispatcher = OverflowStrategyDispatcher()
    assert dispatcher.apply(
        section, OverflowStrategy.IGNORE, prepared, 3, tokenizer=FakeTokenizer()
    ) is None
    assert dispatcher.apply(
        section, OverflowStrategy.TRUNCATE, prepared, 3, tokenizer=FakeTokenizer()
    ).content == "abc"


def test_referenced_section_inherits_single_text_defaults():
    from src.application.context.sections.output_format_section import OutputFormatSection

    section = OutputFormatSection("abcdefghij")
    assert isinstance(section, CompressibleSection)
    assert section.truncate(section.prepare(), 3, tokenizer=FakeTokenizer()).content == "abc"


def test_render_still_frames_running_through_base_compose():
    from src.application.context.sections.role_section import RoleSection

    assert RoleSection("assistant").render() == "assistant"


def test_collection_items_are_source_data():
    chunks = [GenerationChunk("1", "one")]
    section = ChunksSection(chunks)
    assert section.items == tuple(chunks)
    assert section.chunks == tuple(chunks)
    assert HistorySection([]).items == ()


def test_item_separator_joins_items_independently_of_frame_separator():
    section = TaggedSection(_messages(), separator=" <FRAME> ", item_separator=" | ")
    assert section.body() == "uaa | sbb"
    assert section.item_separator == " | "
    assert section.separator == " <FRAME> "


def test_default_item_separator_matches_previous_behavior():
    assert HistorySection(_messages()).body() == "user: aa\n\nsystem: bb"


def test_referenced_collection_section_uses_whole_item_ignore():
    section = TaggedSection(_messages(), item_separator=",")
    prepared = section.prepare()
    assert section.truncate(prepared, 3, tokenizer=FakeTokenizer()) is prepared
    result = section.ignore(prepared, 3, tokenizer=FakeTokenizer())
    assert result.content == "uaa"
    assert result.items == (_messages()[0],)
