"""Real-data validation of ReducedFeatureEngine against the actual 25
feature values stored in prepared_2025.parquet for a real March 2025 regime.
Exact match expected (both sides ultimately call the same OHLCVDeltaTracker/
PriceLevelTracker classes via the same attach_features.py-derived call
pattern) -- 0.0 abs diff on the first validation pass, confirmed this session."""
from __future__ import annotations

import json
import sys
from pathlib import Path

IMPL = Path(__file__).resolve().parents[1] / "implementation"
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(IMPL) not in sys.path:
    sys.path.insert(0, str(IMPL))

import numpy as np
import pandas as pd
import pytest

from reduced_feature_engine import ReducedFeatureEngine  # noqa: E402

RAW_1S_2025 = ROOT / "data" / "raw" / "NQ_v0_1s_2025.parquet"
PREPARED_2025 = (ROOT / "studies" / "short_rth_pure_flip_prediction_enriched"
                 / "_work" / "prepared_2025.parquet")
CANDIDATE_FEATURE_SETS = (ROOT / "studies" / "runtime_constrained_f3_feature_reduction"
                          / "results" / "candidate_feature_sets.json")

pytestmark = pytest.mark.skipif(
    not (RAW_1S_2025.exists() and PREPARED_2025.exists()),
    reason="requires data/raw/NQ_v0_1s_2025.parquet and prepared_2025.parquet")

NS = 1_000_000_000


def _minute_bucket_key(bar_ts: int) -> int:
    return (bar_ts - 1) // (60 * NS)


def _is_rth(ts_ns: int) -> bool:
    t = pd.Timestamp(ts_ns, unit="ns", tz="UTC").tz_convert("America/Chicago")
    m = t.hour * 60 + t.minute
    return 8 * 60 + 30 <= m < 15 * 60


def test_feature_engine_exact_match_on_real_march_regime():
    feat_list = json.loads(CANDIDATE_FEATURE_SETS.read_text())["F3_top25_gbt_v1"]["features"]

    cand = pd.read_parquet(PREPARED_2025, columns=feat_list + [
        "regime_start_ns", "observation_time", "atr_at_entry"])
    obs_dt = pd.to_datetime(cand["observation_time"], unit="ns", utc=True)
    march = cand.loc[obs_dt.dt.strftime("%Y-%m") == "2025-03"]
    sample_regime = int(march["regime_start_ns"].iloc[0])
    sub = march[march["regime_start_ns"] == sample_regime].sort_values("observation_time")
    obs_times = set(sub["observation_time"].tolist())

    raw = pd.read_parquet(RAW_1S_2025, columns=["open", "high", "low", "close", "volume"])
    ts1s = raw.index.view("int64")
    opens, highs = raw["open"].to_numpy(), raw["high"].to_numpy()
    lows, closes, vols = raw["low"].to_numpy(), raw["close"].to_numpy(), raw["volume"].to_numpy()

    lead_start = sample_regime - 7 * 24 * 3600 * NS
    i0 = int(np.searchsorted(ts1s, lead_start, side="left"))
    i1 = int(np.searchsorted(ts1s, int(sub["observation_time"].max()) + 5 * NS, side="left"))

    engine = ReducedFeatureEngine(feat_list)
    current_minute, minute_o, minute_h, minute_l = None, None, None, None
    minute_buf, was_rth = [], False
    results: dict[int, dict] = {}

    for i in range(i0, i1):
        bar_ts = int(ts1s[i])
        b_est = engine.update_1s(bar_ts, opens[i], highs[i], lows[i], closes[i], vols[i])
        mk = _minute_bucket_key(bar_ts)
        if current_minute is None:
            current_minute = mk
            minute_o, minute_h, minute_l = opens[i], highs[i], lows[i]
            minute_buf = [(bar_ts, highs[i], lows[i], vols[i], b_est["bar_est_delta"])]
        elif mk != current_minute:
            m_close_ts = int((current_minute + 1) * 60 * NS)
            now_rth = _is_rth(m_close_ts)
            if now_rth and not was_rth:
                engine.reset_rth(m_close_ts)
            elif not now_rth and was_rth:
                engine.end_rth()
            was_rth = now_rth
            for bts, bh, bl, bv, bd in minute_buf:
                engine.accumulate_regime_rth(bts, bh, bl, bv, bd)
            engine.update_1m(m_close_ts, minute_o, minute_h, minute_l,
                             closes[i - 1] if i > 0 else opens[i], now_rth)
            current_minute = mk
            minute_o, minute_h, minute_l = opens[i], highs[i], lows[i]
            minute_buf = [(bar_ts, highs[i], lows[i], vols[i], b_est["bar_est_delta"])]
        else:
            minute_h, minute_l = max(minute_h, highs[i]), min(minute_l, lows[i])
            minute_buf.append((bar_ts, highs[i], lows[i], vols[i], b_est["bar_est_delta"]))

        if bar_ts in obs_times:
            atr = float(sub.loc[sub["observation_time"] == bar_ts, "atr_at_entry"].iloc[0])
            vec, _, _ = engine.ordered_vector(bar_ts, closes[i], atr)
            results[bar_ts] = dict(zip(feat_list, vec))

    assert len(results) > 50, "expected a substantial number of real checkpoint snapshots"
    max_abs_diff = 0.0
    n_compared = 0
    for _, row in sub.iterrows():
        t = int(row["observation_time"])
        if t not in results:
            continue
        live = results[t]
        for f in feat_list:
            off_v, live_v = row[f], live[f]
            if off_v is None or live_v is None or (isinstance(off_v, float) and np.isnan(off_v)):
                continue
            max_abs_diff = max(max_abs_diff, abs(float(off_v) - float(live_v)))
            n_compared += 1

    assert n_compared > 1000, "expected a substantial number of feature-cell comparisons"
    assert max_abs_diff < 1e-9, f"feature value mismatch: max_abs_diff={max_abs_diff}"
