from fastapi import APIRouter, Depends, Request, status
from pydantic import Field

from src.presentation.schemas.responses import BaseResponseModel, SuccessResponse
from src.presentation.security import get_api_key

router = APIRouter(
    prefix="/mock",
    tags=["Mock Administration"],
    dependencies=[Depends(get_api_key)],
)


class MockResetResponseData(BaseResponseModel):
    message: str = Field(..., description="Confirmation message")
    seeded_items: int = Field(..., description="Total items seeded in memory")


@router.post(
    "/reset",
    status_code=status.HTTP_200_OK,
    summary="Reset in-memory mock repository to initial seed state",
    description="Clears all mutated suggestion data and repopulates the store with baseline realistic Persian suggestions.",
)
async def reset_mock_state(
    request: Request,
) -> SuccessResponse[MockResetResponseData]:
    store = getattr(request.app.state, "mock_store", None)
    seeded_count = 6
    if store is not None:
        seeded_count = await store.reset()

    return SuccessResponse.create(
        data=MockResetResponseData(
            message="Mock store reset to initial seed state successfully",
            seeded_items=seeded_count,
        ),
        status=status.HTTP_200_OK,
    )


__all__ = ["router"]
