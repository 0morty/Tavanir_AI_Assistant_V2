from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class BaseRequestModel(BaseModel):
    """Base model enforcing camelCase alias generation, name population, and forbidden extra fields."""

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        alias_generator=to_camel,
    )


__all__ = ["BaseRequestModel"]
