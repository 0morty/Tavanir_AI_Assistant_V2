from pydantic import Field
from src.presentation.schemas.responses import BaseResponseModel


class UpdateSuggestionDataResponse(BaseResponseModel):
    """Payload data model for successful suggestion update or patch."""

    suggestion_id: str = Field(
        ...,
        description="Business identifier of the updated suggestion",
    )
    chunks_count: int = Field(
        ...,
        description="Number of discrete vector chunks indexed into Qdrant",
    )
    version: int = Field(
        ...,
        description="Updated optimistic concurrency version number",
    )
    status: str = Field(
        default="UPDATED",
        description="Mutation status",
    )


class DeleteSuggestionDataResponse(BaseResponseModel):
    """Payload data model for successful single suggestion soft deletion."""

    suggestion_id: str = Field(
        ...,
        description="Business identifier of the soft-deleted suggestion",
    )
    status: str = Field(
        default="DELETED",
        description="Deletion status",
    )


class BulkDeleteDataResponse(BaseResponseModel):
    """Payload data model for bulk deletion results."""

    deleted_ids: list[str] = Field(
        ...,
        description="List of suggestion IDs successfully soft-deleted",
    )
    total_requested: int = Field(
        ...,
        description="Total number of items requested for deletion",
    )
    total_deleted: int = Field(
        ...,
        description="Total number of items successfully soft-deleted",
    )
    total_failed: int = Field(
        ...,
        description="Total number of items that failed deletion",
    )


__all__ = [
    "UpdateSuggestionDataResponse",
    "DeleteSuggestionDataResponse",
    "BulkDeleteDataResponse",
]
