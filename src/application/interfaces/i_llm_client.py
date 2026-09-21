from abc import ABC, abstractmethod


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