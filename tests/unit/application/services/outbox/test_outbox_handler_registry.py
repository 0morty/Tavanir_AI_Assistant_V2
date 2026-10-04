from unittest.mock import AsyncMock

import pytest
from src.application.interfaces.i_outbox_event_handler import IOutboxEventHandler
from src.application.services.outbox.outbox_handler_registry import (
    OutboxHandlerRegistry,
)

from src.application.exceptions import CommandNotRegisteredError


def test_registry_resolves_registered_event_types():
    handler_ingest = AsyncMock(spec=IOutboxEventHandler)
    handler_update = AsyncMock(spec=IOutboxEventHandler)
    handler_delete = AsyncMock(spec=IOutboxEventHandler)

    registry = OutboxHandlerRegistry(
        handlers={
            "SUGGESTION_INGESTED": handler_ingest,
            "SUGGESTION_UPDATED": handler_update,
            "SUGGESTION_DELETED": handler_delete,
        }
    )

    assert registry.get_handler("SUGGESTION_INGESTED") is handler_ingest
    assert registry.get_handler("SUGGESTION_UPDATED") is handler_update
    assert registry.get_handler("SUGGESTION_DELETED") is handler_delete


def test_registry_raises_unsupported_on_unknown_type():
    registry = OutboxHandlerRegistry(handlers={})

    with pytest.raises(CommandNotRegisteredError) as exc_info:
        registry.get_handler("NON_EXISTENT_EVENT")

    assert (
        "No outbox event handler registered for event type 'NON_EXISTENT_EVENT'"
        in str(exc_info.value)
    )
