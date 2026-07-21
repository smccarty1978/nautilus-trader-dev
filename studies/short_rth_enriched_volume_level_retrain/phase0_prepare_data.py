"""Phase 0 data readiness for short_rth_enriched_volume_level_retrain.

Consumes `studies/ohlcv_volume_delta_price_level_features/_work/full_{year}.parquet`
(2021-2026), the accepted feature-foundation study's output. Verified by
direct comparison (see SPEC.md "Scout-pass findings") to be an exact
row-for-row, label-for-label superset of the prior retrain study's
`labeled_featured_{year}.parquet` -- the 650/222 crossing-candidate
reconciliation and the raw-bar-derived control checks already passed there
(`short_rth_w4_retrain_entry_strength/results/phase0_manifest.json`,
`PHASE0_PASS`, 0 mismatches) therefore still hold here by construction; this
script re-verifies key/label identity rather than re-running the expensive
raw-bar crossing scan a second time on unchanged population data.

Builds, once, in this study's own `_work/`:
1. `outcome_class` (5-class target) from the existing `exit_reason`/`net_pnl`
   columns -- no new label logic, a pure case-when mapping.
2. One-hot encodings of the 28 bounded `*_position` categorical columns
   (fixed category list, `UNAVAILABLE` kept explicit).
3. F0/F1/F2/F3 feature column lists.
4. The concatenated 2021-2024 training frame.

No model is trained here. No feature is selected beyond the four
predeclared sets. No W4 score is used to define candidates.
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
PRIOR_RETRAIN = ROOT / "studies" / "short_rth_w4_retrain_entry_strength"
WORK, RESULTS, AUDIT = HERE / "_work", HERE / "results", HERE / "audit"
for d in (WORK, RESULTS, AUDIT):
    d.mkdir(parents=True, exist_ok=True)

for p in (ROOT / "studies" / "regime_sequence_chop_context", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from train_weakness_model import CENTER_FEATS, SEQUENCE_FEATS  # noqa: E402
from features.registry import FEATURE_REGISTRY  # noqa: E402

F0_FEATS = CENTER_FEATS + SEQUENCE_FEATS
KEY = ["regime_start_ns", "observation_time"]
ALL_YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
TRAIN_YEARS = (2021, 2022, 2023, 2024)

PROVENANCE_COLS = [
    "observation_ts", "latest_source_ts_used",
    "latest_1s_bar_close_ts_used", "latest_1m_bar_close_ts_used",
]
NAME_COLS = ["nearest_level_above_name", "nearest_level_below_name"]
POSITION_CATEGORIES = ["ABOVE", "BELOW", "TOUCH", "UNAVAILABLE"]


def sha256_file(path: Path, block: int = 1 << 20) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def find_position_cols(df: pd.DataFrame) -> list[str]:
    cols = [c for c in df.columns if c.endswith("_position") and df[c].dtype == object]
    return sorted(cols)


def one_hot_position_cols(df: pd.DataFrame, position_cols: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Fixed-category one-hot encoding: every dummy column always exists,
    even if a category never occurs in this split, so F2/F3 schemas are
    identical across train/dev/test."""
    added = []
    for col in position_cols:
        vals = df[col].fillna("UNAVAILABLE")
        unexpected = set(vals.unique()) - set(POSITION_CATEGORIES)
        if unexpected:
            raise ValueError(f"{col}: unexpected category values {unexpected}")
        for cat in POSITION_CATEGORIES:
            new_col = f"{col}__{cat}"
            df[new_col] = (vals == cat).astype(np.int8)
            added.append(new_col)
    return df, added


def build_outcome_class(df: pd.DataFrame) -> pd.DataFrame:
    exit_reason = df["exit_reason"]
    net_pnl = df["net_pnl"].astype(float)
    cls = pd.Series(index=df.index, dtype=object)
    cls[exit_reason == "preflip_policy_stop"] = "pre_alignment_stop"
    cls[exit_reason == "confirmation_timeout_exit"] = "confirmation_timeout"
    cls[exit_reason == "original_stop_after_aligned_flip"] = "post_alignment_stop"
    opp = exit_reason == "original_opposing_flip_exit"
    cls[opp & (net_pnl > 0)] = "opposing_flip_winner"
    cls[opp & (net_pnl <= 0)] = "opposing_flip_loser"
    if cls.isna().any():
        raise RuntimeError(f"{int(cls.isna().sum())} rows did not map to an outcome_class")
    df = df.copy()
    df["outcome_class"] = cls
    # sanity: opposing_flip_exit_positive (existing col) must equal winner flag
    expected_winner = (df["opposing_flip_exit_positive"] == 1)
    if not (expected_winner == (df["outcome_class"] == "opposing_flip_winner")).all():
        raise RuntimeError("outcome_class winner mapping disagrees with opposing_flip_exit_positive")
    return df


def load_year(year: int) -> pd.DataFrame:
    df = pd.read_parquet(FEAT_STUDY / "_work" / f"full_{year}.parquet")
    df = df[df["label_available"]].reset_index(drop=True)
    df = build_outcome_class(df)
    position_cols = find_position_cols(df)
    df, position_dummy_cols = one_hot_position_cols(df, position_cols)
    return df, position_cols, position_dummy_cols


def verify_identity_vs_prior_retrain() -> dict:
    """Confirms full_{year}.parquet is row/label-identical to
    labeled_featured_{year}.parquet, so the prior study's raw-bar-derived
    650/222 crossing-candidate reconciliation still applies unchanged."""
    check_cols = ["exit_reason", "net_pnl", "hit_pre_alignment_stop", "hit_timeout",
                  "hit_post_alignment_stop", "hit_opposing_flip", "label_available"]
    report = {}
    for year in ALL_YEARS:
        old = pd.read_parquet(PRIOR_RETRAIN / "_work" / f"labeled_featured_{year}.parquet")
        new = pd.read_parquet(FEAT_STUDY / "_work" / f"full_{year}.parquet")
        key_match = old[KEY].reset_index(drop=True).equals(new[KEY].reset_index(drop=True))
        label_ident = True
        for c in check_cols:
            a, b = old[c], new[c]
            if a.dtype == object:
                eq = bool((a.astype(str) == b.astype(str)).all())
            else:
                eq = bool(np.allclose(a.fillna(-999999).astype(float),
                                       b.fillna(-999999).astype(float)))
            label_ident = label_ident and eq
        report[year] = {
            "rows_prior_retrain": len(old), "rows_feature_foundation": len(new),
            "row_count_match": len(old) == len(new),
            "key_match": bool(key_match), "label_columns_identical": bool(label_ident),
        }
    return report


def main() -> None:
    t0 = time.time()
    identity = verify_identity_vs_prior_retrain()
    identity_ok = all(v["row_count_match"] and v["key_match"] and v["label_columns_identical"]
                       for v in identity.values())

    prior_phase0 = json.loads(
        (PRIOR_RETRAIN / "results" / "phase0_manifest.json").read_text(encoding="utf-8"))
    prior_control = prior_phase0["control_reconciliation"]
    control_reused_valid = (
        prior_phase0["decision"] == "PHASE0_PASS"
        and prior_control["2025"]["crossing_candidates"] == 650
        and prior_control["2026"]["crossing_candidates"] == 222
        and prior_control["2025"]["gate_error"] is None
        and prior_control["2026"]["gate_error"] is None
    )

    frames, position_cols_by_year, dummy_cols_by_year = {}, {}, {}
    readiness_rows = []
    for year in ALL_YEARS:
        df, position_cols, dummy_cols = load_year(year)
        frames[year] = df
        position_cols_by_year[year] = position_cols
        dummy_cols_by_year[year] = dummy_cols
        out_path = WORK / f"prepared_{year}.parquet"
        df.to_parquet(out_path, index=False, compression="zstd")
        readiness_rows.append({
            "year": year, "rows": len(df), "n_columns": df.shape[1],
            "n_position_categorical_cols": len(position_cols),
            "n_position_dummy_cols": len(dummy_cols),
            "outcome_class_counts": json.dumps(df["outcome_class"].value_counts().to_dict()),
        })

    # Sanity: position/dummy column sets identical across all years.
    ref_pos = set(position_cols_by_year[2021])
    ref_dummy = set(dummy_cols_by_year[2021])
    for year in ALL_YEARS:
        if set(position_cols_by_year[year]) != ref_pos:
            raise RuntimeError(f"{year}: position column set differs from 2021")
        if set(dummy_cols_by_year[year]) != ref_dummy:
            raise RuntimeError(f"{year}: dummy column set differs from 2021")
    if len(ref_pos) != 29:
        raise RuntimeError(f"expected 29 position categorical columns, found {len(ref_pos)}")

    excluded = set(PROVENANCE_COLS) | set(NAME_COLS) | set(ref_pos)
    # Everything from the 461-feature registry that is NOT F0 and NOT a
    # position/name/provenance column is either ohlcv_est_delta or
    # price_level_context (numeric, no further encoding needed).
    ohlcv_feats = [c for c in frames[2021].columns
                   if c in FEATURE_REGISTRY and FEATURE_REGISTRY[c].family == "ohlcv_est_delta"]
    level_feats_numeric = [c for c in frames[2021].columns
                            if c in FEATURE_REGISTRY and FEATURE_REGISTRY[c].family == "price_level_context"
                            and c not in excluded]
    level_feats = level_feats_numeric + sorted(ref_dummy)

    feature_sets = {
        "F0_existing_only": F0_FEATS,
        "F1_volume_delta_only": F0_FEATS + ohlcv_feats,
        "F2_price_levels_only": F0_FEATS + level_feats,
        "F3_volume_delta_plus_price_levels": F0_FEATS + ohlcv_feats + level_feats,
    }
    for name, cols in feature_sets.items():
        missing = [c for c in cols if c not in frames[2021].columns]
        if missing:
            raise RuntimeError(f"{name}: missing columns {missing[:5]}...")
    (WORK / "feature_sets.json").write_text(
        json.dumps({k: v for k, v in feature_sets.items()}, indent=2), encoding="utf-8")

    train_combined = pd.concat([frames[y] for y in TRAIN_YEARS], ignore_index=True)
    train_combined.to_parquet(WORK / "train_2021_2024_prepared.parquet", index=False, compression="zstd")

    decision = "PHASE0_PASS" if (identity_ok and control_reused_valid) else "SHORT_RTH_PARITY_FAIL"

    manifest = {
        "decision": decision,
        "identity_vs_prior_retrain": identity,
        "control_reconciliation_reused_from": str(
            PRIOR_RETRAIN / "results" / "phase0_manifest.json"),
        "control_reconciliation": prior_control,
        "control_reconciliation_reused_valid": control_reused_valid,
        "feature_set_sizes": {k: len(v) for k, v in feature_sets.items()},
        "n_ohlcv_delta_features": len(ohlcv_feats),
        "n_price_level_features_numeric": len(level_feats_numeric),
        "n_price_level_dummy_features": len(ref_dummy),
        "n_position_categorical_cols_source": len(ref_pos),
        "train_2021_2024_rows": len(train_combined),
        "runtime_s": round(time.time() - t0, 1),
        "generator_sha256": sha256_file(Path(__file__).resolve()),
    }
    (RESULTS / "phase0_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    pd.DataFrame(readiness_rows).to_csv(RESULTS / "data_readiness.csv", index=False)

    print("DECISION:", decision)
    print(pd.DataFrame(readiness_rows).to_string(index=False))
    print(json.dumps({k: v for k, v in manifest.items()
                       if k not in ("identity_vs_prior_retrain",)}, indent=2, default=str))


if __name__ == "__main__":
    main()
