"""HTTP fields parsed from the idea-structuring model response."""

from pydantic import Field

from src.presentation.schemas.responses import BaseResponseModel


class StructuredIdeaDataResponse(BaseResponseModel):
    title: str = Field(..., description="Generated title for the idea")
    current_problem: str = Field(
        ..., description="Current problem addressed by the idea"
    )
    solution: str = Field(
        ..., description="Proposed solutions from the {solutions} block"
    )
    advantage: str = Field(..., description="Expected advantages and benefits")
    disadvantage: str = Field(
        ..., description="Disadvantages, limitations, and uncertainties"
    )


__all__ = ["StructuredIdeaDataResponse"]
