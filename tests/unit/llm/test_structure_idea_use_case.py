"""Idea orchestration uses the injected context pipeline and async LLM port."""

from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest

from src.application.context import ContextBuilder, OverflowStrategyDispatcher
from src.application.context.allocation import (
    CapacityAllocator,
    DemandAllocator,
    RedistributionAllocator,
)
from src.application.dtos import StructureIdeaDTO, StructuredIdeaResult
from src.application.exceptions import (
    IdeaInputTooLongError,
    IdeaInputValidationError,
    LLMConnectionError,
    LLMOutputSchemaError,
    PromptBudgetExceededError,
)
from src.application.interfaces import ILLMClient, IStructuredIdeaOutputParser
from src.application.llm import LLMRequestBuilder
from src.application.prompt import PromptBuilder, StructureIdeaPromptConfig
from src.application.use_cases.structure_idea_use_case import StructureIdeaUseCase
from src.domain.context.tokenizer import Tokenizer
from src.domain.enums import OverflowStrategy
from src.infrastructure.services.llm.structured_idea_output_parser import (
    StructuredIdeaOutputParser,
)


VALID_OUTPUT = (
    "{title}\nOccupancy lighting\n***\n"
    "{current problem}\nLights stay on in empty rooms.\n***\n"
    "{solutions}\nInstall occupancy sensors.\n***\n"
    "{advantage}\nPotentially lower consumption.\n***\n"
    "{disadvantage}\nInstallation cost is unknown."
)


class CharacterTokenizer(Tokenizer):
    @property
    def supports_offset_mapping(self) -> bool:
        return True

    def encode(self, text: str) -> list[tuple[int, tuple[int, int]]]:
        return [(ord(char), (i, i + 1)) for i, char in enumerate(text)]

    def count_tokens(self, text: str) -> int:
        return len(text)


class RecordingContextBuilder(ContextBuilder):
    def __init__(self, tokenizer: Tokenizer) -> None:
        super().__init__(
            tokenizer=tokenizer,
            capacity_allocator=CapacityAllocator(DemandAllocator(), RedistributionAllocator()),
            dispatcher=OverflowStrategyDispatcher(),
        )
        self.calls = []

    def build(self, builder: PromptBuilder, max_tokens: int):
        result = super().build(builder, max_tokens)
        self.calls.append((builder, max_tokens, result))
        return result


class RecordingLLM(ILLMClient):
    def __init__(self, output: str = VALID_OUTPUT, error: Exception | None = None) -> None:
        self.output = output
        self.error = error
        self.calls = []

    def complete(self, prompt: str) -> str:
        raise AssertionError("Final generation must invoke the async chat operation")

    async def complete_chat(self, messages) -> str:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return self.output


def collaborators():
    tokenizer = CharacterTokenizer()
    return {
        "tokenizer": tokenizer,
        "context_builder": RecordingContextBuilder(tokenizer),
        "request_builder": LLMRequestBuilder(),
        "llm_client": RecordingLLM(),
        "output_parser": StructuredIdeaOutputParser(),
        "config": StructureIdeaPromptConfig(),
        "max_prompt_tokens": 4096,
    }


@pytest.mark.asyncio
async def test_complete_pipeline_uses_explicit_sections_and_parses_actual_completion():
    deps = collaborators()
    result = await StructureIdeaUseCase(**deps).execute(
        StructureIdeaDTO(description="  Install occupancy sensors.  ")
    )

    assert result == StructuredIdeaResult(
        title="Occupancy lighting",
        current_problem="Lights stay on in empty rooms.",
        solution="Install occupancy sensors.",
        advantage="Potentially lower consumption.",
        disadvantage="Installation cost is unknown.",
    )
    builder, budget, context = deps["context_builder"].calls[0]
    assert isinstance(builder, PromptBuilder)
    assert budget == 4096
    sections = list(builder.sections)
    assert [section.section_type for section in sections] == [
        "SYSTEM-INPUT", "USER-INPUT", "OUTPUT-FORMAT"
    ]
    assert [section.demand for section in sections] == [0.25, 0.25, 0.5]
    assert [section.importance for section in sections] == [1.0, 1.0, 1.0]
    for section in sections:
        assert section.overflow_strategies.strategies == (OverflowStrategy.TRUNCATE,)
        assert section.overflow_strategies.restart is False
        assert section.overflow_strategies.max_restarts == 0
    assert not any(section.overflowed for section in context.sections)
    assert len(deps["llm_client"].calls) == 1
    messages = deps["llm_client"].calls[0]
    assert messages == LLMRequestBuilder().build_messages(context)
    assert messages[1] == {"role": "user", "content": "Install occupancy sensors."}
    assert deps["config"].system_instruction in messages[0]["content"]
    assert deps["config"].output_format in messages[0]["content"]


@pytest.mark.asyncio
async def test_final_request_uses_context_builder_processed_outputs():
    class TransformingContextBuilder(RecordingContextBuilder):
        def build(self, builder: PromptBuilder, max_tokens: int):
            original = super().build(builder, max_tokens)
            outputs = tuple(
                replace(output, content="Processed idea")
                if output.section_type == "USER-INPUT" else output
                for output in original.sections
            )
            return replace(original, sections=outputs)

    deps = collaborators()
    deps["context_builder"] = TransformingContextBuilder(deps["tokenizer"])
    await StructureIdeaUseCase(**deps).execute(StructureIdeaDTO(description="Original idea"))
    messages = deps["llm_client"].calls[0]
    assert messages[1]["content"] == "Processed idea"
    assert all("Original idea" not in message["content"] for message in messages)


@pytest.mark.asyncio
async def test_repeated_calls_have_independent_prompt_sections():
    deps = collaborators()
    use_case = StructureIdeaUseCase(**deps)
    await use_case.execute(StructureIdeaDTO(description="First idea"))
    await use_case.execute(StructureIdeaDTO(description="Second idea"))
    calls = deps["context_builder"].calls
    assert calls[0][0] is not calls[1][0]
    assert [request[1]["content"] for request in deps["llm_client"].calls] == [
        "First idea", "Second idea"
    ]
    assert calls[0][2].sections[1].content == "First idea"
    assert calls[1][2].sections[1].content == "Second idea"


@pytest.mark.asyncio
async def test_512_tokens_are_accepted():
    deps = collaborators()
    await StructureIdeaUseCase(**deps).execute(StructureIdeaDTO(description="x" * 512))
    assert deps["llm_client"].calls[0][1]["content"] == "x" * 512


@pytest.mark.asyncio
async def test_513_tokens_are_rejected_before_context_or_llm():
    deps = collaborators()
    with pytest.raises(IdeaInputTooLongError) as error:
        await StructureIdeaUseCase(**deps).execute(StructureIdeaDTO(description="x" * 513))
    assert error.value.pointer == "/data/description"
    assert deps["context_builder"].calls == []
    assert deps["llm_client"].calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("description", ["", " \t\n", None, 123])
async def test_invalid_descriptions_are_rejected_before_context_or_llm(description):
    deps = collaborators()
    with pytest.raises(IdeaInputValidationError):
        await StructureIdeaUseCase(**deps).execute(StructureIdeaDTO(description=description))
    assert deps["context_builder"].calls == []
    assert deps["llm_client"].calls == []


@pytest.mark.asyncio
async def test_context_builder_handles_overflow_but_essential_content_is_not_sent_cut():
    deps = collaborators()
    deps["max_prompt_tokens"] = 100
    with pytest.raises(PromptBudgetExceededError):
        await StructureIdeaUseCase(**deps).execute(StructureIdeaDTO(description="Sensor lighting"))
    context = deps["context_builder"].calls[0][2]
    assert any(output.overflowed for output in context.sections)
    assert context.total_tokens <= 100
    assert deps["llm_client"].calls == []


@pytest.mark.asyncio
async def test_generation_errors_propagate_through_existing_hierarchy():
    deps = collaborators()
    expected = LLMConnectionError("Provider unavailable")
    deps["llm_client"] = RecordingLLM(error=expected)
    with pytest.raises(LLMConnectionError) as error:
        await StructureIdeaUseCase(**deps).execute(StructureIdeaDTO(description="Sensor lighting"))
    assert error.value is expected


@pytest.mark.asyncio
async def test_malformed_completion_is_not_returned_as_success():
    deps = collaborators()
    deps["llm_client"] = RecordingLLM(output='{"title": "Invalid format"}')
    with pytest.raises(LLMOutputSchemaError):
        await StructureIdeaUseCase(**deps).execute(StructureIdeaDTO(description="Sensor lighting"))


@pytest.mark.asyncio
async def test_injected_parser_is_used():
    class RecordingParser(IStructuredIdeaOutputParser):
        def __init__(self) -> None:
            self.calls = []
            self.result = StructuredIdeaResult("t", "p", "s", "a", "d")

        def parse(self, raw_output: str) -> StructuredIdeaResult:
            self.calls.append(raw_output)
            return self.result

    deps = collaborators()
    parser = RecordingParser()
    deps["output_parser"] = parser
    result = await StructureIdeaUseCase(**deps).execute(StructureIdeaDTO(description="Sensor lighting"))
    assert parser.calls == [VALID_OUTPUT]
    assert result is parser.result


@pytest.mark.parametrize("dependency", [
    "tokenizer", "context_builder", "request_builder", "llm_client", "output_parser", "config"
])
def test_required_collaborators_cannot_be_omitted_or_replaced_with_none(dependency):
    deps = collaborators()
    deps.pop(dependency)
    with pytest.raises(TypeError):
        StructureIdeaUseCase(**deps)
    deps[dependency] = None
    with pytest.raises(TypeError):
        StructureIdeaUseCase(**deps)


def test_prompt_budget_is_required_and_positive():
    deps = collaborators()
    deps.pop("max_prompt_tokens")
    with pytest.raises(TypeError):
        StructureIdeaUseCase(**deps)
    for budget in (0, -1):
        with pytest.raises(ValueError):
            StructureIdeaUseCase(**deps, max_prompt_tokens=budget)


@pytest.mark.asyncio
async def test_observability_records_lengths_without_idea_or_generated_content():
    deps = collaborators()
    with patch("src.application.use_cases.structure_idea_use_case.logger") as logger:
        logger.ainfo = AsyncMock()
        await StructureIdeaUseCase(**deps).execute(StructureIdeaDTO(description="Private idea"))
    logger.ainfo.assert_awaited_once()
    event = str(logger.ainfo.call_args)
    assert "Private idea" not in event
    assert "Occupancy lighting" not in event
    assert logger.ainfo.call_args.kwargs["input_length"] == len("Private idea")
    assert logger.ainfo.call_args.kwargs["length_unit"] == "model_tokens"
