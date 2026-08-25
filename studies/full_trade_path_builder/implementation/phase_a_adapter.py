"""Frozen Bullish-Fade F3 adapter with causal provenance enforcement."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Sequence

from features.registry import resolve_feature_request
from studies.nt_reduced_f3_top25_population_parity_smoke.implementation.reduced_feature_engine import (
    ReducedFeatureEngine,
)

from .phase_a_core import SourceProvenance

FEATURE_SOURCE = Path(
    "studies/runtime_constrained_f3_feature_reduction/results/candidate_feature_sets.json"
)
FEATURE_KEY = "F3_top25_gbt_v1"
EXPECTED_HASH = "8bcfeb74ab3b5453635ad9895fa9d15fd65866044f23fa0415bfc796e5fd6299"
PRICE_FEATURES = {
    "rolling_5m_low_signed_distance_atr",
    "rolling_15m_high_signed_distance_atr",
    "rolling_60m_high_signed_distance_atr",
    "rolling_15m_low_signed_distance_atr",
    "rolling_30m_low_signed_distance_atr",
    "rolling_30m_high_signed_distance_atr",
    "opening_range_30m_low_developing_signed_distance_points",
    "full_level_envelope_width_atr",
    "prior_day_close_signed_distance_atr",
    "pct_levels_behind_trade",
    "prior_day_low_signed_distance_points",
    "opening_range_30m_low_final_signed_distance_points",
    "price_position_in_full_envelope",
    "n_levels_below",
}


def load_ordered_features(repo_root: Path) -> list[str]:
    raw = json.loads((repo_root / FEATURE_SOURCE).read_text(encoding="utf-8"))[FEATURE_KEY]
    if raw["sha256"] != EXPECTED_HASH or raw["actual_n_features"] != 25:
        raise RuntimeError("frozen F3 feature-set identity mismatch")
    names = list(raw["features"])
    for name in names:
        try:
            meta = resolve_feature_request(name)
        except Exception as exc:
            raise RuntimeError("frozen feature missing from canonical resolver") from exc
        expected_tf = "1m" if name in PRICE_FEATURES else "1s"
        if meta["status"] != "verified":
            raise RuntimeError(f"unfrozen registry identity for {name}")
        streams = set(meta["input_requirements"].get("required_streams", []))
        if f"completed_{expected_tf}" not in streams:
            raise RuntimeError(
                f"source timeframe mismatch for {name}: {sorted(streams)} does not include {expected_tf}"
            )
    return names


class BullishFadeAdapter:
    def __init__(self, ordered_features: Sequence[str]):
        if len(ordered_features) != 25 or len(set(ordered_features)) != 25:
            raise ValueError("adapter requires exactly 25 unique ordered features")
        self.features = list(ordered_features)
        self.engine = ReducedFeatureEngine(self.features)

    def snapshot(
        self,
        decision_ns: int,
        reference_price: float,
        atr_at_checkpoint: float,
        provenance: SourceProvenance,
    ) -> tuple[list[float], dict[str, bool], bool]:
        provenance.assert_admissible(decision_ns)
        if not math.isfinite(atr_at_checkpoint) or atr_at_checkpoint <= 0:
            return [float("nan")] * 25, {f: True for f in self.features}, True
        vector, nulls, any_null = self.engine.ordered_vector(
            decision_ns, reference_price, atr_at_checkpoint
        )
        finite = [v is not None and isinstance(v, (int, float)) and math.isfinite(float(v))
                  for v in vector]
        any_bad = any_null or not all(finite)
        return [float(v) if ok else float("nan") for v, ok in zip(vector, finite)], nulls, any_bad
