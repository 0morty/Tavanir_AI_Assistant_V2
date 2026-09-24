"""Build the chat ``messages`` payload for one ``ContextBuilderResult``.

The LLM request layer needs message-aware sections: ``HistorySection`` must
become real chat turns instead of being flattened into the prompt text. This
module owns that transformation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from src.application.dtos import ContextBuilderResult

if TYPE_CHECKING:
    from src.application.context.sections.history_section import HistorySection
    from src.application.prompt.prompt_builder import PromptBuilder


class LLMRequestBuilder:
    """Convert one :class:`ContextBuilderResult` into chat ``messages``.

    The ``HISTORY`` section is lifted out of the flat prompt and becomes one
    standalone message per history turn, using the role value verbatim from
    ``HistoryRole`` (``user`` / ``system`` / ``assistant``). Every other
    section keeps its **fitted** content (the content actually placed by
    ``ContextBuilder`` after allocation/overflow handling) and is joined, in
    the builder's registration order, into a single ``system`` message.

    The join reuses :meth:`PromptBuilder.assemble` -- the exact mechanism
    ``PromptBuilder.render()`` delegates to -- applied to the fitted
    ``SectionOutput`` contents. ``ContextBuilderResult.prompt`` is never used:
    history was already flattened there.
    """

    def build_messages(
        self,
        context_result: ContextBuilderResult,
        builder: PromptBuilder,
    ) -> list[dict[str, str]]:
        """Return OpenAI-compatible ``messages`` for a single chunk/request.

        The first message is the ``system`` message carrying all non-history
        fitted content (in registration order); each history turn follows as
        its own message, preserving the original history order.
        """
        messages: list[dict[str, str]] = []

        system_content = builder.assemble(
            {
                output.section_type: output.content
                for output in context_result.sections
                if output.section_type != "HISTORY"
            }
        )
        if system_content:
            messages.append({"role": "system", "content": system_content})

        messages.extend(self._history_messages(builder))
        return messages

    def build(
        self,
        context_result: ContextBuilderResult,
        builder: PromptBuilder,
        *,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, object]:
        """Return the full OpenAI-compatible body for a single chunk/request.

        Keeps the same top-level keys the batch endpoint already uses
        (``model`` / ``messages`` / ``temperature`` / ``max_tokens``), so a
        batch item is this body's ``messages`` array.
        """
        return {
            "model": model,
            "messages": self.build_messages(context_result, builder),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

    def _history_messages(self, builder: PromptBuilder) -> list[dict[str, str]]:
        history = builder.get_section("HISTORY")
        if history is None:
            return []
        section = cast("HistorySection", history)
        return [
            {"role": item.role.value, "content": item.content}
            for item in section.items
        ]