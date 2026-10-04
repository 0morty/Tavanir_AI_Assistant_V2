"""Actual mock host with a test-only read-only in-memory evidence observer."""

from __future__ import annotations

import os
from dataclasses import asdict
from enum import Enum
from pathlib import Path

from .evidence import write_json


def _plain(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def create_app():
    from src.main import create_app as real_create_app

    app = real_create_app(is_mock=True)
    destination = Path(os.environ["E2E_MOCK_EVIDENCE"])

    @app.middleware("http")
    async def observe_store(request, call_next):
        response = await call_next(request)
        store = getattr(app.state, "mock_store", None)
        if store is not None:
            values = await store.list_active()
            write_json(destination, {value.id: _plain(asdict(value)) for value in values})
        return response

    return app
