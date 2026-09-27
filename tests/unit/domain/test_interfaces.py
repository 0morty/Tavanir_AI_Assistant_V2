import pytest

from src.domain.interfaces import (
    IChunkingStrategy,
    IRegulatoryVectorRepository,
    ISuggestionRepository,
    ISuggestionVectorRepository,
    IVectorRepository,
)


def test_interfaces_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        IVectorRepository()  # type: ignore

    with pytest.raises(TypeError):
        ISuggestionVectorRepository()  # type: ignore

    with pytest.raises(TypeError):
        IRegulatoryVectorRepository()  # type: ignore

    with pytest.raises(TypeError):
        ISuggestionRepository()  # type: ignore

    with pytest.raises(TypeError):
        IChunkingStrategy()  # type: ignore
