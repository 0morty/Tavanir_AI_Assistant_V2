from src.containers import Container
from src.infrastructure.mocks.in_memory_suggestion_store import (
    InMemorySuggestionStore,
)
from src.infrastructure.mocks.mock_use_cases import (
    MockAnalyzeSuggestionUseCase,
    MockBulkDeleteSuggestionsUseCase,
    MockDeleteSuggestionUseCase,
    MockIngestSuggestionUseCase,
    MockUpdateSuggestionUseCase,
)


def apply_mock_overrides(
    container: Container, store: InMemorySuggestionStore
) -> None:
    """Overrides application use case providers on Container with zero-dependency mock doubles.

    Bypasses external resource initialization (PostgreSQL, Qdrant, TEI, HuggingFace AutoTokenizer).
    """
    mock_analyze = MockAnalyzeSuggestionUseCase(store=store)
    mock_ingest = MockIngestSuggestionUseCase(store=store)
    mock_update = MockUpdateSuggestionUseCase(store=store)
    mock_delete = MockDeleteSuggestionUseCase(store=store)
    mock_bulk_delete = MockBulkDeleteSuggestionsUseCase(
        delete_use_case=mock_delete
    )

    container.analyze_suggestion_use_case.override(mock_analyze)
    container.ingest_suggestion_use_case.override(mock_ingest)
    container.update_suggestion_use_case.override(mock_update)
    container.delete_suggestion_use_case.override(mock_delete)
    container.bulk_delete_suggestions_use_case.override(mock_bulk_delete)
