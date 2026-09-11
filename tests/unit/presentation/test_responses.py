from src.presentation.schemas.responses import (
    BaseResponseModel,
    DebugInfo,
    ErrorItem,
    ErrorResponse,
    ErrorSource,
    SuccessResponse,
)


class SampleDataDTO(BaseResponseModel):
    analysis_text: str
    similar_executed_ids: list[str]
    applied_statute_ids: list[str]


def test_success_response_serializes_to_camel_case():
    """Verifies that SuccessResponse and nested DTOs serialize strictly to camelCase."""
    dto = SampleDataDTO(
        analysis_text="تحلیل اولیه",
        similar_executed_ids=["sug-1", "sug-2"],
        applied_statute_ids=["stat-4"],
    )
    response = SuccessResponse.create(data=dto)
    payload = response.model_dump(by_alias=True, exclude_none=True)

    assert payload["status"] == 200
    assert "data" in payload
    data = payload["data"]
    assert "analysisText" in data
    assert "similarExecutedIds" in data
    assert "appliedStatuteIds" in data
    assert "analysis_text" not in data
    assert "similar_executed_ids" not in data


def test_error_response_single_with_pointer():
    """Verifies single error with pointer formatting."""
    response = ErrorResponse.create_single(
        status_code=422,
        code="MISSING_REQUIRED_FIELD",
        pointer="/data/currentProblem",
    )
    payload = response.model_dump(by_alias=True, exclude_none=True)

    assert "errors" in payload
    assert len(payload["errors"]) == 1
    err = payload["errors"][0]
    assert err["status"] == 422
    assert err["code"] == "MISSING_REQUIRED_FIELD"
    assert err["source"]["pointer"] == "/data/currentProblem"


def test_error_response_single_omits_source_when_none():
    """
    Verifies that when pointer is None (single internal server error),
    the 'source' key is completely omitted from the JSON payload.
    """
    response = ErrorResponse.create_single(
        status_code=503,
        code="EMBEDDER_CONNECTION_FAILED",
        pointer=None,
    )
    payload = response.model_dump(by_alias=True, exclude_none=True)

    err = payload["errors"][0]
    assert err["status"] == 503
    assert err["code"] == "EMBEDDER_CONNECTION_FAILED"
    # source MUST NOT exist in dictionary
    assert "source" not in err


def test_error_response_multi_indexed():
    """Verifies multi-error formatting for batch operations."""
    errors = [
        ErrorItem(
            status=422,
            code="INVALID_SUGGESTION_STATUS",
            source=ErrorSource(pointer="/data/0/status"),
        ),
        ErrorItem(
            status=500,
            code="EMBEDDING_FAILED",
            source=ErrorSource(pointer="/data/1"),
        ),
    ]
    response = ErrorResponse.create_multi(errors=errors)
    payload = response.model_dump(by_alias=True, exclude_none=True)

    assert len(payload["errors"]) == 2
    assert payload["errors"][0]["source"]["pointer"] == "/data/0/status"
    assert payload["errors"][1]["source"]["pointer"] == "/data/1"


def test_debug_info_camel_case_serialization():
    """Verifies that DebugInfo fields (stack_trace) serialize to camelCase (stackTrace)."""
    debug = DebugInfo(
        exception="ValueError",
        cause="Connection timeout",
        stack_trace="Traceback...",
    )
    payload = debug.model_dump(by_alias=True, exclude_none=True)

    assert "exception" in payload
    assert "cause" in payload
    assert "stackTrace" in payload
    assert "stack_trace" not in payload
