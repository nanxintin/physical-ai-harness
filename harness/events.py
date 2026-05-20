"""Simple async event bus for device state changes."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable
from typing import Any


class EventBus:
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._history: list[dict[str, Any]] = []

    def subscribe(self, event_type: str, handler: Callable) -> None:
        self._handlers[event_type].append(handler)

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        event = {"type": event_type, **data}
        self._history.append(event)
        for handler in self._handlers.get(event_type, []):
            if asyncio.iscoroutinefunction(handler):
                await handler(event)
            else:
                handler(event)

    def get_history(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._history[-limit:]
