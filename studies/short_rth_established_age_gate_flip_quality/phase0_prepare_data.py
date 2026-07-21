"""Phase 0 -- join gate-input columns onto the enriched feature surface,
derive regime-transition labels, and build the Gate A (120s) / Gate B (240s)
/ optional 180s-bridge full-checkpoint and first-eligible-per-regime
surfaces.

Per SPEC.md's scout-pass findings:
  - Gate-input columns (`regime_age_s`, `running_mfe_atr`, `running_mae_atr`,
    `new_progress_windows`, `retained_mfe_ratio`, `confirm_flip_ns`) are
    rejoined from the already-existing pre-labeling surface files (not
    recomputed) -- exact key match verified in the scout pass.
  - `bearish_flip_within_300s` = existing `aligned` column.
  - `no_flip_before_timeout` = NOT aligned.
  - `adverse_move_1p25A_before_bearish_flip` = existing `hit_pre_alignment_stop`
    column (definitionally identical, traced in label_full_surface.py).
  - `time_to_bearish_flip_s` / `bearish_flip_within_600s` are pure arithmetic
    on `confirm_flip_ns`.
  - `post_flip_mfe_atr_{300,600}s` is the only genuinely new computation:
    a raw-1s-bar scan done ONCE PER REGIME (all checkpoints in a regime
    share the same flip time and post-flip price path), normalized by each
    row's OWN `atr_at_entry`.
  - Gate B / bridge surfaces are pure row-filters on Gate A's joined surface
    (age>=240 with identical other criteria strictly implies Gate A's own
    established condition -- proven in SPEC.md finding 4).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FEAT_STUDY = ROOT / "studies" / "ohlcv_volume_delta_price_level_features"
BACKFILL = ROOT / "studies" / "short_rth_entry_surface_backfill"
ENRICHED_RETRAIN = ROOT / "studies" / "short_rth_enriched_volume_level_retrain"
WORK, RESULTS, AUDIT = HERE / "_work", HERE / "results", HERE / "audit"
for d in (WORK, RESULTS, AUDIT):
    d.mkdir(parents=True, exist_ok=True)

for p in (ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair", ENRICHED_RETRAIN, ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from CODEX_5_X_common import NS, RAW_1S, sha256_file  # noqa: E402
from CODEX_5_X_run_established_fade import validate_raw_bars  # noqa: E402
from phase0_prepare_data import find_position_cols, one_hot_position_cols  # noqa: E402

KEY = ["regime_start_ns", "observation_time"]
ALL_YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
TRAIN_YEARS = (2021, 2022, 2023, 2024)
GATES = {"gate_a_120s": 120.0, "bridge_180s": 180.0, "gate_b_240s": 240.0}
TIMEOUT_S = 300.0
GATE_COLS = ["regime_age_s", "running_mfe_atr", "running_mae_atr",
             "new_progress_windows", "retained_mfe_ratio", "confirm_flip_ns"]


def load_gate_columns(year: int) -> pd.DataFrame:
    if year in TRAIN_YEARS:
        df = pd.read_parquet(BACKFILL / "_work" / f"surface_{year}.parquet",
                              columns=KEY + GATE_COLS)
    else:
        recon = pd.read_parquet(BACKFILL / "results" / "reconciliation_2025_2026_surface.parquet")
        df = recon[recon["year"] == year][KEY + GATE_COLS].reset_index(drop=True)
    if df.duplicated(KEY).any():
        raise RuntimeError(f"{year}: duplicate gate-source keys")
    return df


def post_flip_mfe_by_regime(year: int, regimes: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    """Once per distinct regime_start_ns: MFE (favorable-to-short, i.e. price
    DOWN) in raw points from confirm_flip_ns over fixed 300s/600s windows,
    anchored at the first raw bar open at/after confirm_flip_ns. NaN
    (unavailable, never 0) if fewer than the window's seconds of raw data
    remain after the flip."""
    ts = raw.index.view(np.int64)
    opens = raw["open"].to_numpy(float)
    lows = raw["low"].to_numpy(float)
    ts_max = int(ts[-1])

    nunique_flip = regimes.groupby("regime_start_ns")["confirm_flip_ns"].nunique()
    if (nunique_flip != 1).any():
        raise RuntimeError(
            f"confirm_flip_ns not constant within regime for {int((nunique_flip != 1).sum())} regimes")
    flips = regimes.drop_duplicates("regime_start_ns")[["regime_start_ns", "confirm_flip_ns"]]
    out_rows = []
    for row in flips.itertuples(index=False):
        flip_ts = int(row.confirm_flip_ns)
        i0 = int(np.searchsorted(ts, flip_ts, side="left"))
        if i0 >= len(ts):
            out_rows.append({"regime_start_ns": int(row.regime_start_ns),
                             "post_flip_mfe_points_300s": np.nan,
                             "post_flip_mfe_points_600s": np.nan})
            continue
        anchor = float(opens[i0])
        mfe = {}
        for w in (300, 600):
            end_ts = flip_ts + int(w * NS)
            if end_ts > ts_max:
                mfe[w] = np.nan
                continue
            # Exclusive of end_ts: a raw-bar gap straddling the boundary
            # (session close/holiday) must never pull in a bar timestamped
            # hours past the nominal window -- only bars strictly before
            # end_ts count toward "within 300s/600s of the flip."
            i1 = int(np.searchsorted(ts, end_ts, side="left"))
            if i1 <= i0:
                mfe[w] = np.nan
                continue
            window_low = float(lows[i0:i1].min())
            mfe[w] = max(0.0, anchor - window_low)
        out_rows.append({"regime_start_ns": int(row.regime_start_ns),
                         "post_flip_mfe_points_300s": mfe[300],
                         "post_flip_mfe_points_600s": mfe[600]})
    return pd.DataFrame(out_rows)


def followthrough_flag(flip_within: pd.Series, mfe_atr: pd.Series) -> pd.Series:
    """1.0/0.0/NaN, never a plain bool: if there was no flip within the
    window, followthrough is definitionally 0.0 regardless of MFE
    availability; if there WAS a flip but the post-flip MFE is unavailable
    (censored near year-end), followthrough must stay NaN -- unavailable is
    never silently coerced into 'no followthrough' (NaN >= 1.0 is False)."""
    out = np.where(mfe_atr.isna(), np.nan, (flip_within & (mfe_atr >= 1.0)).astype(float))
    out = pd.Series(out, index=flip_within.index)
    out[~flip_within] = 0.0
    return out


def build_labels(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["time_to_bearish_flip_s"] = (df["confirm_flip_ns"] - df["observation_time"]) / 1e9
    df["bearish_flip_within_300s"] = df["aligned"].astype(bool)
    df["bearish_flip_within_600s"] = df["time_to_bearish_flip_s"] <= 600.0
    df["no_flip_before_timeout"] = ~df["bearish_flip_within_300s"]
    df["adverse_move_1p25A_before_bearish_flip"] = df["hit_pre_alignment_stop"].astype(bool)

    df["post_flip_mfe_atr_300s"] = df["post_flip_mfe_points_300s"] / df["atr_at_entry"]
    df["post_flip_mfe_atr_600s"] = df["post_flip_mfe_points_600s"] / df["atr_at_entry"]

    df["bearish_flip_within_300s_and_followthrough_1A"] = followthrough_flag(
        df["bearish_flip_within_300s"], df["post_flip_mfe_atr_300s"])
    df["bearish_flip_within_600s_and_followthrough_1A"] = followthrough_flag(
        df["bearish_flip_within_600s"], df["post_flip_mfe_atr_600s"])
    # NaN (unavailable, censored) must stay distinguishable from a confirmed
    # "flipped but no followthrough" -- never silently collapsed to False.
    followthrough_600 = df["bearish_flip_within_600s_and_followthrough_1A"]
    df["flip_but_no_followthrough"] = np.where(
        df["bearish_flip_within_600s"] & followthrough_600.isna(), np.nan,
        (df["bearish_flip_within_600s"] & (followthrough_600 == 0.0)).astype(float))
    return df


def run_year(year: int) -> dict:
    t0 = time.time()
    full = pd.read_parquet(FEAT_STUDY / "_work" / f"full_{year}.parquet")
    gate_cols = load_gate_columns(year)

    n_before = len(full)
    merged = full.merge(gate_cols, on=KEY, how="left", validate="one_to_one")
    if len(merged) != n_before:
        raise RuntimeError(f"{year}: join changed row count {n_before} -> {len(merged)}")
    join_rate = float(merged["regime_age_s"].notna().mean())
    if join_rate != 1.0:
        raise RuntimeError(f"{year}: gate-column join rate {join_rate} != 1.0")

    raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close", "volume"])
    validate_raw_bars(raw)
    regime_flips = merged[["regime_start_ns", "confirm_flip_ns"]]
    post_flip = post_flip_mfe_by_regime(year, regime_flips, raw)
    merged = merged.merge(post_flip, on="regime_start_ns", how="left", validate="many_to_one")
    if len(merged) != n_before:
        raise RuntimeError(f"{year}: post-flip join changed row count")

    labeled = build_labels(merged)
    position_cols = find_position_cols(labeled)
    labeled, dummy_cols = one_hot_position_cols(labeled, position_cols)

    out_path = WORK / f"prepared_{year}.parquet"
    labeled.to_parquet(out_path, index=False, compression="zstd")

    return {
        "year": year, "rows": len(labeled), "join_rate_gate_cols": join_rate,
        "distinct_regimes": int(labeled["regime_start_ns"].nunique()),
        "post_flip_mfe_300s_unavailable": int(labeled["post_flip_mfe_atr_300s"].isna().sum()),
        "post_flip_mfe_600s_unavailable": int(labeled["post_flip_mfe_atr_600s"].isna().sum()),
        "n_position_categorical_cols": len(position_cols), "n_position_dummy_cols": len(dummy_cols),
        "runtime_s": round(time.time() - t0, 1),
    }


def build_gate_surfaces() -> dict:
    """Full-checkpoint + first-eligible-per-regime surfaces per gate, all
    years, written once feature_sets.json-compatible F0-F3 lists are
    resolved (reused verbatim from the enriched retrain study)."""
    feature_sets = json.loads((ENRICHED_RETRAIN / "_work" / "feature_sets.json").read_text(encoding="utf-8"))
    (WORK / "feature_sets.json").write_text(json.dumps(feature_sets, indent=2), encoding="utf-8")

    summary = {}
    for gate_name, age_min in GATES.items():
        for year in ALL_YEARS:
            df = pd.read_parquet(WORK / f"prepared_{year}.parquet")
            full_gate = df[df["regime_age_s"] >= age_min].reset_index(drop=True)
            first_elig = (full_gate.sort_values(["regime_start_ns", "observation_time"], kind="stable")
                         .groupby("regime_start_ns", as_index=False, sort=False).first())
            full_gate.to_parquet(WORK / f"full_{gate_name}_{year}.parquet", index=False, compression="zstd")
            first_elig.to_parquet(WORK / f"first_eligible_{gate_name}_{year}.parquet", index=False, compression="zstd")
            summary[(gate_name, year)] = {
                "full_rows": len(full_gate), "full_regimes": int(full_gate["regime_start_ns"].nunique()),
                "first_eligible_rows": len(first_elig),
            }
    return summary


def main() -> None:
    t0 = time.time()
    year_reports = {y: run_year(y) for y in ALL_YEARS}
    surface_summary = build_gate_surfaces()

    manifest = {
        "gates": GATES, "timeout_s": TIMEOUT_S,
        "year_reports": year_reports,
        "surface_summary": {f"{g}|{y}": v for (g, y), v in surface_summary.items()},
        "runtime_s": round(time.time() - t0, 1),
        "generator_sha256": sha256_file(Path(__file__).resolve()),
    }
    (RESULTS / "phase0_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(json.dumps(year_reports, indent=2, default=str))
    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
