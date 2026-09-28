"""Serialize a processed ContextBuilderResult as OpenAI-compatible messages."""

from src.application.dtos import ContextBuilderResult


class LLMRequestBuilder:
    """Turn fitted section outputs into a chat request without reprocessing them."""

    def build_messages(
        self, context_result: ContextBuilderResult
    ) -> list[dict[str, str]]:
        """Assemble non-history output, then emit the fitted History turns."""
        system_content = context_result.section_separator.join(
            output.content
            for output in context_result.sections
            if output.section_type != "HISTORY" and output.content
        )
        messages: list[dict[str, str]] = []
        if system_content:
            messages.append({"role": "system", "content": system_content})

        for output in context_result.sections:
            if output.section_type != "HISTORY":
                continue
            if output.history_messages is None:
                raise ValueError("Processed HISTORY output has no chat messages")
            messages.extend(
                {"role": turn.role.value, "content": turn.content}
                for turn in output.history_messages
            )
        return messages

    def build(
        self,
        context_result: ContextBuilderResult,
        *,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, object]:
        """Return the request body using only the processed context result."""
        return {
            "model": model,
            "messages": self.build_messages(context_result),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
