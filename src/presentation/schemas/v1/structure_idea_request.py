"""HTTP input for structuring a single idea description."""

from typing import Any

from pydantic import Field, field_validator

from src.application.dtos import StructureIdeaDTO
from src.presentation.schemas.requests import BaseRequestModel


class StructureIdeaRequest(BaseRequestModel):
    description: str = Field(
        ...,
        strict=True,
        min_length=1,
        description="Nonblank idea description, limited to 512 model tokens",
    )

    @field_validator("description", mode="before")
    @classmethod
    def trim_description(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    def to_dto(self) -> StructureIdeaDTO:
        return StructureIdeaDTO(description=self.description)


__all__ = ["StructureIdeaRequest"]
