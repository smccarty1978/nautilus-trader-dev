"""Deprecated compatibility shim.

The generic collector implementation now lives in
``research_workflow.generic_collector``. New studies must import the canonical
workflow path directly.
"""
from research_workflow.generic_collector import *  # noqa: F401,F403

__all__ = ["FlipPredictionCollector", "FlipPredictionCollectorConfig"]
