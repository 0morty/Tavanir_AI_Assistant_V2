from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Path, Response, status
from fastapi.responses import JSONResponse
from src.containers import Container
from src.presentation.schemas.responses import (
    ErrorItem,
    ErrorResponse,
    ErrorSource,
    PartialSuccessResponse,
    SuccessResponse,
)

from src.application.interfaces import IStructureIdeaUseCase
from src.application.use_cases import (
    AnalyzeSuggestionUseCase,
    BulkDeleteSuggestionsUseCase,
    DeleteSuggestionUseCase,
    IngestSuggestionUseCase,
    UpdateSuggestionUseCase,
)
from src.presentation.schemas.v1 import (
    AnalyzeSuggestionDataResponse,
    AnalyzeSuggestionRequest,
    BulkDeleteRequest,
    DeleteSuggestionDataResponse,
    IngestSuggestionDataResponse,
    IngestSuggestionRequest,
    PatchSuggestionRequest,
    StructureIdeaRequest,
    StructuredIdeaDataResponse,
    UpdateSuggestionDataResponse,
    UpdateSuggestionRequest,
)

router = APIRouter(tags=["Suggestions"])


@router.post(
    "/suggestions/expand-suggestion",
    status_code=status.HTTP_200_OK,
    summary="Structure an idea into five generated fields",
    description=(
        "Accepts one idea description of at most 512 model tokens. Processes prompt "
        "sections through the context budget pipeline, invokes the configured LLM, "
        "and returns the five parsed fields in the standard success envelope."
    ),
    responses={
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
    },
)
@inject
async def structure_idea(
    request: StructureIdeaRequest,
    use_case: Annotated[
        IStructureIdeaUseCase,
        Depends(Provide[Container.structure_idea_use_case]),
    ],
) -> SuccessResponse[StructuredIdeaDataResponse]:
    result = await use_case.execute(request.to_dto())
    response_data = StructuredIdeaDataResponse(
        title=result.title,
        current_problem=result.current_problem,
        solution=result.solution,
        advantage=result.advantage,
        disadvantage=result.disadvantage,
    )
    return SuccessResponse.create(data=response_data, status=status.HTTP_200_OK)


@router.post(
    "/suggestions/analyze",
    status_code=status.HTTP_200_OK,
    summary="Analyze an incoming employee suggestion against historical suggestions",
    description=(
        "Synchronously executes Tri-Track hybrid Qdrant retrieval, candidate deduplication, "
        "cross-encoder reranking, Max-Passage pooling, and PostgreSQL hydration to return partitioned similar suggestion IDs."
    ),
)
@inject
async def analyze_suggestion(
    request: AnalyzeSuggestionRequest,
    use_case: Annotated[
        AnalyzeSuggestionUseCase,
        Depends(Provide[Container.analyze_suggestion_use_case]),
    ],
) -> SuccessResponse[AnalyzeSuggestionDataResponse]:
    dto = request.to_dto()
    result = await use_case.execute(dto)
    response_data = AnalyzeSuggestionDataResponse(
        analysis=result.analysis,
        similar_executed_ids=result.similar_executed_ids,
        similar_approved_ids=result.similar_approved_ids,
        similar_pending_ids=result.similar_pending_ids,
        similar_rejected_ids=result.similar_rejected_ids,
        similar_not_accepted_ids=result.similar_not_accepted_ids,
        applied_statute_ids=result.applied_statute_ids,
        uncertainty=result.uncertainty,
        cited_suggestion_ids=result.cited_suggestion_ids,
        is_fallback_mode=result.is_fallback_mode,
        grounding_ratio=result.grounding_ratio,
    )
    return SuccessResponse.create(data=response_data, status=status.HTTP_200_OK)


@router.post(
    "/suggestions/ingest",
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a historical or newly submitted employee suggestion",
    description="Synchronously normalizes, chunks, embeds, and stores the suggestion in PostgreSQL and Qdrant vector store.",
)
@inject
async def ingest_suggestion(
    request: IngestSuggestionRequest,
    use_case: Annotated[
        IngestSuggestionUseCase,
        Depends(Provide[Container.ingest_suggestion_use_case]),
    ],
) -> SuccessResponse[IngestSuggestionDataResponse]:
    dto = request.to_dto()
    result = await use_case.execute(dto)
    response_data = IngestSuggestionDataResponse(
        suggestion_id=result.suggestion_id,
        chunks_count=result.chunks_count,
        status=result.status,
    )
    return SuccessResponse.create(data=response_data, status=status.HTTP_201_CREATED)


@router.put(
    "/suggestions/{suggestionId}",
    status_code=status.HTTP_200_OK,
    summary="Full replacement update for an employee suggestion",
    description="Synchronously replaces all core fields of an existing suggestion or restores a soft-deleted suggestion with two-phase concurrency control.",
)
@inject
async def update_suggestion(
    suggestion_id: Annotated[
        str,
        Path(
            alias="suggestionId",
            min_length=1,
            max_length=128,
            description="Unique suggestion identifier",
        ),
    ],
    request: UpdateSuggestionRequest,
    use_case: Annotated[
        UpdateSuggestionUseCase,
        Depends(Provide[Container.update_suggestion_use_case]),
    ],
) -> SuccessResponse[UpdateSuggestionDataResponse]:
    dto = request.to_dto(path_suggestion_id=suggestion_id)
    result = await use_case.execute_put(dto)
    response_data = UpdateSuggestionDataResponse(
        suggestion_id=result.suggestion_id,
        chunks_count=result.chunks_count,
        version=result.version,
        status=result.status,
    )
    return SuccessResponse.create(data=response_data, status=status.HTTP_200_OK)


@router.patch(
    "/suggestions/{suggestionId}",
    status_code=status.HTTP_200_OK,
    summary="Partial update for an employee suggestion",
    description="Synchronously overlays non-null fields onto an active suggestion with two-phase concurrency control. Soft-deleted suggestions cannot be patched.",
)
@inject
async def patch_suggestion(
    suggestion_id: Annotated[
        str,
        Path(
            alias="suggestionId",
            min_length=1,
            max_length=128,
            description="Unique suggestion identifier",
        ),
    ],
    request: PatchSuggestionRequest,
    use_case: Annotated[
        UpdateSuggestionUseCase,
        Depends(Provide[Container.update_suggestion_use_case]),
    ],
) -> SuccessResponse[UpdateSuggestionDataResponse]:
    dto = request.to_dto(path_suggestion_id=suggestion_id)
    result = await use_case.execute_patch(dto)
    response_data = UpdateSuggestionDataResponse(
        suggestion_id=result.suggestion_id,
        chunks_count=result.chunks_count,
        version=result.version,
        status=result.status,
    )
    return SuccessResponse.create(data=response_data, status=status.HTTP_200_OK)


@router.delete(
    "/suggestions/{suggestionId}",
    status_code=status.HTTP_200_OK,
    summary="Soft delete a suggestion and purge its vector chunks",
    description="Guards against race conditions via advisory locking, sets is_deleted=True in PostgreSQL, and physically purges vector chunks from Qdrant.",
)
@inject
async def delete_suggestion(
    suggestion_id: Annotated[
        str,
        Path(
            alias="suggestionId",
            min_length=1,
            max_length=128,
            description="Unique suggestion identifier",
        ),
    ],
    use_case: Annotated[
        DeleteSuggestionUseCase,
        Depends(Provide[Container.delete_suggestion_use_case]),
    ],
) -> SuccessResponse[DeleteSuggestionDataResponse]:
    result = await use_case.execute(suggestion_id=suggestion_id)
    response_data = DeleteSuggestionDataResponse(
        suggestion_id=result.suggestion_id,
        status=result.status,
    )
    return SuccessResponse.create(data=response_data, status=status.HTTP_200_OK)


@router.post(
    "/suggestions/bulk-delete",
    summary="Bulk soft-delete suggestions",
    description=(
        "Sequentially soft-deletes up to 100 suggestions with per-item error isolation. "
        "Returns 200 OK if all succeed, 207 Multi-Status on partial success, "
        "or 400 Bad Request if all fail."
    ),
    responses={
        status.HTTP_200_OK: {
            "model": SuccessResponse[list[DeleteSuggestionDataResponse]],
            "description": "All requested suggestions were successfully soft-deleted.",
        },
        status.HTTP_207_MULTI_STATUS: {
            "model": PartialSuccessResponse[DeleteSuggestionDataResponse],
            "description": "Partial success: some suggestions were deleted while others failed.",
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "All requested items failed to delete or input list violated constraints.",
        },
    },
)
@inject
async def bulk_delete_suggestions(
    request: BulkDeleteRequest,
    use_case: Annotated[
        BulkDeleteSuggestionsUseCase,
        Depends(Provide[Container.bulk_delete_suggestions_use_case]),
    ],
) -> Response:
    dto = request.to_dto()
    result = await use_case.execute(dto)

    # Success items list
    success_items = [
        DeleteSuggestionDataResponse(suggestion_id=sid, status="DELETED").model_dump(
            by_alias=True
        )
        for sid in result.deleted_ids
    ]

    # Error items list
    error_items = [
        ErrorItem(
            status=(
                status.HTTP_404_NOT_FOUND
                if err.code == "SUGGESTION_NOT_FOUND"
                else (
                    status.HTTP_409_CONFLICT
                    if err.code == "SUGGESTION_IN_PROCESSING"
                    else status.HTTP_400_BAD_REQUEST
                )
            ),
            code=err.code,
            source=ErrorSource(pointer=err.source_pointer),
        )
        for err in result.errors
    ]

    if result.total_failed == 0:
        content = SuccessResponse.create(
            data=success_items, status=status.HTTP_200_OK
        ).model_dump(by_alias=True)
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    if result.total_deleted == 0:
        content = ErrorResponse.create_multi(errors=error_items).model_dump(
            by_alias=True
        )
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=content)

    # Partial success: HTTP 207 Multi-Status
    content = PartialSuccessResponse.create(
        data=success_items,
        errors=error_items,
        status=status.HTTP_207_MULTI_STATUS,
    ).model_dump(by_alias=True)
    return JSONResponse(status_code=status.HTTP_207_MULTI_STATUS, content=content)


__all__ = ["router"]
