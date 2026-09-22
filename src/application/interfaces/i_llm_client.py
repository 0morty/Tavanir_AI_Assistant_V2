from abc import ABC, abstractmethod
from collections.abc import Sequence


class ILLMClient(ABC):
    """Application-layer port for LLM invocation.

    This is the Generation API's shared contract for calling an LLM: send a
    fully assembled prompt and receive the model's raw completion text.
    Concrete adapters (e.g. an OpenAI-compatible HTTP client) are injected
    from the infrastructure layer; this port never references a concrete
    provider. The prompt passed in is already built by the shared
    ``PromptBuilder`` / ``ContextBuilder`` pipeline.
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