from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence


class ILLMClient(ABC):
    """Application-layer port for LLM invocation.

    Synchronous prompt operations serve reference and summarization helpers.
    ``complete_chat`` serves final Generation with role-preserving messages.
    Infrastructure adapters provide either capability behind this port.
    """

    @abstractmethod
    def complete(self, prompt: str) -> str:
        """Invoke the LLM with ``prompt`` and return the raw completion text."""

    def complete_many(self, prompts: Sequence[str]) -> list[str]:
        """Return the model's raw completion for each prompt in ``prompts``.

        The result list mirrors ``prompts`` order exactly, one completion per
        prompt. The default implementation degrades to one call per prompt via
        :meth:`complete`; adapters backed by a provider that supports batch
        inference (e.g. vLLM's ``/chat/completions/batch`` endpoint) override
        this so that multiple prompts are sent in a single HTTP request with
        no loss of per-prompt isolation.
        """
        return [self.complete(prompt) for prompt in prompts]

    async def complete_chat(self, messages: Sequence[Mapping[str, str]]) -> str:
        """Return raw text for a role-preserving chat conversation.

        Existing synchronous helper clients can implement only ``complete``;
        final-generation clients override this async operation.
        """
        raise NotImplementedError("This LLM client does not support async chat")
