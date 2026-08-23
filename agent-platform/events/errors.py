from __future__ import annotations

from typing import Any


class EventError(Exception):
    """Structured error for event surface operations."""

    def __init__(self, kind: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": "error",
            "kind": self.kind,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        return result
