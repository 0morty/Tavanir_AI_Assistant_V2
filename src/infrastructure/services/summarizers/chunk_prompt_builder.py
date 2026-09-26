from dataclasses import dataclass

_DEFAULT_ROLE = (
    "تو یک متخصص خلاصه‌سازی متن هستی که متن داده‌شده را جداگانه و وفادار "
    "به محتوای اصلی آن خلاصه می‌کند."
)

_DEFAULT_SYSTEM_INPUT = (
    "متن زیر را خلاصه کن. هر خلاصه باید کاملاً مستقل باشد؛ محتوای این متن را با "
    "هیچ متن دیگری مقایسه، ترکیب یا ادغام نکن. معنای اصلی، اعداد، نام‌ها و "
    "ارجاع‌ها را حفظ کن و زبان خروجی باید همان زبان متن ورودی باشد."
)

_DEFAULT_OUTPUT_FORMAT = (
    "فقط متن خلاصه را برگردان؛ بدون مقدمه، توضیح اضافه یا قالب‌بندی."
)


@dataclass(frozen=True)
class ChunkSummarizationPrompts:
    """The prompt texts used for LLM chunk summarization.

    Overridable so tests and operators can tune wording without touching the
    summarizer logic. Because each chunk is summarized through its own prompt
    (never merged with other chunks), the texts emphasize independent, faithful
    summarization of the single input they wrap.
    """

    role: str = _DEFAULT_ROLE
    system_input: str = _DEFAULT_SYSTEM_INPUT
    output_format: str = _DEFAULT_OUTPUT_FORMAT


class ChunkPromptBuilder:
    """Builds an independent, single-chunk summarization prompt.

    ``build`` renders ``ROLE -> SYSTEM-INPUT -> chunk (USER-INPUT) ->
    OUTPUT-FORMAT`` through the shared :class:`PromptBuilder`. Each call is
    given exactly one chunk, so the model never sees other chunks and every
    chunk keeps a strict 1:1 relationship to its own prompt and, in turn, to
    its own summary.
    """

    def __init__(
        self,
        prompts: ChunkSummarizationPrompts | None = None,
    ) -> None:
        self._prompts = prompts if prompts is not None else ChunkSummarizationPrompts()

    def build(self, chunk: str) -> str:
        """Render the full summarization prompt for a single ``chunk``."""
        from src.application.prompt.prompt_builder import PromptBuilder

        builder = PromptBuilder(seed_defaults=False)
        builder.set_role(self._prompts.role)
        builder.set_system_input(self._prompts.system_input)
        builder.set_user_input(chunk)
        builder.set_output_format(self._prompts.output_format)
        return builder.render()