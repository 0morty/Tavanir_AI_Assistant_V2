from typing import Any

from fastapi import APIRouter, Depends, status
from src.presentation.routers.v1.suggestion import (
    router as suggestion_router,
)
from src.presentation.schemas.responses import ErrorResponse

from src.presentation.security import get_api_key

COMMON_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_400_BAD_REQUEST: {
        "model": ErrorResponse,
        "description": "Bad Request - Malformed syntax, invalid parameters, or payload violation",
    },
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Missing or invalid API Key in header",
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "Target resource not found",
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponse,
        "description": "Resource already exists or concurrent edit collision",
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ErrorResponse,
        "description": "Validation error or domain business rule violation",
    },
    status.HTTP_500_INTERNAL_SERVER_ERROR: {
        "model": ErrorResponse,
        "description": "Internal server error",
    },
}

master_router_v1 = APIRouter(
    prefix="/api/v1",
    tags=["v1"],
    dependencies=[Depends(get_api_key)],
    responses=COMMON_ERROR_RESPONSES,
)

master_router_v1.include_router(suggestion_router)

__all__ = ["master_router_v1", "COMMON_ERROR_RESPONSES"]
