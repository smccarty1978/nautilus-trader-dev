"""Pre-flight: verify the three `seq_*r_*` features in long TOP25 are identical
between the OFFLINE producer the frozen model was trained on and the LIVE
producer the NT runtime would use.

  offline: regime_sequence_chop_context/build_regime_sequence.compute_sequence_features
           (fed by CODEX_5_X_build_regime_history.build_completed_regimes)
  live:    features/trackers/median_center.MedianCenterTracker  (streaming deque)

`features/registry.py` declares MedianCenterTracker as THE implementation for
these features, but the frozen model was trained on the offline path. That
equivalence claim has never been tested. If it fails, long TOP25 is not
live-scorable as frozen and building an NT harness would be wasted work.

Targets (all ATR-free and direction-free, so no ATR/regime-direction plumbing
is needed to compare them):
    seq_8r_mean_retracement, seq_12r_mean_retracement, seq_5r_max_overlap

Method
------
1. Load the SAME raw 1s parquet the atlas used (data/raw/NQ_v0_1s_2025.parquet)
   -- not the NT catalog, which is known to differ on roll days.
2. Reproduce the offline 1m regimes + completed-regime table verbatim.
3. Stream every 1s bar through a real MedianCenterTracker, driven by the same
   1m regime series (isolating record-construction from regime DETECTION,
   which is a separate Phase-1 concern).
4. At each frozen March observation_time, snapshot the tracker at the last
   completed bar (strict `side='left'-1`) and compare to the frozen values in
   prepared_long_2025.parquet.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

STUDY = Path(__file__).resolve().parents[1]
ROOT = STUDY.parents[1]
RESULTS = STUDY / "results"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"))
sys.path.insert(0, str(ROOT / "studies" / "regime_sequence_chop_context"))

from CODEX_5_X_build_regime_history import build_completed_regimes  # noqa: E402
from CODEX_5_X_common import RAW_1S  # noqa: E402
from build_regime_sequence import compute_sequence_features  # noqa: E402
from features.trackers.median_center import MedianCenterTracker  # noqa: E402
from reproduce_regimes import aggregate_and_run_regimes  # noqa: E402

TARGETS = ["seq_8r_mean_retracement", "seq_12r_mean_retracement", "seq_5r_max_overlap"]
PREPARED = (ROOT / "studies" / "long_rth_mirrored_surface_top100_training" / "_work"
            / "prepared_long_2025.parquet")

# Warmup start must precede March by enough to accumulate >=12 completed regimes
# (regimes run ~6/day, so ~1 week is ample) plus the 1h 1s deque.
WARMUP_START = pd.Timestamp("2025-02-20", tz="UTC")
COMPARE_START = pd.Timestamp("2025-03-03", tz="UTC")
COMPARE_END = pd.Timestamp("2025-03-11", tz="UTC")


def _ns(index) -> np.ndarray:
    """Epoch-ns int64 from a pandas index that may be tz-aware datetime64 or
    already integral. The raw 1s parquet uses a tz-aware DatetimeIndex, which
    the offline helpers consume directly - so this only derives a parallel ns
    array and never mutates `raw.index` itself."""
    if isinstance(index, pd.DatetimeIndex):
        return index.tz_convert("UTC").asi8 if index.tz is not None else index.asi8
    return np.asarray(index, dtype=np.int64)


def main() -> None:
    t0 = time.time()
    raw = pd.read_parquet(RAW_1S[2025])
    if not raw.index.is_monotonic_increasing or not raw.index.is_unique:
        raise SystemExit("raw 1s index must be increasing and unique")
    idx_ns = _ns(raw.index)
    sl = (idx_ns >= WARMUP_START.value) & (idx_ns < COMPARE_END.value)
    raw = raw.iloc[sl]
    print(f"raw 1s bars in window: {len(raw):,}")

    # ---- offline regime reproduction (verbatim path) ----
    df_1m = aggregate_and_run_regimes(raw, "1m")
    regimes = build_completed_regimes(df_1m, raw)
    print(f"1m bars: {len(df_1m):,} | completed regimes: {len(regimes):,}")

    # 1m regime series -> per-1s-bar regime, using each 1m bar's close_ts.
    #
    # A 1s bar at time t carries the regime of the most recent 1m bar whose
    # close_ts is <= t  (side='right' - 1).
    #
    # The `<=` is deliberate and is NOT look-ahead: a 1m bar with
    # close_ts == T covers [T-60s, T), so it is COMPLETE at T and its regime is
    # known at T. The 1s bar with ts_event == T covers [T, T+1s) and therefore
    # begins after that 1m bar closed. This also matches the offline slicer
    # exactly -- build_completed_regimes uses
    # `left = searchsorted(index, start, side='left')`, i.e. the bar at
    # ts == start belongs to the NEW regime.
    #
    # An earlier version of this driver used side='left' - 1, which handed the
    # bar at ts == close_ts to the PREVIOUS regime. That shifted every regime
    # window one bar late (median end_time offset exactly 1.000 s), changing
    # start_price -> MFE/MAE/net_aligned_move, which the retracement ratios
    # then amplified. It produced a spurious "tracker is broken" result; the
    # defect was in this driver, not in MedianCenterTracker.
    m_close = df_1m["close_ts"].to_numpy(np.int64)
    m_reg = df_1m["regime"].to_numpy(np.int64)
    raw_ns = _ns(raw.index)
    pos = np.searchsorted(m_close, raw_ns, side="right") - 1
    bar_regime = np.where(pos >= 0, m_reg[np.clip(pos, 0, len(m_reg) - 1)], 0)

    # ---- frozen offline reference rows to compare at ----
    prep = pd.read_parquet(PREPARED, columns=["observation_time", "regime_start_ns"] + TARGETS)
    m = ((prep["observation_time"] >= COMPARE_START.value)
         & (prep["observation_time"] < COMPARE_END.value))
    ref = prep[m].reset_index(drop=True)
    print(f"frozen reference rows to compare: {len(ref):,}")
    if ref.empty:
        raise SystemExit("no reference rows in window")

    obs = ref["observation_time"].to_numpy(np.int64)
    # strict causal snap: last completed 1s bar STRICTLY before observation_time
    snap = np.searchsorted(raw_ns, obs, side="left") - 1
    if (snap < 0).any():
        raise SystemExit("observation before first bar")
    if not (raw_ns[snap] < obs).all():
        raise SystemExit("CAUSALITY VIOLATION: snapped bar not strictly before observation")

    # ---- stream the real tracker ----
    o = raw["open"].to_numpy(float); h = raw["high"].to_numpy(float)
    lo = raw["low"].to_numpy(float); c = raw["close"].to_numpy(float)
    v = raw["volume"].to_numpy(float)

    tracker = MedianCenterTracker()
    want = {}
    for j, s in enumerate(snap):
        want.setdefault(int(s), []).append(j)

    live = np.full((len(ref), len(TARGETS)), np.nan)
    n_missing_key = 0
    for i in range(len(raw_ns)):
        bar = SimpleNamespace(open=o[i], high=h[i], low=lo[i], close=c[i],
                              volume=v[i], ts_init=int(raw_ns[i]))
        tracker.update_1s(bar, int(bar_regime[i]), 1.0)
        rows = want.get(i)
        if rows:
            # touch_bar.ts_init must be the OBSERVATION instant for the
            # completed-regime slice; bar i is the last completed bar and its
            # ts_init is its own ts_event here, so pass the observation time.
            for j in rows:
                tb = SimpleNamespace(close=c[i], ts_init=int(obs[j]))
                res = tracker.calculate(int(bar_regime[i]), 1.0, tb)
                for k, feat in enumerate(TARGETS):
                    if feat not in res:
                        n_missing_key += 1
                    live[j, k] = np.nan if res.get(feat) is None else float(res[feat])
        if i % 250_000 == 0 and i:
            print(f"  {i:,}/{len(raw_ns):,} bars  ({time.time()-t0:.0f}s)")

    # ---- offline recomputation through the ORIGINAL function ----
    offline = np.full((len(ref), len(TARGETS)), np.nan)
    for j in range(len(ref)):
        feats = compute_sequence_features(int(obs[j]), float(c[snap[j]]), -1, 1.0, regimes)
        for k, feat in enumerate(TARGETS):
            val = feats.get(feat)
            offline[j, k] = np.nan if val is None else float(val)

    frozen = ref[TARGETS].to_numpy(float)

    rows = []
    for k, feat in enumerate(TARGETS):
        for label, arr in (("live_vs_frozen", live[:, k]), ("offline_vs_frozen", offline[:, k]),
                           ("live_vs_offline", live[:, k])):
            other = frozen[:, k] if label.endswith("frozen") else offline[:, k]
            both = np.isfinite(arr) & np.isfinite(other)
            d = np.abs(arr[both] - other[both])
            rows.append({
                "feature": feat, "comparison": label,
                "n_compared": int(both.sum()),
                "n_a_nan": int((~np.isfinite(arr)).sum()),
                "n_b_nan": int((~np.isfinite(other)).sum()),
                "max_abs_diff": float(d.max()) if d.size else np.nan,
                "mean_abs_diff": float(d.mean()) if d.size else np.nan,
                "p99_abs_diff": float(np.percentile(d, 99)) if d.size else np.nan,
                "n_over_1e_9": int((d > 1e-9).sum()) if d.size else 0,
                "status": ("PASS" if d.size and d.max() <= 1e-9 else
                           ("FAIL" if d.size else "NO_OVERLAP")),
            })
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "seq_feature_equivalence.csv", index=False)

    verdict = "PASS" if (out[out.comparison == "live_vs_frozen"]["status"] == "PASS").all() else "FAIL"
    (RESULTS / "seq_feature_equivalence.json").write_text(json.dumps({
        "targets": TARGETS,
        "raw_source": str(RAW_1S[2025]),
        "warmup_start": str(WARMUP_START), "compare_window": [str(COMPARE_START), str(COMPARE_END)],
        "n_raw_1s_bars": int(len(raw)), "n_completed_regimes": int(len(regimes)),
        "n_reference_rows": int(len(ref)),
        "missing_feature_keys_from_tracker": n_missing_key,
        "tolerance": 1e-9, "verdict": verdict,
        "rows": rows,
        "runtime_s": round(time.time() - t0, 1),
    }, indent=2), encoding="utf-8")

    print("\n" + out.to_string(index=False))
    print(f"\nSEQ EQUIVALENCE VERDICT: {verdict}   ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
