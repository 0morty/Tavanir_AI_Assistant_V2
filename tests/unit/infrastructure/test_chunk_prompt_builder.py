from src.application.context import ContextBuilder
from src.infrastructure.services.summarizers import (
    ChunkPromptBuilder,
    ChunkSummarizationPrompts,
)


def test_chunk_prompt_builder_renders_fixed_section_order():
    builder = ChunkPromptBuilder()
    prompt = builder.build(["چانک آ", "چانک ب"])

    role = prompt.index("متخصص خلاصه")
    system = prompt.index("ادغام، حذف")
    chunks = prompt.index("چانک آ")
    output = prompt.index("بلوک مستقل")
    assert role < system < chunks < output


def test_chunk_prompt_builder_joins_chunks_with_separator():
    builder = ChunkPromptBuilder()
    prompt = builder.build(["آ", "ب", "ج"])

    assert "آ\n---\nب\n---\nج" in prompt


def test_chunk_prompt_builder_splits_one_summary_per_delimiter():
    builder = ChunkPromptBuilder()
    response = "خلاصه ۱\n---\nخلاصه ۲\n---\nخلاصه ۳"

    assert builder.split(response) == ["خلاصه ۱", "خلاصه ۲", "خلاصه ۳"]


def test_chunk_prompt_builder_split_strips_whitespace():
    builder = ChunkPromptBuilder()

    assert builder.split("  آ  \n---\n ب ") == ["آ", "ب"]


def test_chunk_prompt_builder_honours_custom_prompts():
    prompts = ChunkSummarizationPrompts(
        role="role-x",
        system_input="system-y",
        output_format="format-z",
    )
    builder = ChunkPromptBuilder(prompts=prompts)

    prompt = builder.build(["chunk"])

    assert "role-x" in prompt
    assert "system-y" in prompt
    assert "format-z" in prompt
    assert "chunk" in prompt