"""Canonical public entry points for declarative research workflows.

This package is intentionally a small facade over the established runtime.  It
provides one stable import surface without creating parallel implementations.
"""

__all__ = ["study_factory", "compiler", "generic_collector", "phase0", "readiness", "preflight"]
