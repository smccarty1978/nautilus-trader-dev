"""Feature Library for ML Training.

Comprehensive feature extraction using NautilusTrader indicators.
All features computed bar-by-bar with no look-ahead bias.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
import pytz
import pandas as pd

from nautilus_trader.indicators import (
    ExponentialMovingAverage,
    SimpleMovingAverage,
    AverageTrueRange,
    RelativeStrengthIndex,
    Stochastics,
    CommodityChannelIndex,
    RateOfChange,
    BollingerBands,
    KeltnerChannel,
    DonchianChannel,
    MovingAverageConvergenceDivergence,
    OnBalanceVolume,
    DirectionalMovement,
    AroonOscillator,
    ChandeMomentumOscillator,
    LinearRegression,
    HullMovingAverage,
    VolatilityRatio,
    Swings,
    Pressure,
    EfficiencyRatio,
)


CT = pytz.timezone('America/Chicago')


@dataclass
class FeatureLibraryConfig:
    """Configuration for FeatureLibrary."""

    # EMA periods
    ema_periods: List[int] = field(default_factory=lambda: [3, 5, 9, 13, 21, 50])

    # SMA periods
    sma_periods: List[int] = field(default_factory=lambda: [10, 20, 50])

    # ATR periods
    atr_periods: List[int] = field(default_factory=lambda: [14, 50, 200])

    # RSI periods
    rsi_periods: List[int] = field(default_factory=lambda: [7, 14, 21])

    # Stochastics
    stoch_k: int = 14
    stoch_d: int = 3

    # CCI
    cci_period: int = 20

    # ROC periods
    roc_periods: List[int] = field(default_factory=lambda: [5, 10, 20])

    # Bollinger Bands
    bb_period: int = 20
    bb_std: float = 2.0

    # Keltner Channel
    kc_period: int = 20
    kc_mult: float = 2.0

    # Donchian Channel
    dc_period: int = 20

    # MACD
    macd_fast: int = 12
    macd_slow: int = 26

    # ADX/Directional Movement
    adx_period: int = 14

    # Aroon
    aroon_period: int = 25

    # CMO
    cmo_period: int = 14

    # Linear Regression
    linreg_period: int = 20

    # Hull MA
    hma_period: int = 20

    # Volatility Ratio
    vol_ratio_fast: int = 14
    vol_ratio_slow: int = 50

    # Swings
    swings_period: int = 10

    # Pressure
    pressure_period: int = 10

    # Efficiency Ratio
    er_period: int = 10

    # OBV
    obv_period: int = 20

    # Slope calculation lookback
    slope_lookback: int = 5

    # Volume baseline period
    volume_baseline_period: int = 20

    # Disabled features (set of feature names to skip)
    disabled_features: Set[str] = field(default_factory=set)


class FeatureLibrary:
    """
    Comprehensive feature library for ML training.

    Categories:
    - TREND/MA: Moving averages, slopes, crossovers
    - MOMENTUM: RSI, Stochastics, CCI, ROC, CMO
    - VOLATILITY: ATR, BB width, KC width, volatility ratios
    - VOLUME: OBV, volume ratios, pressure
    - STRUCTURE: Swings, Donchian position, range metrics
    - TIME: Hour, day, RTH, session
    """

    def __init__(self, config: FeatureLibraryConfig = None):
        self.config = config or FeatureLibraryConfig()
        self._bar_count = 0

        # Initialize all indicators
        self._init_trend_indicators()
        self._init_momentum_indicators()
        self._init_volatility_indicators()
        self._init_volume_indicators()
        self._init_structure_indicators()

        # History buffers for derived features
        self._init_buffers()

    def _init_trend_indicators(self):
        """Initialize trend/MA indicators."""
        # EMAs
        self.emas = {}
        for period in self.config.ema_periods:
            self.emas[period] = ExponentialMovingAverage(period)

        # SMAs
        self.smas = {}
        for period in self.config.sma_periods:
            self.smas[period] = SimpleMovingAverage(period)

        # Hull MA
        self.hma = HullMovingAverage(self.config.hma_period)

        # MACD
        self.macd = MovingAverageConvergenceDivergence(
            self.config.macd_fast,
            self.config.macd_slow
        )

        # Linear Regression
        self.linreg = LinearRegression(self.config.linreg_period)

    def _init_momentum_indicators(self):
        """Initialize momentum indicators."""
        # RSI
        self.rsis = {}
        for period in self.config.rsi_periods:
            self.rsis[period] = RelativeStrengthIndex(period)

        # Stochastics
        self.stoch = Stochastics(self.config.stoch_k, self.config.stoch_d)

        # CCI
        self.cci = CommodityChannelIndex(self.config.cci_period)

        # ROC
        self.rocs = {}
        for period in self.config.roc_periods:
            self.rocs[period] = RateOfChange(period)

        # CMO (Chande Momentum Oscillator)
        self.cmo = ChandeMomentumOscillator(self.config.cmo_period)

        # Aroon
        self.aroon = AroonOscillator(self.config.aroon_period)

        # ADX/Directional Movement
        self.dm = DirectionalMovement(self.config.adx_period)

        # Efficiency Ratio
        self.er = EfficiencyRatio(self.config.er_period)

    def _init_volatility_indicators(self):
        """Initialize volatility indicators."""
        # ATRs
        self.atrs = {}
        for period in self.config.atr_periods:
            self.atrs[period] = AverageTrueRange(period)

        # Bollinger Bands
        self.bb = BollingerBands(self.config.bb_period, self.config.bb_std)

        # Keltner Channel
        self.kc = KeltnerChannel(self.config.kc_period, self.config.kc_mult)

        # Volatility Ratio (built-in)
        self.vol_ratio = VolatilityRatio(
            self.config.vol_ratio_fast,
            self.config.vol_ratio_slow
        )

    def _init_volume_indicators(self):
        """Initialize volume indicators."""
        # OBV
        self.obv = OnBalanceVolume(self.config.obv_period)

        # Pressure
        self.pressure = Pressure(self.config.pressure_period)

    def _init_structure_indicators(self):
        """Initialize structure indicators."""
        # Donchian Channel
        self.dc = DonchianChannel(self.config.dc_period)

        # Swings
        self.swings = Swings(self.config.swings_period)

    def _init_buffers(self):
        """Initialize history buffers for derived calculations."""
        # EMA history for slope calculations
        self.ema_buffers = {}
        for period in self.config.ema_periods:
            self.ema_buffers[period] = deque(maxlen=self.config.slope_lookback + 1)

        # Volume buffer
        self.volume_buffer = deque(maxlen=self.config.volume_baseline_period)

        # OBV buffer for slope
        self.obv_buffer = deque(maxlen=self.config.slope_lookback + 1)

        # Price buffers for HH/LL counting
        self.high_buffer = deque(maxlen=20)
        self.low_buffer = deque(maxlen=20)
        self.close_buffer = deque(maxlen=20)

        # Last bar timestamp
        self.last_bar_ts = None

    def update(self, bar) -> None:
        """Update all indicators with new bar data."""
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)
        o = float(bar.open)
        v = float(bar.volume) if hasattr(bar, 'volume') else 0.0

        self._bar_count += 1
        self.last_bar_ts = bar.ts_event

        # Update price buffers
        self.high_buffer.append(h)
        self.low_buffer.append(l)
        self.close_buffer.append(c)
        self.volume_buffer.append(v)

        # Update trend indicators
        for ema in self.emas.values():
            ema.update_raw(c)
        for sma in self.smas.values():
            sma.update_raw(c)
        self.hma.update_raw(c)
        self.macd.update_raw(c)
        self.linreg.update_raw(c)

        # Update EMA buffers for slopes
        for period, ema in self.emas.items():
            if ema.initialized:
                self.ema_buffers[period].append(ema.value)

        # Update momentum indicators
        for rsi in self.rsis.values():
            rsi.update_raw(c)
        self.stoch.update_raw(h, l, c)
        self.cci.update_raw(h, l, c)
        for roc in self.rocs.values():
            roc.update_raw(c)
        self.cmo.update_raw(c)
        self.aroon.update_raw(h, l)
        self.dm.update_raw(h, l)
        self.er.update_raw(c)

        # Update volatility indicators
        for atr in self.atrs.values():
            atr.update_raw(h, l, c)
        self.bb.update_raw(h, l, c)
        self.kc.update_raw(h, l, c)
        self.vol_ratio.update_raw(h, l, c)

        # Update volume indicators
        self.obv.update_raw(o, c, v)
        if self.obv.initialized:
            self.obv_buffer.append(self.obv.value)
        self.pressure.update_raw(h, l, c, v)

        # Update structure indicators
        self.dc.update_raw(h, l)
        # Swings needs timestamp
        ts = pd.Timestamp(bar.ts_event, tz='UTC')
        self.swings.update_raw(h, l, ts)

    def get_features(self, bar=None) -> Dict[str, float]:
        """
        Get all feature values as a dictionary.

        Call after update() to get current feature snapshot.
        Optionally pass bar for time-based features.
        """
        features = {}
        disabled = self.config.disabled_features

        # Get primary ATR for normalization
        atr = self.atrs[14].value if self.atrs[14].initialized else 1.0
        if atr <= 0:
            atr = 1.0

        close = self.close_buffer[-1] if self.close_buffer else 0.0

        # =====================================================================
        # TREND / MA FEATURES
        # =====================================================================

        # EMA values (price distance in ATR)
        for period, ema in self.emas.items():
            fname = f'ema_{period}_dist_atr'
            if fname not in disabled and ema.initialized:
                features[fname] = (close - ema.value) / atr

        # EMA slopes (normalized)
        for period in self.config.ema_periods:
            fname = f'ema_{period}_slope'
            if fname not in disabled:
                features[fname] = self._calc_slope(self.ema_buffers[period], atr)

        # EMA crossover states (short above long = 1, else -1)
        if 'ema_3_9_cross' not in disabled:
            if self.emas[3].initialized and self.emas[9].initialized:
                features['ema_3_9_cross'] = 1 if self.emas[3].value > self.emas[9].value else -1

        if 'ema_9_21_cross' not in disabled:
            if self.emas[9].initialized and self.emas[21].initialized:
                features['ema_9_21_cross'] = 1 if self.emas[9].value > self.emas[21].value else -1

        if 'ema_21_50_cross' not in disabled:
            if self.emas[21].initialized and self.emas[50].initialized:
                features['ema_21_50_cross'] = 1 if self.emas[21].value > self.emas[50].value else -1

        # SMA distances
        for period, sma in self.smas.items():
            fname = f'sma_{period}_dist_atr'
            if fname not in disabled and sma.initialized:
                features[fname] = (close - sma.value) / atr

        # Hull MA distance
        if 'hma_dist_atr' not in disabled and self.hma.initialized:
            features['hma_dist_atr'] = (close - self.hma.value) / atr

        # MACD
        if 'macd' not in disabled and self.macd.initialized:
            features['macd'] = self.macd.value / atr  # Normalized

        # Linear Regression
        if self.linreg.initialized:
            if 'linreg_slope' not in disabled:
                features['linreg_slope'] = self.linreg.slope / atr
            if 'linreg_r2' not in disabled:
                features['linreg_r2'] = self.linreg.R2

        # =====================================================================
        # MOMENTUM FEATURES
        # =====================================================================

        # RSI values
        for period, rsi in self.rsis.items():
            fname = f'rsi_{period}'
            if fname not in disabled and rsi.initialized:
                features[fname] = rsi.value

        # RSI zones (oversold < 30, neutral 30-70, overbought > 70)
        if 'rsi_14_zone' not in disabled and self.rsis[14].initialized:
            rsi_val = self.rsis[14].value
            if rsi_val < 30:
                features['rsi_14_zone'] = -1  # Oversold
            elif rsi_val > 70:
                features['rsi_14_zone'] = 1   # Overbought
            else:
                features['rsi_14_zone'] = 0   # Neutral

        # Stochastics
        if self.stoch.initialized:
            if 'stoch_k' not in disabled:
                features['stoch_k'] = self.stoch.value_k
            if 'stoch_d' not in disabled:
                features['stoch_d'] = self.stoch.value_d
            if 'stoch_cross' not in disabled:
                features['stoch_cross'] = 1 if self.stoch.value_k > self.stoch.value_d else -1

        # CCI
        if 'cci' not in disabled and self.cci.initialized:
            features['cci'] = self.cci.value

        # ROC
        for period, roc in self.rocs.items():
            fname = f'roc_{period}'
            if fname not in disabled and roc.initialized:
                features[fname] = roc.value

        # CMO
        if 'cmo' not in disabled and self.cmo.initialized:
            features['cmo'] = self.cmo.value

        # Aroon
        if self.aroon.initialized:
            if 'aroon_up' not in disabled:
                features['aroon_up'] = self.aroon.aroon_up
            if 'aroon_down' not in disabled:
                features['aroon_down'] = self.aroon.aroon_down
            if 'aroon_osc' not in disabled:
                features['aroon_osc'] = self.aroon.value

        # ADX / Directional Movement
        if self.dm.initialized:
            if 'adx' not in disabled:
                features['adx'] = self.dm.value
            if 'di_plus' not in disabled:
                features['di_plus'] = self.dm.pos
            if 'di_minus' not in disabled:
                features['di_minus'] = self.dm.neg
            if 'di_diff' not in disabled:
                features['di_diff'] = self.dm.pos - self.dm.neg

        # Efficiency Ratio
        if 'efficiency_ratio' not in disabled and self.er.initialized:
            features['efficiency_ratio'] = self.er.value

        # =====================================================================
        # VOLATILITY FEATURES
        # =====================================================================

        # ATR values
        for period, atr_ind in self.atrs.items():
            fname = f'atr_{period}'
            if fname not in disabled and atr_ind.initialized:
                features[fname] = atr_ind.value

        # ATR ratios
        if 'atr_ratio_14_50' not in disabled:
            if self.atrs[14].initialized and self.atrs[50].initialized and self.atrs[50].value > 0:
                features['atr_ratio_14_50'] = self.atrs[14].value / self.atrs[50].value

        if 'atr_ratio_14_200' not in disabled:
            if self.atrs[14].initialized and self.atrs[200].initialized and self.atrs[200].value > 0:
                features['atr_ratio_14_200'] = self.atrs[14].value / self.atrs[200].value

        # Built-in Volatility Ratio
        if 'vol_ratio' not in disabled and self.vol_ratio.initialized:
            features['vol_ratio'] = self.vol_ratio.value

        # Bollinger Bands
        if self.bb.initialized:
            bb_width = self.bb.upper - self.bb.lower
            if 'bb_width_atr' not in disabled:
                features['bb_width_atr'] = bb_width / atr
            if 'bb_position' not in disabled:
                # Position within bands: -1 at lower, 0 at middle, +1 at upper
                if bb_width > 0:
                    features['bb_position'] = (close - self.bb.middle) / (bb_width / 2)
                else:
                    features['bb_position'] = 0.0

        # Keltner Channel
        if self.kc.initialized:
            kc_width = self.kc.upper - self.kc.lower
            if 'kc_width_atr' not in disabled:
                features['kc_width_atr'] = kc_width / atr
            if 'kc_position' not in disabled:
                if kc_width > 0:
                    features['kc_position'] = (close - self.kc.middle) / (kc_width / 2)
                else:
                    features['kc_position'] = 0.0

        # Squeeze detection (BB inside KC)
        if 'squeeze' not in disabled and self.bb.initialized and self.kc.initialized:
            features['squeeze'] = 1 if (self.bb.lower > self.kc.lower and self.bb.upper < self.kc.upper) else 0

        # =====================================================================
        # VOLUME FEATURES
        # =====================================================================

        # OBV slope
        if 'obv_slope' not in disabled:
            features['obv_slope'] = self._calc_obv_slope()

        # Volume ratio (current vs average)
        if 'volume_ratio' not in disabled and len(self.volume_buffer) >= self.config.volume_baseline_period:
            avg_vol = sum(self.volume_buffer) / len(self.volume_buffer)
            if avg_vol > 0:
                features['volume_ratio'] = self.volume_buffer[-1] / avg_vol
            else:
                features['volume_ratio'] = 1.0

        # Pressure
        if self.pressure.initialized:
            if 'pressure' not in disabled:
                features['pressure'] = self.pressure.value
            if 'pressure_cumulative' not in disabled:
                features['pressure_cumulative'] = self.pressure.value_cumulative

        # =====================================================================
        # STRUCTURE FEATURES
        # =====================================================================

        # Donchian Channel position
        if self.dc.initialized:
            dc_width = self.dc.upper - self.dc.lower
            if 'dc_position' not in disabled and dc_width > 0:
                features['dc_position'] = (close - self.dc.lower) / dc_width  # 0 to 1
            if 'dc_width_atr' not in disabled:
                features['dc_width_atr'] = dc_width / atr

        # Swings
        if self.swings.initialized:
            if 'swing_direction' not in disabled:
                features['swing_direction'] = self.swings.direction
            if 'bars_since_high' not in disabled:
                features['bars_since_high'] = self.swings.since_high
            if 'bars_since_low' not in disabled:
                features['bars_since_low'] = self.swings.since_low
            if 'swing_length_atr' not in disabled:
                features['swing_length_atr'] = self.swings.length / atr if atr > 0 else 0

        # Higher Highs / Lower Lows counting
        if len(self.high_buffer) >= 10:
            if 'hh_count_10' not in disabled:
                features['hh_count_10'] = self._count_higher_highs(10)
            if 'll_count_10' not in disabled:
                features['ll_count_10'] = self._count_lower_lows(10)

        # Range position (where in recent N-bar range)
        if 'range_position_20' not in disabled and len(self.high_buffer) >= 20:
            recent_high = max(list(self.high_buffer)[-20:])
            recent_low = min(list(self.low_buffer)[-20:])
            range_size = recent_high - recent_low
            if range_size > 0:
                features['range_position_20'] = (close - recent_low) / range_size
            else:
                features['range_position_20'] = 0.5

        # =====================================================================
        # TIME FEATURES
        # =====================================================================

        if bar is not None and hasattr(bar, 'ts_event'):
            time_features = self._get_time_features(bar.ts_event)
            for fname, fval in time_features.items():
                if fname not in disabled:
                    features[fname] = fval

        return features

    def _calc_slope(self, buffer: deque, atr: float) -> float:
        """Calculate normalized slope from buffer."""
        if len(buffer) < self.config.slope_lookback + 1:
            return 0.0
        if atr <= 0:
            return 0.0

        current = buffer[-1]
        past = buffer[0]
        return (current - past) / (self.config.slope_lookback * atr)

    def _calc_obv_slope(self) -> float:
        """Calculate OBV slope (normalized by recent OBV range)."""
        if len(self.obv_buffer) < self.config.slope_lookback + 1:
            return 0.0

        current = self.obv_buffer[-1]
        past = self.obv_buffer[0]

        # Normalize by OBV range
        obv_range = max(self.obv_buffer) - min(self.obv_buffer)
        if obv_range > 0:
            return (current - past) / obv_range
        return 0.0

    def _count_higher_highs(self, lookback: int) -> int:
        """Count higher highs in recent bars."""
        highs = list(self.high_buffer)[-lookback:]
        count = 0
        for i in range(1, len(highs)):
            if highs[i] > highs[i-1]:
                count += 1
        return count

    def _count_lower_lows(self, lookback: int) -> int:
        """Count lower lows in recent bars."""
        lows = list(self.low_buffer)[-lookback:]
        count = 0
        for i in range(1, len(lows)):
            if lows[i] < lows[i-1]:
                count += 1
        return count

    def _get_time_features(self, ts_event) -> Dict[str, float]:
        """Extract time-based features from timestamp."""
        import pandas as pd

        features = {}

        # Convert to datetime
        if isinstance(ts_event, (int, float)):
            dt = pd.Timestamp(ts_event, tz='UTC').astimezone(CT)
        else:
            dt = ts_event.astimezone(CT) if hasattr(ts_event, 'astimezone') else ts_event

        # Hour (0-23)
        features['hour_ct'] = dt.hour

        # Day of week (0=Monday, 4=Friday)
        features['day_of_week'] = dt.weekday()

        # Is RTH (8:30 - 15:00 CT)
        rth_start = dt.replace(hour=8, minute=30, second=0)
        rth_end = dt.replace(hour=15, minute=0, second=0)
        is_rth = rth_start <= dt <= rth_end
        features['is_rth'] = 1 if is_rth else 0

        # Minutes since RTH open
        if is_rth:
            features['minutes_since_rth_open'] = (dt - rth_start).total_seconds() / 60
        else:
            features['minutes_since_rth_open'] = -1

        # Session (simplified: 0=overnight, 1=morning, 2=midday, 3=afternoon)
        hour = dt.hour
        if 8 <= hour < 11:
            features['session'] = 1  # Morning
        elif 11 <= hour < 13:
            features['session'] = 2  # Midday
        elif 13 <= hour < 15:
            features['session'] = 3  # Afternoon
        else:
            features['session'] = 0  # Overnight/Extended

        return features

    @property
    def is_warmed_up(self) -> bool:
        """Check if all primary indicators have enough data."""
        return (
            self.emas[9].initialized and
            self.atrs[14].initialized and
            self.rsis[14].initialized and
            len(self.ema_buffers[9]) >= self.config.slope_lookback + 1
        )

    @property
    def is_fully_warmed_up(self) -> bool:
        """Check if ALL indicators including slow ones are warmed up."""
        return (
            self.is_warmed_up and
            self.atrs[200].initialized and
            self.emas[50].initialized and
            self.linreg.initialized and
            self.dm.initialized
        )

    def get_feature_names(self) -> List[str]:
        """Get list of all possible feature names."""
        # Generate a dummy features dict to get names
        # This is a static list based on configuration
        names = []

        # Trend
        for p in self.config.ema_periods:
            names.append(f'ema_{p}_dist_atr')
            names.append(f'ema_{p}_slope')
        names.extend(['ema_3_9_cross', 'ema_9_21_cross', 'ema_21_50_cross'])
        for p in self.config.sma_periods:
            names.append(f'sma_{p}_dist_atr')
        names.extend(['hma_dist_atr', 'macd', 'linreg_slope', 'linreg_r2'])

        # Momentum
        for p in self.config.rsi_periods:
            names.append(f'rsi_{p}')
        names.append('rsi_14_zone')
        names.extend(['stoch_k', 'stoch_d', 'stoch_cross', 'cci'])
        for p in self.config.roc_periods:
            names.append(f'roc_{p}')
        names.extend(['cmo', 'aroon_up', 'aroon_down', 'aroon_osc'])
        names.extend(['adx', 'di_plus', 'di_minus', 'di_diff', 'efficiency_ratio'])

        # Volatility
        for p in self.config.atr_periods:
            names.append(f'atr_{p}')
        names.extend(['atr_ratio_14_50', 'atr_ratio_14_200', 'vol_ratio'])
        names.extend(['bb_width_atr', 'bb_position', 'kc_width_atr', 'kc_position', 'squeeze'])

        # Volume
        names.extend(['obv_slope', 'volume_ratio', 'pressure', 'pressure_cumulative'])

        # Structure
        names.extend(['dc_position', 'dc_width_atr'])
        names.extend(['swing_direction', 'bars_since_high', 'bars_since_low', 'swing_length_atr'])
        names.extend(['hh_count_10', 'll_count_10', 'range_position_20'])

        # Time
        names.extend(['hour_ct', 'day_of_week', 'is_rth', 'minutes_since_rth_open', 'session'])

        # Filter disabled
        return [n for n in names if n not in self.config.disabled_features]

    def reset(self) -> None:
        """Reset all indicators and buffers."""
        self._bar_count = 0

        # Reset all indicators
        for ema in self.emas.values():
            ema.reset()
        for sma in self.smas.values():
            sma.reset()
        self.hma.reset()
        self.macd.reset()
        self.linreg.reset()

        for rsi in self.rsis.values():
            rsi.reset()
        self.stoch.reset()
        self.cci.reset()
        for roc in self.rocs.values():
            roc.reset()
        self.cmo.reset()
        self.aroon.reset()
        self.dm.reset()
        self.er.reset()

        for atr in self.atrs.values():
            atr.reset()
        self.bb.reset()
        self.kc.reset()
        self.vol_ratio.reset()

        self.obv.reset()
        self.pressure.reset()

        self.dc.reset()
        self.swings.reset()

        # Clear buffers
        for buf in self.ema_buffers.values():
            buf.clear()
        self.volume_buffer.clear()
        self.obv_buffer.clear()
        self.high_buffer.clear()
        self.low_buffer.clear()
        self.close_buffer.clear()
