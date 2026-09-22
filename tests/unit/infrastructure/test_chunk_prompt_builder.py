from src.application.context import ContextBuilder
from src.infrastructure.services.summarizers import (
    ChunkPromptBuilder,
    ChunkSummarizationPrompts,
)


def test_chunk_prompt_builder_renders_fixed_section_order():
    builder = ChunkPromptBuilder()
    prompt = builder.build("چانک آ")

    role = prompt.index("متخصص خلاصه")
    system = prompt.index("متن زیر را خلاصه کن")
    chunk = prompt.index("چانک آ")
    output = prompt.index("فقط متن خلاصه")
    assert role < system < chunk < output


def test_chunk_prompt_builder_embeds_exactly_one_chunk():
    builder = ChunkPromptBuilder()
    prompt = builder.build("چانک آ")

    assert "چانک آ" in prompt
    assert "---" not in prompt


def test_chunk_prompt_builder_builds_independent_prompt_per_chunk():
    builder = ChunkPromptBuilder()
    first = builder.build("چانک آ")
    second = builder.build("چانک ب")

    assert "چانک آ" in first and "چانک ب" not in first
    assert "چانک ب" in second and "چانک آ" not in second


def test_chunk_prompt_builder_honours_custom_prompts():
    prompts = ChunkSummarizationPrompts(
        role="role-x",
        system_input="system-y",
        output_format="format-z",
    )
    builder = ChunkPromptBuilder(prompts=prompts)

    prompt = builder.build("chunk")

    assert "role-x" in prompt
    assert "system-y" in prompt
    assert "format-z" in prompt
    assert "chunk" in prompt