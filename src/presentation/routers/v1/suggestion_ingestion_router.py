from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status
from src.application.use_cases.ingest_suggestion_use_case import IngestSuggestionUseCase
from src.containers import Container
from src.presentation.schemas.responses import SuccessResponse
from src.presentation.schemas.v1.ingest_suggestion_request import (
    IngestSuggestionRequest,
)
from src.presentation.schemas.v1.ingest_suggestion_response import (
    IngestSuggestionDataResponse,
)

router = APIRouter(tags=["Suggestions"])


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


__all__ = ["router"]
