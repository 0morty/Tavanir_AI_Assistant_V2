"""Provider-neutral final Generation orchestration."""

from src.application.dtos import GenerationInput, GenerationResult
from src.application.interfaces.i_generate_suggestion_use_case import (
    IGenerateSuggestionUseCase,
)
from src.application.interfaces.i_llm_client import ILLMClient
from src.application.interfaces.i_llm_request_builder import ILLMRequestBuilder
from src.application.interfaces.i_output_parser import IOutputParser
from src.application.interfaces.i_suggestion_prompt_preparer import (
    ISuggestionPromptPreparer,
)


class GenerateSuggestionUseCase(IGenerateSuggestionUseCase):
    """Prepare fitted evidence, invoke a chat model, and validate its result."""

    def __init__(
        self,
        *,
        prompt_preparer: ISuggestionPromptPreparer,
        request_builder: ILLMRequestBuilder,
        llm_client: ILLMClient,
        output_parser: IOutputParser,
        max_prompt_tokens: int,
    ) -> None:
        if any(
            dependency is None
            for dependency in (
                prompt_preparer,
                request_builder,
                llm_client,
                output_parser,
            )
        ):
            raise TypeError("Generation collaborators must be supplied")
        if max_prompt_tokens <= 0:
            raise ValueError("max_prompt_tokens must be positive")
        self._prompt_preparer = prompt_preparer
        self._request_builder = request_builder
        self._llm_client = llm_client
        self._output_parser = output_parser
        self._max_prompt_tokens = max_prompt_tokens

    async def execute(self, generation_input: GenerationInput) -> GenerationResult:
        prepared = self._prompt_preparer.prepare_with_citations(
            generation_input, self._max_prompt_tokens
        )
        messages = self._request_builder.build_messages(prepared.context)
        raw_output = await self._llm_client.complete_chat(messages)
        return self._output_parser.parse(raw_output, citation_map=prepared.citation_map)
