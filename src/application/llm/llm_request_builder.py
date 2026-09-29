"""Serialize fitted context as provider-neutral chat messages."""

from src.application.dtos import ContextBuilderResult
from src.application.interfaces.i_llm_request_builder import ILLMRequestBuilder


class LLMRequestBuilder(ILLMRequestBuilder):
    """Turn fitted section outputs into a chat request without reprocessing them."""

    def build_messages(
        self, context_result: ContextBuilderResult
    ) -> list[dict[str, str]]:
        """Build system, fitted history, and user messages from section outputs."""
        system_parts: list[str] = []
        user_parts: list[str] = []
        history: list[dict[str, str]] = []
        for output in context_result.sections:
            if output.section_type == "HISTORY":
                if output.history_messages is None:
                    raise ValueError("Processed HISTORY output has no chat messages")
                history.extend(
                    {"role": turn.role.value, "content": turn.content}
                    for turn in output.history_messages
                )
            elif output.content:
                if output.section_type in {"USER-INPUT", "SIMILAR-SUGGESTIONS"}:
                    user_parts.append(output.content)
                else:
                    system_parts.append(output.content)

        messages: list[dict[str, str]] = []
        if system_parts:
            messages.append(
                {
                    "role": "system",
                    "content": context_result.section_separator.join(system_parts),
                }
            )
        messages.extend(history)
        if user_parts:
            messages.append(
                {
                    "role": "user",
                    "content": context_result.section_separator.join(user_parts),
                }
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
