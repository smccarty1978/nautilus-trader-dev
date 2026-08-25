"""Checkpoint hook type."""
from typing import Protocol, Any

class CheckpointHook(Protocol):
    def __call__(self, timestamp_ns: int, state: Any) -> Any: ...
