from fastapi import APIRouter, Depends, status

from src.presentation.security import get_api_key

master_router_v1 = APIRouter(
    prefix="/api/v1",
    tags=["v1"],
    dependencies=[Depends(get_api_key)],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid API Key"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error or domain rule violation"
        },
    },
)
