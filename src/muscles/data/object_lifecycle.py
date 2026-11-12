"""Transaction-bound notifications for package-owned objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from .policies import DataOperationContext


@dataclass(frozen=True)
class ObjectLifecycleEvent:
    action: Literal["created", "deleted"]
    object_type: str
    object_uid: str
    context: DataOperationContext


class ObjectLifecycle:
    """Dispatch handlers synchronously inside the caller's transaction.

    Handlers receive the transaction used for the object write. Exceptions
    propagate to the caller so that the transaction can be rolled back.
    """

    def __init__(self) -> None:
        self._handlers: list[Callable] = []

    def register(self, handler: Callable) -> None:
        if not callable(handler):
            raise TypeError("Lifecycle handler must be callable")
        if handler not in self._handlers:
            self._handlers.append(handler)

    def emit(self, transaction, event: ObjectLifecycleEvent) -> None:
        if event.action not in ("created", "deleted"):
            raise ValueError("Unsupported object lifecycle action")
        if not event.object_type or not event.object_uid:
            raise ValueError("Object type and identifier are required")
        for handler in tuple(self._handlers):
            handler(transaction, event)
