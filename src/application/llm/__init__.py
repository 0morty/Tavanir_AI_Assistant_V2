"""Application-layer LLM request construction.

Turns a :class:`~src.application.dtos.ContextBuilderResult` plus the
``PromptBuilder`` that produced it into the OpenAI-compatible ``messages``
structure expected by chat-completion APIs (vLLM
``/v1/chat/completions/batch`` items, ``/v1/chat/completions``, ...).

The builder is provider-agnostic: it only constructs the message structure.
HTTP transport and payload merge stay with the LLM client adapter.
"""

from src.application.llm.llm_request_builder import LLMRequestBuilder

__all__ = ["LLMRequestBuilder"]