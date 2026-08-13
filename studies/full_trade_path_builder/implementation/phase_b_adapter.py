"""Frozen, independent Phase B model adapters and scorers."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Callable
import warnings

import joblib
import numpy as np
from numba import njit
from scipy.special import expit

warnings.filterwarnings(
    "ignore",
    message="X does not have valid feature names.*",
    category=UserWarning,
)

_LONG_IMPL = (
    Path(__file__).resolve().parents[2]
    / "nt_long_top25_march2025_runtime_parity"
    / "implementation"
)
if str(_LONG_IMPL) not in sys.path:
    sys.path.insert(0, str(_LONG_IMPL))
from studies.nt_long_top25_march2025_runtime_parity.implementation.long_feature_engine import (  # noqa: E402
    LongFeatureEngine,
)
import common as _LONG_COMMON  # noqa: E402

from .phase_a_core import SourceProvenance
from .phase_a_runtime import FrozenBullishScorer, load_frozen_adapter, sha256_file

EXPECTED_BEAR_MODEL_SHA256 = (
    "1d696d85f2e31026db8415fb15913267d447bd7fde9be0fcefed490c7bf4af26"
)
EXPECTED_FEATURE_HASH = (
    "8bcfeb74ab3b5453635ad9895fa9d15fd65866044f23fa0415bfc796e5fd6299"
)
BEAR_DEPENDENCIES = {
    "studies/nt_long_top25_march2025_runtime_parity/implementation/long_feature_engine.py":
        "b4b71cb312c4f475cac6d11af849dc0c87289cfc2baab75be6fb076f0c9a9be6",
    "studies/nt_long_top25_march2025_runtime_parity/implementation/common.py":
        "f518d6c800704c2529d069d38abe1a296f352dc24ab9be93d8b39da424f626c0",
    "features/trackers/ohlcv_delta.py":
        "2fd438659ed26e117c2f404c812d14ac11ca066a30c9033da2c690fd9eb3e0f6",
    "features/trackers/price_levels.py":
        "57556de862b4f226db9edaa4b082da263f8c4faeb69571ad12e92eecfd1f91cf",
    "features/trackers/median_center.py":
        "b800317b95f7d744d311eb93a590ee745a7ec17b9e1475cf84726366eacee3d0",
    "studies/fable5_pre_flip_d10_reversal_entry/strategy.py":
        "b2868dffd763c937f14e6015790460edaca7adb5674e1a1e6722b2d4c11b334d",
}


def vector_sha256(vector: list[float]) -> str:
    """Hash the exact ordered little-endian float64 runtime vector."""
    arr = np.asarray(vector, dtype="<f8")
    return hashlib.sha256(arr.tobytes(order="C")).hexdigest()


@njit(cache=True)
def _predict_flat_hgb(
    x, offsets, values, features, thresholds, missing_left, left, right, is_leaf,
    baseline,
):
    raw = baseline
    for tree in range(len(offsets)):
        offset = offsets[tree]
        node = offset
        while is_leaf[node] == 0:
            value = x[features[node]]
            if np.isnan(value):
                node = offset + (left[node] if missing_left[node] else right[node])
            elif value <= thresholds[node]:
                node = offset + left[node]
            else:
                node = offset + right[node]
        raw += values[node]
    return raw


class ExactFastHGBProbability:
    """Exact frozen-tree traversal without sklearn's per-row validation overhead."""

    def __init__(self, model):
        if model.n_trees_per_iteration_ != 1:
            raise RuntimeError("fast scorer only supports frozen binary HGB models")
        nodes = [iteration[0].nodes for iteration in model._predictors]
        self.offsets = np.asarray(
            np.cumsum([0, *[len(node) for node in nodes[:-1]]]), dtype=np.int64
        )
        joined = np.concatenate(nodes)
        if np.any(joined["is_categorical"]):
            raise RuntimeError("fast scorer does not support categorical splits")
        self.values = joined["value"].astype(np.float64)
        self.features = joined["feature_idx"].astype(np.int64)
        self.thresholds = joined["num_threshold"].astype(np.float64)
        self.missing_left = joined["missing_go_to_left"].astype(np.uint8)
        self.left = joined["left"].astype(np.int64)
        self.right = joined["right"].astype(np.int64)
        self.is_leaf = joined["is_leaf"].astype(np.uint8)
        self.baseline = float(model._baseline_prediction[0, 0])
        _predict_flat_hgb(
            np.zeros(model.n_features_in_, dtype=np.float64),
            self.offsets, self.values, self.features, self.thresholds,
            self.missing_left, self.left, self.right, self.is_leaf, self.baseline,
        )

    def probability(self, vector: list[float]) -> float:
        raw = _predict_flat_hgb(
            np.asarray(vector, dtype=np.float64),
            self.offsets, self.values, self.features, self.thresholds,
            self.missing_left, self.left, self.right, self.is_leaf, self.baseline,
        )
        return float(expit(raw))


class FrozenBearishScorer:
    def __init__(self, artifact_dir: Path):
        self.artifact_dir = artifact_dir
        repo_root = Path(__file__).resolve().parents[3]
        for relative, expected in BEAR_DEPENDENCIES.items():
            if sha256_file(repo_root / relative) != expected:
                raise RuntimeError(f"frozen Bearish dependency mismatch: {relative}")
        if sha256_file(artifact_dir / "model.joblib") != EXPECTED_BEAR_MODEL_SHA256:
            raise RuntimeError("frozen Bearish model hash mismatch")
        raw = json.loads((artifact_dir / "feature_list.json").read_text(encoding="utf-8"))
        self.features = list(raw["features"] if isinstance(raw, dict) else raw)
        encoded = json.dumps(self.features).encode()
        if hashlib.sha256(encoded).hexdigest() != EXPECTED_FEATURE_HASH:
            raise RuntimeError("frozen Bearish ordered-feature hash mismatch")
        if sha256_file(artifact_dir / "feature_mapping.json") != (
            "c8984d771df35011ab3489ba762f5ef0a1f276eada6e8e7b893679e1649c6fd5"
        ):
            raise RuntimeError("frozen Bearish feature mapping mismatch")
        self.model = joblib.load(artifact_dir / "model.joblib")
        if list(self.model.classes_) != [0, 1]:
            raise RuntimeError("unexpected frozen Bearish model classes")

    def probability(self, vector: list[float]) -> float:
        arr = np.asarray(vector, dtype=np.float64).reshape(1, -1)
        if arr.shape[1] != len(self.features):
            raise ValueError("Bearish runtime vector width mismatch")
        return float(self.model.predict_proba(arr)[0, 1])


class BearishFadeAdapter:
    """Strict-training-compatible 1s-derived-minute adapter, direction +1."""

    def __init__(self, ordered_features: list[str], is_rth_ts: Callable[[int], bool]):
        if len(ordered_features) != 25 or len(set(ordered_features)) != 25:
            raise ValueError("Bearish adapter requires 25 unique ordered features")
        self.features = list(ordered_features)
        self.engine = LeanStrictLongFeatureEngine(self.features, is_rth_ts)

    def snapshot(
        self,
        decision_ns: int,
        snap_bar_ts: int,
        reference_price: float,
        atr_at_checkpoint: float,
        prevailing_direction: int,
        provenance: SourceProvenance,
    ) -> tuple[list[float], dict[str, bool], bool]:
        provenance.assert_admissible(decision_ns)
        if not math.isfinite(atr_at_checkpoint) or atr_at_checkpoint <= 0:
            return [float("nan")] * 25, {f: True for f in self.features}, True
        vector, nulls, any_null = self.engine.ordered_vector(
            snap_bar_ts=snap_bar_ts,
            observation_ts=decision_ns,
            reference_price=reference_price,
            atr=atr_at_checkpoint,
            current_regime=prevailing_direction,
            center_atr=atr_at_checkpoint,
        )
        finite = [
            value is not None
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
            for value in vector
        ]
        any_bad = any_null or not all(finite)
        return (
            [float(value) if ok else float("nan") for value, ok in zip(vector, finite)],
            nulls,
            any_bad,
        )


class LeanStrictLongFeatureEngine(LongFeatureEngine):
    """Exact strict Top-25 path without unused median/sequence computation."""

    def update_1s(self, ts_event, open_px, high, low, close, volume, current_regime, atr):
        est = self.ohlcv.update(ts_event, open_px, high, low, close, volume)
        bar = (
            int(ts_event), float(high), float(low), float(volume),
            est.get("bar_est_delta", 0.0) if est else 0.0,
        )
        mkey = _LONG_COMMON.minute_bucket_key(int(ts_event))
        if self._minute_key is None:
            self._minute_key = mkey
            self._m_open, self._m_high, self._m_low = open_px, high, low
            self._minute_buffer = [bar]
        elif mkey != self._minute_key:
            self._finalize_minute()
            self._minute_key = mkey
            self._m_open, self._m_high, self._m_low = open_px, high, low
            self._minute_buffer = [bar]
        else:
            self._m_high = max(self._m_high, high)
            self._m_low = min(self._m_low, low)
            self._minute_buffer.append(bar)
        self._prev_close = close
        return est

    def snapshot(
        self, snap_bar_ts, observation_ts, reference_price, atr,
        current_regime=-1, center_atr=None,
    ):
        a = float(atr) if atr and atr > 0 else 1.0
        merged = {
            **self._selected_ohlcv(a),
            **self._selected_price(reference_price, a),
        }
        values, null_mask = {}, {}
        for feature in self.ordered_features:
            value = merged.get(feature)
            values[feature] = value
            null_mask[feature] = value is None
        return values, null_mask

    def _selected_ohlcv(self, atr):
        tracker = self.ohlcv
        if not tracker.ts:
            return {}
        ts = np.asarray(tracker.ts, dtype=np.int64)
        opens = np.asarray(tracker.opens, dtype=np.float64)
        highs = np.asarray(tracker.highs, dtype=np.float64)
        lows = np.asarray(tracker.lows, dtype=np.float64)
        closes = np.asarray(tracker.closes, dtype=np.float64)
        volumes = np.asarray(tracker.volumes, dtype=np.float64)
        deltas = np.asarray(tracker.est_deltas, dtype=np.float64)
        obs = int(ts[-1])
        out = {}
        for seconds in (30, 60, 300, 1800):
            cutoff = obs - seconds * 1_000_000_000
            mask = ts > cutoff
            available = bool(ts[0] <= cutoff + 1_000_000_000)
            if not available or not np.any(mask):
                values = {
                    30: ("price_change_atr_30s",),
                    60: ("price_change_points_60s", "price_change_atr_60s"),
                    300: ("est_bear_vol_sum_300s",),
                    1800: (
                        "range_points_1800s", "est_delta_sum_1800s",
                        "up_down_vol_ratio_1800s", "vol_max_1s_1800s",
                    ),
                }[seconds]
                out.update({name: None for name in values})
                continue
            wo, wh, wl = opens[mask], highs[mask], lows[mask]
            wc, wv, wd = closes[mask], volumes[mask], deltas[mask]
            change = float(wc[-1] - wo[0])
            if seconds == 30:
                out["price_change_atr_30s"] = change / atr
            elif seconds == 60:
                out["price_change_points_60s"] = change
                out["price_change_atr_60s"] = change / atr
            elif seconds == 300:
                rng = wh - wl
                safe = np.where(rng > 0, rng, 1.0)
                bull_ratio = np.where(
                    rng > 0, np.clip((wc - wl) / safe, 0.0, 1.0), 0.5
                )
                out["est_bear_vol_sum_300s"] = float((wv - wv * bull_ratio).sum())
            else:
                out["range_points_1800s"] = float(wh.max() - wl.min())
                out["est_delta_sum_1800s"] = float(wd.sum())
                up = float(wv[wc > wo].sum())
                down = float(wv[wc < wo].sum())
                out["up_down_vol_ratio_1800s"] = up / max(down, 1e-9)
                out["vol_max_1s_1800s"] = float(wv.max())
        if tracker._rth_active and tracker._rth_start_ts is not None:
            out.update({
                "rth_elapsed_seconds": (obs - tracker._rth_start_ts) / 1_000_000_000,
                "rth_vol_cum": tracker._rth_vol_cum,
                "rth_abs_delta_cum": tracker._rth_abs_delta_cum,
            })
        else:
            out.update({
                "rth_elapsed_seconds": None,
                "rth_vol_cum": None,
                "rth_abs_delta_cum": None,
            })
        return out

    def _selected_price(self, reference_price, atr, direction=+1):
        levels = self.price._raw_levels()
        prices = {name: price for name, (price, _) in levels.items() if price is not None}
        def signed(name, normalized=True):
            price = levels[name][0]
            if price is None:
                return None
            value = reference_price - price
            return value / atr if normalized else value
        out = {
            "rolling_5m_low_signed_distance_atr": signed("rolling_5m_low"),
            "rolling_15m_high_signed_distance_atr": signed("rolling_15m_high"),
            "rolling_60m_high_signed_distance_atr": signed("rolling_60m_high"),
            "rolling_15m_low_signed_distance_atr": signed("rolling_15m_low"),
            "rolling_30m_low_signed_distance_atr": signed("rolling_30m_low"),
            "rolling_30m_high_signed_distance_atr": signed("rolling_30m_high"),
            "opening_range_30m_low_developing_signed_distance_points": signed(
                "opening_range_30m_low_developing", normalized=False
            ),
            "prior_day_close_signed_distance_atr": signed("prior_day_close"),
            "prior_day_low_signed_distance_points": signed(
                "prior_day_low", normalized=False
            ),
            "opening_range_30m_low_final_signed_distance_points": signed(
                "opening_range_30m_low_final", normalized=False
            ),
        }
        if prices:
            low, high = min(prices.values()), max(prices.values())
            width = high - low
            out["full_level_envelope_width_atr"] = width / atr
            out["price_position_in_full_envelope"] = (
                (reference_price - low) / width if width > 0 else None
            )
            out["pct_levels_behind_trade"] = (
                sum(
                    price < reference_price if direction == +1
                    else price > reference_price
                    for price in prices.values()
                ) / len(prices)
            )
            tolerance = max(
                self.price.tick_size,
                self.price.touch_tolerance_ticks * self.price.tick_size,
            )
            out["n_levels_below"] = sum(
                reference_price > price + tolerance for price in prices.values()
            )
        else:
            out.update({
                "full_level_envelope_width_atr": None,
                "price_position_in_full_envelope": None,
                "pct_levels_behind_trade": None,
                "n_levels_below": None,
            })
        return out


class LeanBullishAdapter:
    """Read the frozen Bull state with the same specialized Top-25 projection."""

    def __init__(self, frozen):
        self.features = frozen.features
        self.engine = frozen.engine
        self._projection = LeanStrictLongFeatureEngine.__new__(
            LeanStrictLongFeatureEngine
        )
        self._projection.ohlcv = self.engine.ohlcv
        self._projection.price = self.engine.price

    def snapshot(self, decision_ns, reference_price, atr_at_checkpoint, provenance):
        provenance.assert_admissible(decision_ns)
        if not math.isfinite(atr_at_checkpoint) or atr_at_checkpoint <= 0:
            return [float("nan")] * 25, {f: True for f in self.features}, True
        merged = {
            **self._projection._selected_ohlcv(atr_at_checkpoint),
            **self._projection._selected_price(
                reference_price, atr_at_checkpoint, direction=-1
            ),
        }
        vector = [merged.get(feature) for feature in self.features]
        nulls = {feature: merged.get(feature) is None for feature in self.features}
        finite = [
            value is not None
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
            for value in vector
        ]
        bad = any(nulls.values()) or not all(finite)
        return (
            [float(value) if ok else float("nan") for value, ok in zip(vector, finite)],
            nulls, bad,
        )


def load_phase_b_adapters(
    repo_root: Path,
    is_rth_ts: Callable[[int], bool],
):
    bull_dir = (
        repo_root
        / "studies/full_trade_path_builder/artifacts/BULLISH_STRICT_top25_gbt_v2"
    )
    bear_dir = (
        repo_root
        / "studies/freeze_long_strict_models_v2/artifacts/LONG_STRICT_top25_gbt_v2"
    )
    bull_adapter = LeanBullishAdapter(load_frozen_adapter(bull_dir))
    bull_scorer = FrozenBullishScorer(bull_dir)
    bear_scorer = FrozenBearishScorer(bear_dir)
    bull_scorer.fast_probability = ExactFastHGBProbability(bull_scorer.model)
    bear_scorer.fast_probability = ExactFastHGBProbability(bear_scorer.model)
    # Strict attachment classifies its synthetic minute by the close label
    # itself (08:30 is the first RTH feature minute), not by close-minus-1s.
    from .phase_a_strategy import is_rth_decision
    bear_adapter = BearishFadeAdapter(bear_scorer.features, is_rth_decision)
    if bull_adapter.features != bull_scorer.features:
        raise RuntimeError("Bullish adapter/model ordered features disagree")
    return bull_adapter, bull_scorer, bear_adapter, bear_scorer
