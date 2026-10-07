"""Run the existing Section/context/chat pipeline for a single idea."""

from time import perf_counter

import structlog

from src.application.context.sections import (
    OutputFormatSection,
    SystemInputSection,
    UserInputSection,
)
from src.application.dtos import StructureIdeaDTO, StructuredIdeaResult
from src.application.exceptions import (
    IdeaInputTooLongError,
    IdeaInputValidationError,
    LLMBaseError,
    PromptBudgetExceededError,
)
from src.application.interfaces import (
    IContextBuilder,
    ILLMClient,
    ILLMRequestBuilder,
    IStructureIdeaUseCase,
    IStructuredIdeaOutputParser,
)
from src.application.prompt import PromptBuilder, StructureIdeaPromptConfig
from src.domain.context.tokenizer import Tokenizer
from src.domain.enums import OverflowStrategy
from src.domain.overflow_strategy_stack import OverflowStrategyStack

logger = structlog.get_logger(__name__)


class StructureIdeaUseCase(IStructureIdeaUseCase):
    MAX_IDEA_TOKENS = 512

    def __init__(
        self,
        *,
        tokenizer: Tokenizer,
        context_builder: IContextBuilder,
        request_builder: ILLMRequestBuilder,
        llm_client: ILLMClient,
        output_parser: IStructuredIdeaOutputParser,
        config: StructureIdeaPromptConfig,
        max_prompt_tokens: int,
    ) -> None:
        if any(
            dependency is None
            for dependency in (
                tokenizer,
                context_builder,
                request_builder,
                llm_client,
                output_parser,
                config,
            )
        ):
            raise TypeError("Idea structuring collaborators must be supplied")
        if max_prompt_tokens <= 0:
            raise ValueError("max_prompt_tokens must be positive")
        self._tokenizer = tokenizer
        self._context_builder = context_builder
        self._request_builder = request_builder
        self._llm_client = llm_client
        self._output_parser = output_parser
        self._config = config
        self._max_prompt_tokens = max_prompt_tokens

    async def execute(self, dto: StructureIdeaDTO) -> StructuredIdeaResult:
        started = perf_counter()
        if not isinstance(dto.description, str) or not dto.description.strip():
            raise IdeaInputValidationError("Idea description must be a nonblank string")
        description = dto.description.strip()
        idea_tokens = self._tokenizer.count_tokens(description)
        if idea_tokens > self.MAX_IDEA_TOKENS:
            raise IdeaInputTooLongError("Idea description must not exceed 512 model tokens")

        # Sections and their registry are per-call prompt data, following the
        # existing preparer's pattern. All runtime services are constructor-injected.
        builder = PromptBuilder(seed_defaults=False)
        builder.set_section(
            "SYSTEM-INPUT",
            SystemInputSection(
                self._config.system_instruction,
                demand=self._config.system_demand,
                importance=self._config.system_importance,
                overflow_strategies=OverflowStrategyStack(
                    [OverflowStrategy.TRUNCATE], restart=False, max_restarts=0
                ),
            ),
        )
        builder.set_section(
            "USER-INPUT",
            UserInputSection(
                description,
                demand=self._config.user_demand,
                importance=self._config.user_importance,
                overflow_strategies=OverflowStrategyStack(
                    [OverflowStrategy.TRUNCATE], restart=False, max_restarts=0
                ),
            ),
        )
        builder.set_section(
            "OUTPUT-FORMAT",
            OutputFormatSection(
                self._config.output_format,
                demand=self._config.output_demand,
                importance=self._config.output_importance,
                overflow_strategies=OverflowStrategyStack(
                    [OverflowStrategy.TRUNCATE], restart=False, max_restarts=0
                ),
            ),
        )
        context = self._context_builder.build(builder, self._max_prompt_tokens)
        # ContextBuilder owns allocation and reductions. These three sections
        # are all essential: an undersized configured budget must not silently
        # remove part of the accepted idea or weaken the output instructions.
        if any(section.overflowed for section in context.sections):
            raise PromptBudgetExceededError(
                "Idea, system instructions, and output format must fit the prompt budget"
            )

        messages = self._request_builder.build_messages(context)
        try:
            raw_output = await self._llm_client.complete_chat(messages)
            result = self._output_parser.parse(raw_output)
        except LLMBaseError as exc:
            await logger.awarning(
                "idea_structuring_failed",
                error_type=type(exc).__name__,
                elapsed_ms=round((perf_counter() - started) * 1000, 2),
            )
            raise
        await logger.ainfo(
            "idea_structuring_completed",
            input_length=idea_tokens,
            prompt_length=context.total_tokens,
            length_unit="model_tokens",
            elapsed_ms=round((perf_counter() - started) * 1000, 2),
        )
        return result
