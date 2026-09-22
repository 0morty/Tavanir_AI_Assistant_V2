from collections.abc import Sequence
from dataclasses import dataclass

_DEFAULT_ROLE = (
    "تو یک متخصص خلاصه‌سازی متن هستی که هر بخش (چانک) را جداگانه و وفادار "
    "به محتوای اصلی آن خلاصه می‌کند."
)

_DEFAULT_SYSTEM_INPUT = (
    "چانک‌ها با جداکنندهٔ «---» از هم جدا شده‌اند و این جداکننده جنبهٔ ساختاری دارد:\n"
    "- بین چانک‌ها هیچ‌گونه ادغام، حذف، اضافه یا جابه‌جایی انجام نده.\n"
    "- هر چانک را جداگانه و دقیقاً به ترتیب ورودی خلاصه کن.\n"
    "- معنای اصلی، اعداد، نام‌ها و ارجاع‌ها را حفظ کن.\n"
    "- زبان خروجی باید همان زبان ورودی باشد.\n"
    "- جداکنندهٔ «---» نباید درون هیچ خلاصه‌ای ظاهر شود."
)

_DEFAULT_OUTPUT_FORMAT = (
    "خروجی باید دقیقاً به‌اندازهٔ تعداد چانک‌های ورودی، خلاصه داشته باشد و هر "
    "خلاصه در یک بلوک مستقل با جداکنندهٔ «---» از بلوک بعدی جدا شود:\n"
    "[خلاصهٔ ۱]\n---\n[خلاصهٔ ۲]\n---\n...\n"
    "مطمئن شو هیچ چانکی حذف، ادغام، اضافه یا جابه‌جا نشده است."
)


@dataclass(frozen=True)
class ChunkSummarizationPrompts:
    """The prompt texts used for batched LLM chunk summarization.

    Overridable so tests and operators can tune wording without touching the
    summarizer logic. ``system_input`` pins the chunk-order/separator rules and
    ``output_format`` mandates a strict one-summary-per-chunk layout.
    """

    role: str = _DEFAULT_ROLE
    system_input: str = _DEFAULT_SYSTEM_INPUT
    output_format: str = _DEFAULT_OUTPUT_FORMAT


class ChunkPromptBuilder:
    """Builds the chunk-summarization prompt and parses its 1:1 output.

    The prompt follows the fixed structure ``ROLE -> SYSTEM-INPUT -> CHUNKS ->
    OUTPUT-FORMAT``. The chunks (joined with the structural separator ``---``)
    occupy the USER-INPUT slot of the shared :class:`PromptBuilder`, which
    places them after the system input and before the output format. The same
    ``---`` boundary is what the model must reproduce between summaries, so
    ``split()`` reliably parses the response back into per-chunk summaries.
    """

    CHUNK_DELIMITER = "---"
    CHUNK_SEPARATOR = "\n---\n"

    def __init__(
        self,
        prompts: ChunkSummarizationPrompts | None = None,
    ) -> None:
        self._prompts = prompts if prompts is not None else ChunkSummarizationPrompts()

    def format_chunks(self, chunks: Sequence[str]) -> str:
        """Join ``chunks`` with the structural chunk separator."""
        return self.CHUNK_SEPARATOR.join(chunks)

    def build(self, chunks: Sequence[str]) -> str:
        """Render the full chunk-summarization prompt in fixed section order."""
        from src.application.prompt.prompt_builder import PromptBuilder

        builder = PromptBuilder(seed_defaults=False)
        builder.set_role(self._prompts.role)
        builder.set_system_input(self._prompts.system_input)
        builder.set_user_input(self.format_chunks(chunks))
        builder.set_output_format(self._prompts.output_format)
        return builder.render()

    def split(self, response: str) -> list[str]:
        """Split the model response into one summary per chunk, stripped."""
        return [part.strip() for part in response.split(self.CHUNK_DELIMITER)]