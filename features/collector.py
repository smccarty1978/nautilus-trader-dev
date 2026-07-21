"""Feature Collector for ML Training.

Collects features at touch time using composition with the centralized FeatureEngine.
"""

from typing import Optional, Dict, Any
from features.engine import FeatureEngine

class FeatureCollector:
    """
    Collects features at touch time using a composed FeatureEngine.

    Usage:
        collector = FeatureCollector()

        # On each 1s bar:
        collector.update_1s(bar)

        # On each 1m bar (AFTER regime.update()):
        collector.update_1m(bar, regime)

        # At touch time:
        features = collector.get_features(touch_bar, regime, direction)
    """

    def __init__(self, buffer_size_1s: int = 60, buffer_size_1m: int = 30):
        self._engine = FeatureEngine(buffer_size_1s, buffer_size_1m)

    def update_1s(self, bar) -> None:
        """Update 1s buffers. Call on every 1s bar."""
        self._engine.update_1s(bar)

    def update_1m(self, bar, regime) -> None:
        """Update 1m state. Call on every 1m bar AFTER regime.update()."""
        self._engine.update_1m(bar, regime)

    def on_new_breach(self, regime) -> None:
        """Call when a new breach is detected. Resets breach tracking."""
        self._engine.on_new_breach(regime)

    def get_features(self, touch_bar, regime, direction: int) -> Optional[Dict[str, float]]:
        """
        Get all features at touch time.

        Args:
            touch_bar: The 1s bar that triggered the touch
            regime: RegimeIndicatorsV2 instance
            direction: +1 for long, -1 for short

        Returns:
            dict with all features, or None if insufficient data
        """
        snap_context = {
            "touch_bar": touch_bar,
            "regime": regime,
            "direction": direction
        }
        # Emits canonical features by requesting the full verified set
        res = self._engine.snapshot(feature_set="all", snap_context=snap_context)
        return res if res else None
