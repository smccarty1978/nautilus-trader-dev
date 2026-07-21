"""Rebuild repaired weakness checkpoints from raw causal bars, year by year.

The repaired local path state, every dependent weakness label, and every W4
center/sequence input are rebuilt from raw 1s bars and a fresh canonical
RegimeEngine. The immutable legacy atlas is used only to verify checkpoint
identity; no legacy model-input value is copied into the repaired atlas.
"""
from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
UPSTREAM = ROOT / "studies" / "regime_sequence_chop_context"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(UPSTREAM))

from CODEX_5_X_common import (  # noqa: E402
    AUDIT, LEGACY_ATLAS, NS, RAW_1S, REPAIRED_ATLAS, RESULTS,
    require_frozen_pre_2026_contract, sha256_file, write_json, year_atlas_path,
)
from CODEX_5_X_build_regime_history import build_completed_regimes  # noqa: E402
from build_median_centers import build_median_centers_df  # noqa: E402
from build_regime_sequence import compute_sequence_features  # noqa: E402
from build_weakness_atlas import build_weakness_checkpoints_for_regime  # noqa: E402
from reproduce_regimes import aggregate_and_run_regimes  # noqa: E402
from train_weakness_model import CENTER_FEATS, SEQUENCE_FEATS  # noqa: E402


REBUILT_COLUMNS = [
    "observation_time", "direction", "regime_age", "regime_start_ns",
    "flip_decision_ns", "entry_ts_event", "entry_open", "regime_end_ns",
    "atr_at_entry", "atr_at_checkpoint",
    "current_pnl", "current_mfe", "current_mae", "running_mfe",
    "running_mae", "giveback", "opp_flip_in_30s", "opp_flip_in_60s",
    "opp_flip_in_120s", "opp_flip_in_300s",
    "no_new_fav_before_025_giveback", "no_new_fav_before_050_giveback",
    "recovered_30s", "recovered_60s", "recovered_120s",
    "current_mfe_is_final", "additional_mfe_remaining",
    "max_giveback_before_next_fav_extreme", "terminal_deterioration",
    "state_class",
]


def year_bounds(year: int) -> tuple[int, int]:
    start = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    end = pd.Timestamp(f"{year + 1}-01-01", tz="UTC").value
    return start, end


def period_for_year(year: int) -> str:
    if year <= 2024:
        return "train"
    if year == 2025:
        return "validation"
    if year == 2026:
        return "test"
    raise ValueError(year)


def attach_last_available_feature_rows(
    checkpoints: pd.DataFrame, feature_rows: pd.DataFrame,
) -> pd.DataFrame:
    out = pd.merge_asof(
        checkpoints.sort_values("observation_time", kind="stable"),
        feature_rows.sort_values("feature_bar_ts_event", kind="stable"),
        left_on="observation_time", right_on="feature_bar_ts_event",
        direction="backward", allow_exact_matches=False,
    )
    if out["feature_bar_ts_event"].isna().any():
        raise RuntimeError("checkpoint lacks a completed causal feature bar")
    if not (out["feature_bar_ts_event"] < out["observation_time"]).all():
        raise RuntimeError("W4 context includes an unavailable checkpoint bar")
    return out


def compute_sequence_features_batched(
    checkpoints: pd.DataFrame, regimes: pd.DataFrame,
) -> pd.DataFrame:
    """Exact W4 sequence features with invariant work cached per regime."""
    n = len(checkpoints)
    values = {col: np.full(n, np.nan, dtype=float) for col in SEQUENCE_FEATS}
    end_times = regimes["end_time"].to_numpy(dtype=np.int64)
    dynamic_names = {
        "efficiency", "disp_atr", "range_atr", "position_pct",
        "dist_to_high_atr", "dist_to_low_atr",
        "center_migration_slope_atr",
    }

    for _, positions in checkpoints.groupby("regime_start_ns", sort=False).indices.items():
        pos = np.asarray(positions, dtype=np.int64)
        group = checkpoints.iloc[pos]
        first = group.iloc[0]
        last = group.iloc[-1]
        completed = int(np.searchsorted(
            end_times, int(first["observation_time"]), side="right"
        ))
        completed_last = int(np.searchsorted(
            end_times, int(last["observation_time"]), side="right"
        ))
        if completed != completed_last:
            raise RuntimeError("completed-regime set changed inside active regime")
        base = compute_sequence_features(
            int(first["observation_time"]), float(first["close"]),
            int(first["direction"]), float(first["atr"]), regimes,
        )
        for col in SEQUENCE_FEATS:
            suffix = col.split("_", 2)[-1]
            if col in base and suffix not in dynamic_names:
                values[col][pos] = float(base[col])

        price = group["close"].to_numpy(dtype=float)
        atr = group["atr"].to_numpy(dtype=float)
        direction = int(first["direction"])
        if not np.all(group["direction"].to_numpy(dtype=int) == direction):
            raise RuntimeError("direction changed inside exact regime group")
        for k in (3, 5, 8, 12):
            if completed < k:
                continue
            sub = regimes.iloc[completed - k:completed]
            seq_start = float(sub.iloc[0]["start_price"])
            total_abs_net = float(np.abs(
                sub["net_aligned_move"].to_numpy(dtype=float)
            ).sum())
            sub_direction = sub["direction"].to_numpy(dtype=int)
            sub_start = sub["start_price"].to_numpy(dtype=float)
            sub_mfe = sub["MFE"].to_numpy(dtype=float)
            sub_mae = sub["MAE"].to_numpy(dtype=float)
            highs = np.where(sub_direction == 1,
                             sub_start + sub_mfe, sub_start + sub_mae)
            lows = np.where(sub_direction == 1,
                            sub_start - sub_mae, sub_start - sub_mfe)
            seq_high, seq_low = float(highs.max()), float(lows.min())
            seq_range = seq_high - seq_low
            centers = sub["regime_center"].to_numpy(dtype=float)
            mean_center = float(centers.mean())
            sum_x = k * (k - 1) / 2.0
            ss_xx = k * (k ** 2 - 1) / 12.0
            sum_xy = float((np.arange(k) * centers).sum())
            migration_slope = (sum_xy - sum_x * mean_center) / ss_xx
            prefix = f"seq_{k}r_"
            values[prefix + "efficiency"][pos] = (
                np.abs(price - seq_start) / (total_abs_net + 1e-8)
            )
            values[prefix + "disp_atr"][pos] = (
                direction * (price - seq_start) / (atr + 1e-8)
            )
            values[prefix + "range_atr"][pos] = seq_range / (atr + 1e-8)
            position = ((price - seq_low) / seq_range
                        if seq_range > 1e-8 else np.full(len(pos), 0.5))
            values[prefix + "position_pct"][pos] = (
                direction * (position - 0.5) + 0.5
            )
            values[prefix + "dist_to_high_atr"][pos] = (
                direction * (seq_high - price) / (atr + 1e-8)
            )
            values[prefix + "dist_to_low_atr"][pos] = (
                direction * (price - seq_low) / (atr + 1e-8)
            )
            values[prefix + "center_migration_slope_atr"][pos] = (
                migration_slope / (atr + 1e-8)
            )
    return pd.DataFrame(values, index=checkpoints.index)


def compute_activity_features_batched(
    checkpoints: pd.DataFrame, regimes: pd.DataFrame,
) -> pd.DataFrame:
    """Exact causal activity features without per-checkpoint dictionaries."""
    ts = checkpoints["observation_time"].to_numpy(dtype=np.int64)
    end_times = regimes["end_time"].to_numpy(dtype=np.int64)
    durations = regimes["duration"].to_numpy(dtype=float)
    right = np.searchsorted(end_times, ts, side="right")
    data: dict[str, np.ndarray] = {}
    left30 = None
    for window_min in (5, 15, 30, 60, 120):
        left = np.searchsorted(
            end_times, ts - window_min * 60 * NS, side="right"
        )
        count = right - left
        data[f"activity_regime_count_{window_min}m"] = count.astype(float)
        if window_min == 30:
            left30 = left
            data["activity_flip_count_30m"] = count.astype(float)
    if left30 is None:
        raise RuntimeError("30-minute activity window missing")

    pairs, inverse = np.unique(
        np.column_stack([left30, right]), axis=0, return_inverse=True
    )
    median30_unique = np.full(len(pairs), np.nan, dtype=float)
    for i, (left, stop) in enumerate(pairs):
        if stop > left:
            median30_unique[i] = float(np.median(durations[left:stop]))
    data["activity_duration_median_30m"] = median30_unique[inverse]

    unique_right, right_inverse = np.unique(right, return_inverse=True)
    for count in (3, 5, 10):
        medians = np.full(len(unique_right), np.nan, dtype=float)
        for i, stop in enumerate(unique_right):
            if stop >= count:
                medians[i] = float(np.median(durations[stop - count:stop]))
        data[f"duration_median_last_{count}"] = medians[right_inverse]
    data["duration_ratio_3_vs_10"] = (
        data["duration_median_last_3"]
        / (data["duration_median_last_10"] + 1e-8)
    )
    data["duration_ratio_5_vs_10"] = (
        data["duration_median_last_5"]
        / (data["duration_median_last_10"] + 1e-8)
    )
    divisor = np.maximum(data["activity_regime_count_30m"], 1.0)
    data["cross_family_spread_vs_reg_count"] = (
        checkpoints["center_spread_5m_30m"].to_numpy(dtype=float) / divisor
    )
    data["cross_family_slope_vs_reg_count"] = (
        checkpoints["slope_30m_15m_aligned_atr"].to_numpy(dtype=float) / divisor
    )
    return pd.DataFrame(data, index=checkpoints.index)


def attach_causal_w4_context(
    raw: pd.DataFrame,
    df_1m: pd.DataFrame,
    regimes: pd.DataFrame,
    checkpoints: pd.DataFrame,
) -> pd.DataFrame:
    """Rebuild W4 context and attach only rows available before checkpoint."""
    raw_work = raw.copy()
    raw_work["ts_ns"] = raw_work.index.view(np.int64)
    raw_work = raw_work.sort_values("ts_ns", kind="stable")
    minute = df_1m.sort_values("close_ts", kind="stable")
    merged = pd.merge_asof(
        raw_work,
        minute[["close_ts", "atr", "regime"]],
        left_on="ts_ns", right_on="close_ts", direction="backward",
        allow_exact_matches=True,
    )
    merged.index = pd.to_datetime(merged["ts_ns"], unit="ns", utc=True)
    merged.index.name = "ts_event"
    features = build_median_centers_df(
        merged.drop(columns=["ts_ns", "close_ts"])
    )
    median_center_features = [c for c in CENTER_FEATS if c in features.columns]
    feature_rows = features[
        ["close", "atr", "regime", *median_center_features]
    ].copy()
    feature_rows["feature_bar_ts_event"] = feature_rows.index.view(np.int64)
    feature_rows = feature_rows.reset_index(drop=True).sort_values(
        "feature_bar_ts_event", kind="stable"
    )

    out = attach_last_available_feature_rows(checkpoints, feature_rows)
    if not (out["regime"].astype(int) == out["direction"].astype(int)).all():
        raise RuntimeError("causal context regime disagrees with checkpoint direction")
    out["atr_at_checkpoint"] = out["atr"].astype(float)
    atr_values = out[["atr_at_entry", "atr_at_checkpoint"]].to_numpy(dtype=float)
    if not np.isfinite(atr_values).all():
        raise RuntimeError("entry/checkpoint ATR must be finite")
    if not ((out["atr_at_entry"] > 0) & (out["atr_at_checkpoint"] > 0)).all():
        raise RuntimeError("entry/checkpoint ATR must be positive")
    if not np.array_equal(
        out["atr"].to_numpy(dtype=float),
        out["atr_at_checkpoint"].to_numpy(dtype=float),
    ):
        raise RuntimeError("legacy atr alias differs from atr_at_checkpoint")

    activity = compute_activity_features_batched(out, regimes)
    out = pd.concat([out, activity], axis=1)

    seq = compute_sequence_features_batched(out, regimes)
    out = pd.concat([out, seq], axis=1)
    missing = [c for c in CENTER_FEATS + SEQUENCE_FEATS if c not in out]
    if missing:
        raise RuntimeError(f"missing rebuilt W4 context columns: {missing}")
    return out


def build_raw_checkpoints(year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_parquet(RAW_1S[year])
    if not raw.index.is_monotonic_increasing or not raw.index.is_unique:
        raise RuntimeError(f"{year} raw 1s index must be increasing and unique")
    df_1m = aggregate_and_run_regimes(raw, "1m")
    regimes = build_completed_regimes(df_1m, raw)
    raw_ns = raw.copy()
    raw_ns.index = raw_ns.index.view(np.int64)
    records: list[dict] = []
    contracts: list[dict] = []
    step_s = 30 if year <= 2024 else 5

    atr_by_flip = dict(zip(
        df_1m["close_ts"].astype(np.int64), df_1m["atr"].astype(float)
    ))
    for reg in regimes.itertuples(index=False):
        direction = int(reg.direction)
        start = int(reg.start_time)
        end = int(reg.end_time)
        atr = float(atr_by_flip.get(start, np.nan))
        if not np.isfinite(atr) or atr <= 0:
            continue
        raw_index = raw_ns.index.to_numpy(dtype=np.int64, copy=False)
        entry_pos = int(np.searchsorted(raw_index, start, side="left"))
        if entry_pos >= len(raw_ns) or int(raw_index[entry_pos]) >= end:
            continue
        entry_ts = int(raw_index[entry_pos])
        entry_open = float(raw_ns.iloc[entry_pos]["open"])
        path = raw_ns.loc[entry_ts:end + 300 * NS]
        if int(path.index[0]) != entry_ts:
            raise RuntimeError("anchor timestamp must equal first path timestamp")
        contracts.append({
            "year": year, "regime_start_ns": start,
            "regime_end_ns": end, "direction": direction,
            "entry_ts_event": entry_ts, "entry_open": entry_open,
        })
        rows = build_weakness_checkpoints_for_regime(
            direction=direction,
            flip_ts=start,
            flip_close=entry_open,
            opp_flip_ts=end,
            atr_val=atr,
            df_1s_regime=path,
            df_regimes=regimes,
            step_s=step_s,
        )
        for row in rows:
            row["regime_start_ns"] = start
        records.extend(rows)
    out = pd.DataFrame(records)
    out = out.sort_values(["observation_time", "direction"], kind="stable")
    assert not out.duplicated(["observation_time", "direction"]).any()
    out = attach_causal_w4_context(raw, df_1m, regimes, out)
    del raw, raw_ns, df_1m, regimes
    gc.collect()
    contract = pd.DataFrame(contracts).drop_duplicates(
        ["year", "regime_start_ns", "direction"]
    )
    return out, contract


def load_legacy_year(year: int) -> pd.DataFrame:
    start, end = year_bounds(year)
    return pd.read_parquet(
        LEGACY_ATLAS,
        filters=[("observation_time", ">=", start),
                 ("observation_time", "<", end)],
    )


def add_legacy_regime_key(legacy: pd.DataFrame, year: int) -> pd.DataFrame:
    legacy = legacy.copy()
    age_ns = legacy["regime_age"].astype(float).to_numpy() * NS
    rounded_age_ns = np.rint(age_ns).astype(np.int64)
    if not np.all(np.abs(age_ns - rounded_age_ns) <= 1.0):
        raise RuntimeError("legacy regime_age is not integral to nanosecond tolerance")
    legacy["regime_start_ns"] = (
        legacy["observation_time"].astype(np.int64) - rounded_age_ns
    )
    legacy["year"] = year
    return legacy


def classify_noncausal_legacy_only(legacy_only: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    required = ["observation_time", "regime_end_ns", "entry_ts_event"]
    if legacy_only[required].isna().any().any():
        raise RuntimeError("legacy-only key lacks a causal regime contract")
    endpoint = legacy_only["observation_time"] == legacy_only["regime_end_ns"]
    no_path = legacy_only["observation_time"] <= legacy_only["entry_ts_event"]
    if (endpoint & no_path).any():
        raise RuntimeError("legacy-only removal classes overlap")
    if not (endpoint | no_path).all():
        raise RuntimeError("legacy-only keys include an unexplained causal checkpoint")
    return endpoint, no_path


def parity_and_merge(year: int, rebuilt: pd.DataFrame,
                     legacy: pd.DataFrame,
                     contracts: pd.DataFrame) -> pd.DataFrame:
    legacy = add_legacy_regime_key(legacy, year)
    rebuilt["year"] = year
    keys = ["year", "regime_start_ns", "observation_time", "direction"]
    legacy = legacy.sort_values(keys, kind="stable")
    assert not legacy.duplicated(keys).any(), "legacy checkpoint keys duplicate"
    rk = pd.MultiIndex.from_frame(rebuilt[keys])
    lk = pd.MultiIndex.from_frame(legacy[keys])
    missing_rebuilt = int((~lk.isin(rk)).sum())
    missing_legacy = int((~rk.isin(lk)).sum())
    if missing_legacy:
        raise RuntimeError(
            f"fresh rebuild contains {missing_legacy} keys absent from legacy"
        )
    legacy_only = legacy.loc[~lk.isin(rk), keys].merge(
        contracts[["year", "regime_start_ns", "direction", "regime_end_ns",
                   "entry_ts_event"]],
        on=["year", "regime_start_ns", "direction"], how="left",
        validate="many_to_one",
    )
    endpoint_only, no_path_available = classify_noncausal_legacy_only(legacy_only)

    age_check = rebuilt[keys + ["regime_age"]].merge(
        legacy[keys + ["regime_age"]].rename(
            columns={"regime_age": "legacy_regime_age"}
        ),
        on=keys, how="left", validate="one_to_one",
    )
    if age_check["legacy_regime_age"].isna().any():
        raise RuntimeError("rebuilt checkpoint missing from legacy parity frame")
    if not np.allclose(age_check["regime_age"], age_check["legacy_regime_age"],
                       rtol=0.0, atol=1e-9):
        raise RuntimeError("legacy and rebuilt regime ages differ")
    out = rebuilt.copy()
    out["period"] = period_for_year(year)
    out["repair_source"] = "CODEX_5_X_all_w4_inputs_rebuilt_raw_half_open"
    out["year"] = year
    out = out.sort_values(["regime_start_ns", "observation_time"], kind="stable")

    if not set(out["direction"].dropna().unique()) <= {-1, 1}:
        raise RuntimeError("invalid direction in repaired atlas")
    if out["direction"].isna().any():
        raise RuntimeError("null direction in repaired atlas")
    if not (out["entry_ts_event"] >= out["flip_decision_ns"]).all():
        raise RuntimeError("entry precedes flip decision")
    if not (out["observation_time"] < out["regime_end_ns"]).all():
        raise RuntimeError("non-causal endpoint checkpoint survived")

    numeric = out[["current_mfe", "current_mae", "running_mfe", "running_mae"]]
    negative = int((numeric < -1e-12).sum().sum())
    mono_mfe = int((out.groupby("regime_start_ns", sort=False)["running_mfe"]
                    .diff().fillna(0) < -1e-12).sum())
    mono_mae = int((out.groupby("regime_start_ns", sort=False)["running_mae"]
                    .diff().fillna(0) < -1e-12).sum())
    assert negative == mono_mfe == mono_mae == 0
    assert np.allclose(out["current_mfe"], out["running_mfe"])
    assert np.allclose(out["current_mae"], out["running_mae"])

    audit = {
        "year": year,
        "legacy_rows": len(legacy),
        "rebuilt_rows": len(rebuilt),
        "output_rows": len(out),
        "legacy_only_noncausal_keys_removed": missing_rebuilt,
        "legacy_only_exact_flip_endpoints_removed": int(endpoint_only.sum()),
        "legacy_only_no_causal_path_available_removed": int(no_path_available.sum()),
        "rebuilt_only_keys": missing_legacy,
        "negative_excursion_cells": negative,
        "running_mfe_monotonicity_violations": mono_mfe,
        "running_mae_monotonicity_violations": mono_mae,
        "legacy_atlas_sha256": sha256_file(LEGACY_ATLAS),
        "raw_sha256": sha256_file(RAW_1S[year]),
        "context_source": "raw causal last ts_event strictly before checkpoint",
        "excursion_denominator": "atr_at_entry",
        "legacy_atr_alias": "atr_at_checkpoint",
    }
    write_json(AUDIT / f"CODEX_5_X_atlas_rebuild_{year}.json", audit)
    return out


def build_year(year: int, force: bool) -> None:
    out_path = year_atlas_path(year)
    if out_path.exists() and not force:
        print(f"{out_path.name} exists; use --force to rebuild")
        return
    t0 = time.time()
    print(f"[{year}] rebuilding local path state from raw bars...")
    rebuilt, contracts = build_raw_checkpoints(year)
    print(f"[{year}] {len(rebuilt):,} raw checkpoints; loading legacy context...")
    legacy = load_legacy_year(year)
    out = parity_and_merge(year, rebuilt, legacy, contracts)
    out.to_parquet(out_path, index=False, compression="zstd")
    print(f"[{year}] wrote {len(out):,} rows in {time.time() - t0:.1f}s")


def combine(years: list[int]) -> None:
    missing = [y for y in years if not year_atlas_path(y).exists()]
    assert not missing, f"missing repaired year atlases: {missing}"
    writer = None
    rows = 0
    try:
        for year in years:
            table = pq.read_table(year_atlas_path(year))
            if writer is None:
                writer = pq.ParquetWriter(REPAIRED_ATLAS, table.schema,
                                          compression="zstd")
            writer.write_table(table)
            rows += table.num_rows
    finally:
        if writer is not None:
            writer.close()
    write_json(AUDIT / "CODEX_5_X_combined_atlas.json", {
        "years": years,
        "rows": rows,
        "path": str(REPAIRED_ATLAS),
        "sha256": sha256_file(REPAIRED_ATLAS),
    })
    print(f"combined {rows:,} rows -> {REPAIRED_ATLAS}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, choices=range(2021, 2027))
    ap.add_argument("--combine", action="store_true")
    ap.add_argument("--include-2026", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if args.year:
        if args.year == 2026:
            require_frozen_pre_2026_contract("build repaired 2026 atlas")
        build_year(args.year, args.force)
    elif args.combine:
        years = list(range(2021, 2027 if args.include_2026 else 2026))
        if args.include_2026:
            require_frozen_pre_2026_contract("combine repaired atlas through 2026")
        combine(years)
    else:
        raise SystemExit("specify --year YEAR or --combine")


if __name__ == "__main__":
    main()
