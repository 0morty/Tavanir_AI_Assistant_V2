from src.application.context.sections import (
    OutputFormatSection,
    SimilarSuggestionsSection,
    SystemInputSection,
    UserInputSection,
)
from src.application.dtos import ContextBuilderResult, GenerationInput
from src.application.exceptions import (
    InsufficientEvidenceBudgetError,
    PromptBudgetExceededError,
)
from src.application.interfaces.i_context_builder import IContextBuilder
from src.application.interfaces.i_suggestion_prompt_preparer import (
    ISuggestionPromptPreparer,
)
from src.application.prompt.prompt_builder import PromptBuilder
from src.application.prompt.suggestion_analysis_prompt_config import (
    SuggestionAnalysisPromptConfig,
)
from src.domain.context.tokenizer import Tokenizer


class SuggestionPromptPreparer(ISuggestionPromptPreparer):
    """Compiles a token-budgeted prompt for suggestion analysis.

    Enforces upfront budget reservations for fixed sections, guarantees strict
    upstream rank preservation for similar suggestions, and delegates context
    reduction to :class:`IContextBuilder`.
    """

    def __init__(
        self,
        *,
        context_builder: IContextBuilder,
        tokenizer: Tokenizer,
        config: SuggestionAnalysisPromptConfig,
    ) -> None:
        if context_builder is None:
            raise TypeError("context_builder must not be None.")
        if tokenizer is None:
            raise TypeError("tokenizer must not be None.")
        if config is None:
            raise TypeError("config must not be None.")
        self._context_builder = context_builder
        self._tokenizer = tokenizer
        self._config = config

    def prepare(
        self,
        generation_input: GenerationInput,
        max_prompt_tokens: int,
    ) -> ContextBuilderResult:
        if max_prompt_tokens <= 0:
            raise PromptBudgetExceededError(
                f"max_prompt_tokens must be positive, got {max_prompt_tokens}.",
                pointer="/data/maxPromptTokens",
                field_name="max_prompt_tokens",
            )

        curr = generation_input.current_suggestion
        ctx_title = (
            curr.context_title.strip()
            if curr.context_title and curr.context_title.strip()
            else "عمومی"
        )
        user_content = (
            f"عنوان پیشنهاد: {curr.title}\n"
            f"حوزه تخصصی: {ctx_title}\n"
            f"مسئله و چالش: {curr.problem}\n"
            f"راهکار پیشنهادی: {curr.solution}"
        )

        tokens_system = self._tokenizer.count_tokens(self._config.system_instruction)
        tokens_user = self._tokenizer.count_tokens(user_content)
        tokens_output = self._tokenizer.count_tokens(self._config.output_format)
        t_fixed = tokens_system + tokens_user + tokens_output

        has_evidence = bool(generation_input.similar_suggestions)
        num_sections = 4 if has_evidence else 3
        num_separators = num_sections - 1
        sep_tokens = self._tokenizer.count_tokens(PromptBuilder.SECTION_SEPARATOR)
        t_sep = num_separators * sep_tokens

        if t_fixed + t_sep > max_prompt_tokens:
            raise PromptBudgetExceededError(
                f"Fixed prompt sections require {t_fixed + t_sep} tokens, "
                f"exceeding max budget of {max_prompt_tokens}.",
                pointer="/data/maxPromptTokens",
                field_name="max_prompt_tokens",
            )

        usable_budget = max_prompt_tokens - t_sep
        t_remaining = usable_budget - t_fixed

        # Demand-based allocation ensures fixed sections are guaranteed their exact
        # needed capacity, leaving exactly t_remaining for dynamic evidence.
        d_sys = tokens_system / usable_budget
        d_usr = tokens_user / usable_budget
        d_out = tokens_output / usable_budget

        system_section = SystemInputSection(
            self._config.system_instruction,
            demand=d_sys,
            importance=1.0,
        )
        user_section = UserInputSection(
            user_content,
            demand=d_usr,
            importance=1.0,
        )
        output_section = OutputFormatSection(
            self._config.output_format,
            demand=d_out,
            importance=1.0,
        )

        builder = PromptBuilder(seed_defaults=False)
        builder.set_section("SYSTEM-INPUT", system_section)
        builder.set_section("USER-INPUT", user_section)

        if has_evidence:
            d_evi = t_remaining / usable_budget
            evidence_section = SimilarSuggestionsSection(
                suggestions=generation_input.similar_suggestions,
                demand=d_evi,
                importance=0.1,
            )
            # Include the visible citation when checking whether the first item fits.
            first_item_text = evidence_section.prepare().item_bodies[0]
            pre_tokens = self._tokenizer.count_tokens(evidence_section.pre_context)
            frame_sep_tokens = self._tokenizer.count_tokens(evidence_section.separator)
            first_item_tokens = (
                self._tokenizer.count_tokens(first_item_text)
                + pre_tokens
                + frame_sep_tokens
            )

            if first_item_tokens > t_remaining:
                raise InsufficientEvidenceBudgetError(
                    f"Remaining token capacity ({t_remaining}) cannot fit even the "
                    f"highest-ranked similar suggestion ({first_item_tokens} tokens needed).",
                    pointer="/data/similarSuggestions",
                    field_name="similar_suggestions",
                )
            builder.set_section("SIMILAR-SUGGESTIONS", evidence_section)

        builder.set_section("OUTPUT-FORMAT", output_section)

        return self._context_builder.build(builder, max_tokens=max_prompt_tokens)
