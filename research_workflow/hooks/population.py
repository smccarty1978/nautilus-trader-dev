"""Population predicate hook type."""
from typing import Protocol, Any

class PopulationPredicate(Protocol):
    def __call__(self, observation: Any) -> bool: ...
