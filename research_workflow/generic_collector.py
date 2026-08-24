"""Generic collector facade.

New studies bind this collector through compiled configuration. Historical
study collectors are deliberately not imported here.
"""
from strategies.flip_prediction_collector import FlipPredictionCollector, FlipPredictionCollectorConfig

GenericStudyCollector = FlipPredictionCollector
GenericStudyCollectorConfig = FlipPredictionCollectorConfig

__all__ = ["GenericStudyCollector", "GenericStudyCollectorConfig"]
