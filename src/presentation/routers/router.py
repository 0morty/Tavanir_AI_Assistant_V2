from fastapi import APIRouter, Depends, status
from src.presentation.routers.v1.suggestion_ingestion_router import (
    router as suggestion_ingestion_router,
)

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

master_router_v1.include_router(suggestion_ingestion_router)

__all__ = ["master_router_v1"]
