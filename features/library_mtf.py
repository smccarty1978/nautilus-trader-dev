"""Multi-Timeframe Feature Library for ML Training.

Computes features on 30s, 1m, 5m, and 15m bars for richer context.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field

from nautilus_trader.model.data import Bar, BarType

from features.library import FeatureLibrary, FeatureLibraryConfig


# Top 25 features from SHAP analysis (computed on each timeframe)
TOP_25_BASE_FEATURES = [
    'aroon_osc',
    'pressure_cumulative',
    'atr_200',
    'atr_50',
    'stoch_k',
    'bb_width_atr',
    'atr_14',
    'linreg_r2',
    'swing_length_atr',
    'obv_slope',
    'dc_width_atr',
    'di_plus',
    'vol_ratio',
    'kc_width_atr',
    'hma_dist_atr',
    'di_diff',
    'sma_50_dist_atr',
    'volume_ratio',
    'sma_10_dist_atr',
    'di_minus',
    'hour_ct',
]


@dataclass
class MultiTimeframeFeatureConfig:
    """Configuration for multi-timeframe feature library."""

    # Bar type strings
    bar_type_30s: str = ""
    bar_type_1m: str = ""
    bar_type_5m: str = ""
    bar_type_15m: str = ""

    # Which timeframes to enable
    enable_30s: bool = True
    enable_1m: bool = True
    enable_5m: bool = True
    enable_15m: bool = True

    # Base feature config (shared across timeframes)
    base_config: FeatureLibraryConfig = field(default_factory=FeatureLibraryConfig)


class MultiTimeframeFeatureLibrary:
    """
    Multi-timeframe feature library.

    Creates separate FeatureLibrary instances for each timeframe,
    updates them on appropriate bars, and returns combined features
    with timeframe suffixes.
    """

    def __init__(self, config: MultiTimeframeFeatureConfig):
        self.config = config

        # Parse bar types
        self._bar_type_30s = BarType.from_str(config.bar_type_30s) if config.bar_type_30s else None
        self._bar_type_1m = BarType.from_str(config.bar_type_1m) if config.bar_type_1m else None
        self._bar_type_5m = BarType.from_str(config.bar_type_5m) if config.bar_type_5m else None
        self._bar_type_15m = BarType.from_str(config.bar_type_15m) if config.bar_type_15m else None

        # Create feature libraries for each timeframe
        self._libs = {}

        if config.enable_30s and config.bar_type_30s:
            self._libs['30s'] = FeatureLibrary(config.base_config)

        if config.enable_1m and config.bar_type_1m:
            self._libs['1m'] = FeatureLibrary(config.base_config)

        if config.enable_5m and config.bar_type_5m:
            self._libs['5m'] = FeatureLibrary(config.base_config)

        if config.enable_15m and config.bar_type_15m:
            self._libs['15m'] = FeatureLibrary(config.base_config)

        # Track which timeframes are warmed up
        self._warmup_status = {tf: False for tf in self._libs.keys()}

    def update(self, bar: Bar) -> None:
        """Update appropriate library based on bar type."""
        bar_type = bar.bar_type

        if bar_type == self._bar_type_30s and '30s' in self._libs:
            self._libs['30s'].update(bar)
            self._warmup_status['30s'] = self._libs['30s'].is_fully_warmed_up

        elif bar_type == self._bar_type_1m and '1m' in self._libs:
            self._libs['1m'].update(bar)
            self._warmup_status['1m'] = self._libs['1m'].is_fully_warmed_up

        elif bar_type == self._bar_type_5m and '5m' in self._libs:
            self._libs['5m'].update(bar)
            self._warmup_status['5m'] = self._libs['5m'].is_fully_warmed_up

        elif bar_type == self._bar_type_15m and '15m' in self._libs:
            self._libs['15m'].update(bar)
            self._warmup_status['15m'] = self._libs['15m'].is_fully_warmed_up

    def get_features(self, bar: Optional[Bar] = None) -> Dict[str, float]:
        """
        Get combined features from all timeframes.

        Features are suffixed with timeframe: feature_name_1m, feature_name_5m, etc.
        """
        combined = {}

        for tf, lib in self._libs.items():
            if not lib.is_fully_warmed_up:
                continue

            tf_features = lib.get_features(bar)

            for fname, fval in tf_features.items():
                # Add timeframe suffix
                combined[f"{fname}_{tf}"] = fval

        return combined

    def get_top25_features(self, bar: Optional[Bar] = None) -> Dict[str, float]:
        """
        Get only the top 25 features from each timeframe.

        This reduces feature count while keeping the most predictive ones.
        """
        combined = {}

        for tf, lib in self._libs.items():
            if not lib.is_fully_warmed_up:
                continue

            tf_features = lib.get_features(bar)

            for fname in TOP_25_BASE_FEATURES:
                if fname in tf_features:
                    combined[f"{fname}_{tf}"] = tf_features[fname]

        return combined

    @property
    def is_fully_warmed_up(self) -> bool:
        """Check if all enabled timeframes are warmed up."""
        if not self._libs:
            return False
        return all(self._warmup_status.values())

    @property
    def warmup_status(self) -> Dict[str, bool]:
        """Get warmup status for each timeframe."""
        return self._warmup_status.copy()

    def get_feature_names(self, top25_only: bool = False) -> List[str]:
        """Get list of all feature names with timeframe suffixes."""
        names = []

        base_features = TOP_25_BASE_FEATURES if top25_only else None

        for tf, lib in self._libs.items():
            if base_features:
                for fname in base_features:
                    names.append(f"{fname}_{tf}")
            else:
                for fname in lib.get_feature_names():
                    names.append(f"{fname}_{tf}")

        return names

    def reset(self) -> None:
        """Reset all libraries."""
        for lib in self._libs.values():
            lib.reset()
        self._warmup_status = {tf: False for tf in self._libs.keys()}
