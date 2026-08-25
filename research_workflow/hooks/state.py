"""State-transition hook type."""
from typing import Protocol, Any

class StateHook(Protocol):
    def __call__(self, event: Any, state: Any) -> Any: ...
