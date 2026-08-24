"""Target observation hook type."""
from typing import Protocol, Any

class TargetPredicate(Protocol):
    def __call__(self, observation: Any) -> Any: ...
