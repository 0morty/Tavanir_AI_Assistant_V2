from dataclasses import dataclass

from src.application.interfaces.i_llm_client import ILLMClient
from src.application.interfaces.i_llm_summarizer import ILLMSummarizer

_DEFAULT_ROLE = (
    "تو یک متخصص خلاصه‌سازی متن هستی که فقط بر اساس متنی که به او داده "
    "می‌شود، خلاصه‌ای فشرده و وفادار به متن تولید می‌کند."
)

_DEFAULT_SYSTEM_INPUT = (
    "متن زیر را خلاصه کن. معنای اصلی، اعداد، نام‌ها و ارجاع‌ها باید حفظ شوند. "
    "زبان خروجی باید همان زبان متن ورودی باشد."
)

_DEFAULT_OUTPUT_FORMAT = (
    "فقط متن خلاصه را برگردان؛ بدون مقدمه، توضیح اضافه، یا قالب‌بندی.\n"
    "خلاصه نباید از ظرفیت توکن تعیین‌شده تجاوز کند."
)

_DEFAULT_MAX_TOKENS_INSTRUCTION = (
    "خلاصه باید در حداکثر {max_tokens} توکن تهیه شود."
)


@dataclass(frozen=True)
class SummarizationPrompts:
    """The prompt texts used for LLM summarization.

    Overridable so tests and operators can tune wording without touching the
    summarizer logic. ``max_tokens_instruction`` carries the token budget into
    the prompt; ``output_format`` pins the expected answer shape.
    """

    role: str = _DEFAULT_ROLE
    system_input: str = _DEFAULT_SYSTEM_INPUT
    output_format: str = _DEFAULT_OUTPUT_FORMAT
    max_tokens_instruction: str = _DEFAULT_MAX_TOKENS_INSTRUCTION


class LLMSummarizer(ILLMSummarizer):
    """Summarize a text through an injected LLM.

    The summary prompt is assembled by the shared ``PromptBuilder`` from the
    standard sections -- ROLE, SYSTEM-INPUT, USER-INPUT (+ OUTPUT-FORMAT when a
    token budget is provided) -- so summarization follows the same prompt
    architecture as the rest of the Generation API. The token budget supplied
    through :meth:`summarize` is surfaced as an OUTPUT-FORMAT instruction; the
    ``ContextBuilder`` safety net enforces the exact cap regardless of what the
    model returns.

    The LLM client is injected through the constructor (:class:`ILLMClient`),
    never instantiated here.
    """

    def __init__(
        self,
        llm_client: ILLMClient,
        *,
        prompts: SummarizationPrompts | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._prompts = prompts if prompts is not None else SummarizationPrompts()

    def summarize(self, text: str, *, max_tokens: int | None = None) -> str:
        """Return the model's summary of ``text``, or ``""`` for empty input."""
        if not text or not text.strip():
            return ""

        # Deferred import: the context/prompt packages import the reference
        # package at module load time, so importing PromptBuilder here avoids a
        # circular import during package init.
        from src.application.prompt.prompt_builder import PromptBuilder

        builder = PromptBuilder(seed_defaults=False)
        builder.set_role(self._prompts.role)
        builder.set_system_input(self._prompts.system_input)
        builder.set_user_input(text)
        budget = ""
        if max_tokens is not None and max_tokens > 0:
            budget = self._prompts.max_tokens_instruction.format(max_tokens=max_tokens)
        if budget:
            builder.set_output_format(f"{budget}\n{self._prompts.output_format}")
        else:
            builder.set_output_format(self._prompts.output_format)

        return self._llm_client.complete(builder.render()).strip()