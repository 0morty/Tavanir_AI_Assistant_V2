from pydantic import Field
from src.presentation.schemas.responses import BaseResponseModel


class IngestSuggestionDataResponse(BaseResponseModel):
    """Payload data model for successful suggestion ingestion."""

    suggestion_id: str = Field(
        ...,
        description="Business identifier of the persisted suggestion",
    )
    chunks_count: int = Field(
        ...,
        description="Number of discrete vector chunks indexed into Qdrant",
    )
    status: str = Field(
        default="CREATED",
        description="Ingestion processing status",
    )


__all__ = ["IngestSuggestionDataResponse"]
