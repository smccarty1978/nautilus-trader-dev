"""Pinpoint WHY MedianCenterTracker's seq_* features diverge from the offline
producer the frozen model was trained on.

verify_seq_features.py established:
  offline_vs_frozen  max_abs_diff = 0.0   (offline reproduction is bit-exact)
  live_vs_offline    FAIL on all three targets

Since the seq_* FORMULAS are line-for-line identical between the two files, the
divergence must be in the completed-regime RECORDS each side feeds them. This
script compares those records directly.
"""
from __future__ import annotations

import json
import sys
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
from features.trackers.median_center import MedianCenterTracker  # noqa: E402
from reproduce_regimes import aggregate_and_run_regimes  # noqa: E402

WARMUP_START = pd.Timestamp("2025-02-20", tz="UTC")
END = pd.Timestamp("2025-03-11", tz="UTC")


def _ns(index):
    if isinstance(index, pd.DatetimeIndex):
        return index.tz_convert("UTC").asi8 if index.tz is not None else index.asi8
    return np.asarray(index, dtype=np.int64)


def main() -> None:
    raw = pd.read_parquet(RAW_1S[2025])
    ins = _ns(raw.index)
    raw = raw.iloc[(ins >= WARMUP_START.value) & (ins < END.value)]
    raw_ns = _ns(raw.index)

    df_1m = aggregate_and_run_regimes(raw, "1m")
    regimes = build_completed_regimes(df_1m, raw)

    reg_vals = df_1m["regime"].to_numpy(np.int64)
    n_zero = int((reg_vals == 0).sum())
    print(f"1m bars={len(df_1m):,}  regime==0 bars={n_zero:,} "
          f"({100*n_zero/len(df_1m):.2f}%)  offline completed regimes={len(regimes):,}")

    m_close = df_1m["close_ts"].to_numpy(np.int64)
    pos = np.searchsorted(m_close, raw_ns, side="left") - 1
    bar_regime = np.where(pos >= 0, reg_vals[np.clip(pos, 0, len(reg_vals) - 1)], 0)
    print(f"1s bars with regime==0: {int((bar_regime==0).sum()):,} / {len(bar_regime):,}")

    # ---- stream the tracker, capture its own completed-regime records ----
    o = raw["open"].to_numpy(float); h = raw["high"].to_numpy(float)
    lo = raw["low"].to_numpy(float); c = raw["close"].to_numpy(float)
    v = raw["volume"].to_numpy(float)
    tr = MedianCenterTracker()
    for i in range(len(raw_ns)):
        tr.update_1s(SimpleNamespace(open=o[i], high=h[i], low=lo[i], close=c[i],
                                     volume=v[i], ts_init=int(raw_ns[i])),
                     int(bar_regime[i]), 1.0)
    live = pd.DataFrame(list(tr.completed_regimes))
    print(f"live completed regimes={len(live):,}")

    off = regimes.copy()
    for col in ("start_time", "end_time"):
        if col in off.columns:
            off[col] = off[col].astype(np.int64)

    # ---- align on end_time and compare the record fields ----
    cols = ["direction", "start_price", "MFE", "MAE", "net_aligned_move"]
    merged = off.merge(live, on="end_time", how="inner", suffixes=("_off", "_live"))
    print(f"\nrecords matched on end_time: {len(merged):,} "
          f"(offline {len(off):,}, live {len(live):,})")

    rows = []
    for col in cols:
        a, b = f"{col}_off", f"{col}_live"
        if a not in merged or b not in merged:
            continue
        d = np.abs(merged[a].astype(float) - merged[b].astype(float))
        rows.append({"field": col, "n": int(len(d)),
                     "n_exact": int((d <= 1e-9).sum()),
                     "pct_exact": round(100 * float((d <= 1e-9).mean()), 2),
                     "max_abs_diff": float(d.max()), "mean_abs_diff": float(d.mean())})
    rec = pd.DataFrame(rows)
    print("\nper-field record comparison (matched on end_time):")
    print(rec.to_string(index=False))

    # ---- boundary comparison ----
    off_ends = set(off["end_time"].tolist())
    live_ends = set(live["end_time"].tolist()) if len(live) else set()
    boundary = {
        "offline_regimes": int(len(off)), "live_regimes": int(len(live)),
        "shared_end_times": int(len(off_ends & live_ends)),
        "offline_only_end_times": int(len(off_ends - live_ends)),
        "live_only_end_times": int(len(live_ends - off_ends)),
    }
    print("\nboundary:", json.dumps(boundary))

    # ---- start_time comparison for matched records ----
    if "start_time_off" in merged and "start_time_live" in merged:
        sd = (merged["start_time_off"].astype(np.int64)
              - merged["start_time_live"].astype(np.int64))
        boundary["start_time_diff_ns_median"] = float(np.median(sd))
        boundary["start_time_diff_ns_max_abs"] = float(np.abs(sd).max())
        boundary["start_time_exact_pct"] = round(100 * float((sd == 0).mean()), 2)
        print(f"start_time: exact={boundary['start_time_exact_pct']}% "
              f"median_diff={boundary['start_time_diff_ns_median']/1e9:.3f}s "
              f"max_abs={boundary['start_time_diff_ns_max_abs']/1e9:.3f}s")

    rec.to_csv(RESULTS / "seq_divergence_record_fields.csv", index=False)
    (RESULTS / "seq_divergence_diagnosis.json").write_text(json.dumps({
        "window": [str(WARMUP_START), str(END)],
        "n_1m_bars": int(len(df_1m)), "n_1m_regime_zero": n_zero,
        "pct_1m_regime_zero": round(100 * n_zero / len(df_1m), 4),
        "n_1s_regime_zero": int((bar_regime == 0).sum()),
        "boundary": boundary,
        "record_fields": rows,
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
