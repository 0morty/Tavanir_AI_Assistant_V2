from __future__ import annotations

from dataclasses import dataclass

from src.application.exceptions import LLMAPIError
from src.application.interfaces.i_context_builder import IContextBuilder
from src.application.interfaces.i_llm_client import ILLMClient
from src.application.interfaces.i_reference_generator import IReferenceGenerator
from src.application.interfaces.i_template_validator import ITemplateValidator
from src.application.reference.reference_cache import ReferenceCache
from src.application.reference.template_filler import substitute_placeholders
from src.domain.entities import Reference, ReferenceDetails

_DEFAULT_ROLE = (
    "تو یک مهندس پرامپت متخصص هستی. وظیفه‌ی تو این است که فقط بر اساس "
    "ویژگی‌های ارائه‌شده، یک عبارت ارجاع کوتاه، طبیعی و خوانا برای یک منبع تولید کنی."
)

_DEFAULT_SYSTEM_INPUT = (
    "قالب ارجاع (Reference Template) یک جمله‌ی کوتاه به زبان طبیعی است که محل و "
    "مشخصات منبع محتوا را توصیف می‌کند؛ مانند صفحه، ماده، فصل یا نویسنده.\n"
    "در این قالب فقط از توکن‌های جایگزین به شکل [name] برای مقادیر ویژگی‌ها استفاده کن.\n"
    "قالب باید فقط به ویژگی‌هایی که در بخش Properties آمده‌اند اشاره کند و هرگز ویژگی "
    "دیگری را ابداع یا فرض نکند.\n"
    "قالب باید یک جمله باشد و نباید مقدار واقعی هیچ ویژگی را در خود داشته باشد.\n"
    "متن محتوای اصلی را در قالب نیاور؛ فقط جمله‌ی ارجاع را بساز."
)

_DEFAULT_OUTPUT_FORMAT = (
    "فقط متن قالب ارجاع را برگردان و هیچ توضیح، نقل‌قول یا قالب‌بندی اضافی ارائه نده.\n"
    "نام ویژگی‌ها را دقیقاً با همان نام‌هایی که در بخش Properties آمده‌اند و به شکل "
    "[name] بنویس."
)

_DEFAULT_ERROR_HEADING = "Template Validator برای قالبی که ساختی یک خطا ایجاد کرد:"


@dataclass(frozen=True)
class ReferenceGenerationPrompts:
    """The prompt texts used for reference-template generation.

    Overridable so tests and operators can tune wording without touching the
    generator logic. ``error_heading`` prefixes the exact ``TemplateValidator``
    error on every retry attempt.
    """

    role: str = _DEFAULT_ROLE
    system_input: str = _DEFAULT_SYSTEM_INPUT
    output_format: str = _DEFAULT_OUTPUT_FORMAT
    error_heading: str = _DEFAULT_ERROR_HEADING


class LLMBaseReferenceGenerator(IReferenceGenerator):
    """Generate a Reference's human-readable text through an LLM.

    The generation prompt is assembled by the shared ``PromptBuilder`` from the
    standard Sections -- ROLE, SYSTEM-INPUT, ERROR, PROPERTIES, OUTPUT-FORMAT,
    in exactly that order -- and token-budgeted by ``ContextBuilder``, so
    reference-template generation follows the same prompt architecture as the
    rest of the Generation API. No parallel prompt-building mechanism is
    introduced here.

    The returned template is validated with ``TemplateValidator``:

    - valid template -> filled deterministically (``substitute_placeholders``);
    - invalid template -> retried, with the **exact** validator error included
      in the ERROR section of the next attempt's prompt so the LLM can fix the
      mistake;
    - after all attempts fail validation -> raise an LLM error, leaving the
      cache unchanged rather than rendering a malformed template.

    Validated templates are persisted by ``cache`` (§17): the property-shape
    hash computed from :class:`ReferenceDetails` is the key, so a later
    Reference sharing the same property shape reuses the cached template and
    skips the LLM entirely (§18 cache-resolution flow). Cached entries are
    revalidated before use so an old invalid entry cannot be rendered. Only
    templates that passed validation are cached; a reference with no available
    properties renders as ``""`` and never touches the cache.

    Retry state (counter, error carry-over) lives only in this generator;
    ``ContextBuilder``/``PromptBuilder``/sections/``TemplateValidator`` are
    unchanged elsewhere.
    """

    def __init__(
        self,
        llm_client: ILLMClient,
        *,
        max_attempts: int = 3,
        max_tokens: int = 2048,
        validator: ITemplateValidator,
        prompts: ReferenceGenerationPrompts | None = None,
        context_builder: IContextBuilder,
        cache: ReferenceCache,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if max_tokens < 0:
            raise ValueError("max_tokens must be non-negative")
        self._llm_client = llm_client
        self._max_attempts = max_attempts
        self._max_tokens = max_tokens
        self._validator = validator
        self._prompts = prompts if prompts is not None else ReferenceGenerationPrompts()
        self._context_builder = context_builder
        self._cache = cache

    def generate(self, reference: Reference) -> str:
        """Return the concrete reference text for ``reference``.

        A Reference with no available properties renders as ``""``: there is
        nothing to describe, matching :class:`DeterministicReferenceGenerator`.
        Otherwise the property-shape hash is resolved through the cache; only
        a cache miss triggers LLM template generation.
        """
        details = reference.details
        if not details.properties:
            return ""
        shape_hash = details.hash()
        template = self._cache.load(shape_hash)
        if template is None or not self._validator.validate(template, details).valid:
            template = self._resolve_template(details)
            self._cache.save(shape_hash, template)
        return substitute_placeholders(template, reference)

    def _resolve_template(self, details: ReferenceDetails) -> str:
        """Return a validated template or fail after the configured attempts."""
        validation_message = ""
        for _ in range(self._max_attempts):
            prompt = self._build_prompt(details, validation_message)
            template = self._llm_client.complete(prompt).strip()
            result = self._validator.validate(template, details)
            if result.valid:
                return template
            validation_message = result.error_message()
        raise LLMAPIError(
            "Reference template validation failed after "
            f"{self._max_attempts} attempts: {validation_message}"
        )

    def _build_prompt(self, details: ReferenceDetails, validation_message: str) -> str:
        error_content = ""
        if validation_message:
            error_content = f"{self._prompts.error_heading}\n{validation_message}"

        # Deferred imports: the context/prompt packages import the reference
        # package (DeterministicReferenceGenerator) at module load time, so
        # importing them here avoids a circular import during package init.
        from src.application.context.sections.error_section import ErrorSection
        from src.application.context.sections.properties_section import (
            PropertiesSection,
        )
        from src.application.prompt.prompt_builder import PromptBuilder

        builder = PromptBuilder(seed_defaults=False)
        builder.set_role(self._prompts.role)
        builder.set_system_input(self._prompts.system_input)
        builder.add_section(ErrorSection(error_content))
        builder.add_section(PropertiesSection(details))
        builder.set_output_format(self._prompts.output_format)

        return self._context_builder.build(
            builder, max_tokens=self._max_tokens
        ).prompt