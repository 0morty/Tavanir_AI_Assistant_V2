from __future__ import annotations

from collections.abc import Mapping

from src.application.exceptions import CommandNotRegisteredError
from src.application.interfaces.i_outbox_event_handler import IOutboxEventHandler


class OutboxHandlerRegistry:
    """
    Registry for resolving outbox event projection strategies (OCP/Factory).
    Decouples event dispatching from concrete projection implementations.
    """

    def __init__(self, handlers: Mapping[str, IOutboxEventHandler]) -> None:
        self._handlers = dict(handlers)

    def get_handler(self, event_type: str) -> IOutboxEventHandler:
        """
        Resolves the dedicated handler for the given event type.

        Args:
            event_type: String identifier of the event (e.g. 'SUGGESTION_INGESTED').

        Returns:
            The registered IOutboxEventHandler strategy.

        Raises:
            CommandNotRegisteredError: If no handler is registered for event_type.
        """
        handler = self._handlers.get(event_type)
        if handler is None:
            raise CommandNotRegisteredError(
                f"No outbox event handler registered for event type '{event_type}'"
            )
        return handler


__all__ = ["OutboxHandlerRegistry"]
