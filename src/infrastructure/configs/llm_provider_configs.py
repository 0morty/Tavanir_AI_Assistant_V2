from enum import Enum

from openai import AsyncOpenAI

from src.application.exceptions import LLMConfigurationError
from src.infrastructure.configs.settings import llm_settings


class LLMProvider(str, Enum):
    """Single source of truth for supported LLM providers."""

    TEI = "tei"
    VLLM = "vllm"


class APIKeyProvider:
    """Centralized API key management for different providers."""

    @staticmethod
    def get_api_key_for_provider(provider: LLMProvider) -> str:
        provider_key_mapping = {
            LLMProvider.TEI: llm_settings.TEI_API_KEY,
            LLMProvider.VLLM: llm_settings.VLLM_API_KEY,
        }

        api_key = provider_key_mapping.get(provider)

        if not api_key or not api_key.strip():
            raise LLMConfigurationError(
                f"API key for '{provider.value}' is empty or unset in environment variables."
            )

        return api_key


class AsyncOpenAIClientFactory:
    """Factory class for creating Async OpenAI-compatible clients."""

    @classmethod
    def _get_base_url(cls, provider: LLMProvider) -> str:
        """Fetch the correct base URL from settings dynamically."""
        url_mapping = {
            LLMProvider.TEI: llm_settings.TEI_BASE_URL,
            LLMProvider.VLLM: llm_settings.VLLM_BASE_URL,
        }
        base_url = url_mapping.get(provider)
        if not base_url:
            raise LLMConfigurationError(
                f"Base URL for provider '{provider.value}' is not configured."
            )
        return base_url

    @classmethod
    def create_client(cls, provider_name: str, timeout: float) -> AsyncOpenAI:
        provider_name = provider_name.lower().strip()

        # 1. Convert string to Enum. This provides built-in validation.
        try:
            provider = LLMProvider(provider_name)
        except ValueError as err:
            supported = [p.value for p in LLMProvider]
            raise LLMConfigurationError(
                f"Unsupported provider: '{provider_name}'. Supported are: {supported}"
            ) from err

        # 2. Pass strongly-typed Enum to the helpers
        api_key = APIKeyProvider.get_api_key_for_provider(provider)
        base_url = cls._get_base_url(provider)

        # Instantiate the client (which maintains its own connection pool)
        return AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=llm_settings.MAX_RETRIES,
        )
