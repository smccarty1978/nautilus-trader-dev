"""Explicit structural test-coverage declarations for canonical features."""
from __future__ import annotations

from typing import Callable, TypeVar

F = TypeVar("F", bound=Callable)


def covers_feature(name: str):
    def decorate(func: F) -> F:
        setattr(func, "__covers_features__", (name,))
        return func
    return decorate


def covers_feature_family(name: str):
    def decorate(func: F) -> F:
        setattr(func, "__covers_feature_families__", (name,))
        return func
    return decorate
