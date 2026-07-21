"""Phase 2 + Phase 3 (part B) - assemble prepared_long_{year}.

For each year:
  1. load attached_long_{year} (surface keys/metadata + 56 ohlcv+price features);
  2. join the 44 center/slope/alignment features from the ATLAS on
     (regime_start_ns, observation_time) - already regime-direction-relative,
     one-to-one (observation_time unique within a regime);
  3. build the mirrored primary label
        bullish_regime_flip_within_300s = (confirm_flip_ns - observation_time)/1e9 <= 300
     plus by-year diagnostics (600s rate, median time-to-flip);
  4. select exactly the frozen top-100 features + keys + label + metadata;
  5. verify all 100 present; report null rates; write prepared_long_{year}.parquet.

Pure arithmetic label - independent of stop/PnL/timeout/entry/exit. Censoring:
confirm_flip_ns is always defined for a completed regime, so 0 primary-label
censored rows expected; any unobservable-horizon row is dropped and counted.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
ROOT = STUDY.parents[1]
WORK, RESULTS = STUDY / "_work", STUDY / "results"
sys.path.insert(0, str(ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"))
from CODEX_5_X_common import sha256_file  # noqa: E402

# Import the frozen atlas path map + feature list.
sys.path.insert(0, str(HERE))
from build_surface_long import ATLAS_PATHS  # noqa: E402

KEY = ["regime_start_ns", "observation_time"]
MANIFEST = json.load(open(STUDY / "results" / "top100_feature_manifest.json"))
TOP100 = MANIFEST["feature_names_in_order"]
CENTER_FEATS = [f for f in TOP100
                if f in set(pd.read_csv(STUDY / "results" / "top100_feature_list.csv")
                            .query("family=='regime_median_center_slope_alignment'")["feature_name"])]


def run_year(year: int) -> dict:
    t0 = time.time()
    attached = pd.read_parquet(WORK / f"attached_long_{year}.parquet")
    n0 = len(attached)

    # Join the 44 center feats from the atlas (keys + those columns only).
    atlas = pd.read_parquet(ATLAS_PATHS[year], columns=KEY + CENTER_FEATS)
    # Fail loud on duplicate keys rather than silently resolving them (W1).
    ndup = int(atlas.duplicated(KEY).sum())
    if ndup:
        raise RuntimeError(f"{year}: atlas has {ndup} duplicate (regime_start_ns, observation_time) keys")
    merged = attached.merge(atlas, on=KEY, how="left", validate="one_to_one")
    if len(merged) != n0:
        raise RuntimeError(f"{year}: atlas center-feat join changed row count {n0}->{len(merged)}")
    center_join_rate = float(merged[CENTER_FEATS[0]].notna().mean())

    # Label (pure arithmetic).
    merged["time_to_bullish_flip_s"] = (merged["confirm_flip_ns"] - merged["observation_time"]) / 1e9
    horizon_observable = merged["confirm_flip_ns"].notna() & (merged["time_to_bullish_flip_s"] >= 0)
    censored = int((~horizon_observable).sum())
    merged = merged[horizon_observable].reset_index(drop=True)
    merged["bullish_regime_flip_within_300s"] = (merged["time_to_bullish_flip_s"] <= 300.0).astype(int)
    merged["bullish_flip_within_600s"] = (merged["time_to_bullish_flip_s"] <= 600.0).astype(int)

    missing = [f for f in TOP100 if f not in merged.columns]
    if missing:
        raise RuntimeError(f"{year}: LONG_SURFACE_BUILD_FAILED - top100 features absent after attach: {missing[:10]}")

    meta = ["year", "regime_start_ns", "observation_time", "regime_start_time",
            "confirm_flip_ns", "prevailing_direction", "entry_direction",
            "atr_at_entry", "regime_age_s", "fill_ts", "fill_px", "session",
            "time_to_bullish_flip_s", "bullish_flip_within_600s"]
    keep = meta + TOP100 + ["bullish_regime_flip_within_300s"]
    out = merged[keep].copy()
    out_path = WORK / f"prepared_long_{year}.parquet"
    out.to_parquet(out_path, index=False, compression="zstd")

    pos = int(out["bullish_regime_flip_within_300s"].sum())
    nregimes = int(out["regime_start_ns"].nunique())
    null_rates = {f: float(out[f].isna().mean()) for f in TOP100}
    return {
        "year": year, "rows": len(out), "censored_rows": censored,
        "center_join_rate": center_join_rate,
        "distinct_regimes": nregimes,
        "mean_rows_per_regime": round(len(out) / nregimes, 3) if nregimes else 0,
        "median_rows_per_regime": float(out.groupby("regime_start_ns").size().median()) if nregimes else 0,
        "positive_count": pos, "positive_rate": round(pos / len(out), 5) if len(out) else 0,
        "within_600s_rate": round(float(out["bullish_flip_within_600s"].mean()), 5) if len(out) else 0,
        "median_time_to_bullish_flip_s": round(float(out["time_to_bullish_flip_s"].median()), 2) if len(out) else 0,
        "max_feature_null_rate": round(max(null_rates.values()), 5),
        "features_with_nulls": {f: round(r, 5) for f, r in null_rates.items() if r > 0},
        "output_path": str(out_path), "output_sha256": sha256_file(out_path),
        "runtime_s": round(time.time() - t0, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+",
                    default=[2021, 2022, 2023, 2024, 2025, 2026])
    args = ap.parse_args()
    reports = {y: run_year(y) for y in args.years}
    for y, r in reports.items():
        print(f"[{y}] rows={r['rows']:,} regimes={r['distinct_regimes']:,} "
              f"pos_rate={r['positive_rate']} censored={r['censored_rows']} "
              f"max_null={r['max_feature_null_rate']} center_join={r['center_join_rate']}")
    (RESULTS / "phase2_3_assemble_manifest.json").write_text(
        json.dumps({"generator_sha256": sha256_file(Path(__file__).resolve()),
                    "n_center_feats_joined": len(CENTER_FEATS), "years": reports},
                   indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
