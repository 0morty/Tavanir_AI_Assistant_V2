import pytest

from src.infrastructure.services.llm.llm_client_registry import LLMClientRegistry


class FakeClient:
    """Stand-in AsyncOpenAI client handed back by the fake factory."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _fake_factory() -> tuple[callable, list[tuple[str, float]]]:
    calls: list[tuple[str, float]] = []

    def factory(provider: str, timeout: float):
        calls.append((provider, timeout))
        return FakeClient()

    return factory, calls


@pytest.mark.asyncio
async def test_injected_client_factory_is_used():
    factory, calls = _fake_factory()
    registry = LLMClientRegistry(client_factory=factory)

    client = await registry.get_client("tei", 30.0)

    assert isinstance(client, FakeClient)
    assert calls == [("tei", 30.0)]
    await registry.close_all()


@pytest.mark.asyncio
async def test_injected_factory_is_cached_per_provider_and_timeout():
    factory, calls = _fake_factory()
    registry = LLMClientRegistry(client_factory=factory)

    first = await registry.get_client("tei", 30.0)
    second = await registry.get_client("tei", 30.0)

    assert first is second
    assert len(calls) == 1
    await registry.close_all()