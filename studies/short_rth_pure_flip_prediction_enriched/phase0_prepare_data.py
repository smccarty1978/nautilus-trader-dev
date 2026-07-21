"""Phase 0 -- join gate-input columns, build the CORRECTED pure
regime-transition primary label, and the full-checkpoint (not
first-eligible-only) surface for all 6 years.

Per SPEC.md scout-pass finding 1: `bearish_regime_flip_within_300s` is
built fresh, by pure arithmetic on `confirm_flip_ns` vs `observation_time`
-- NEVER via Policy A's `aligned` column, which conflates "regime flipped
within 300s" with "hypothetical trade survived the 1.25xATR pre-alignment
stop long enough to see it" (traced in
`[[age_gate_120_vs_240_inconclusive]]`'s correction note).

Reuses, unmodified, via import (unaffected by the aligned-bug):
`load_gate_columns`, `post_flip_mfe_by_regime`, `followthrough_flag` from
`studies/short_rth_established_age_gate_flip_quality/phase0_prepare_data.py`.
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
AGE_GATE_STUDY = ROOT / "studies" / "short_rth_established_age_gate_flip_quality"
ENRICHED_RETRAIN = ROOT / "studies" / "short_rth_enriched_volume_level_retrain"
WORK, RESULTS, AUDIT = HERE / "_work", HERE / "results", HERE / "audit"
for d in (WORK, RESULTS, AUDIT):
    d.mkdir(parents=True, exist_ok=True)

for p in (ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from CODEX_5_X_common import NS, RAW_1S, sha256_file  # noqa: E402
from CODEX_5_X_run_established_fade import validate_raw_bars  # noqa: E402


def _load_module(name: str, path: Path):
    """Both upstream scripts are named `phase0_prepare_data.py` -- a plain
    `from phase0_prepare_data import ...` would collide via sys.modules
    caching (the second import would silently resolve against the first
    module). Load each under a distinct internal name instead."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_enriched_retrain_phase0 = _load_module(
    "_enriched_retrain_phase0", ENRICHED_RETRAIN / "phase0_prepare_data.py")
# The age-gate script's OWN source does `from phase0_prepare_data import
# find_position_cols, one_hot_position_cols` (a bare-name import). Register
# the already-loaded enriched-retrain module under that bare name so the
# age-gate script's internal import resolves to it, instead of colliding
# with (or partially re-executing) whatever else is registered under that
# name -- e.g. this very file, if it is ever `import`ed rather than run
# directly, which registers itself under the literal name
# "phase0_prepare_data" mid-execution and would otherwise be found first.
# Save/restore rather than blind delete: if THIS file is itself being
# imported under that same bare name (not run as __main__), a bare delete
# would corrupt the import machinery's own in-progress bookkeeping for it.
_sentinel = object()
_prior_module = sys.modules.get("phase0_prepare_data", _sentinel)
sys.modules["phase0_prepare_data"] = _enriched_retrain_phase0
_age_gate_phase0 = _load_module(
    "_age_gate_phase0", AGE_GATE_STUDY / "phase0_prepare_data.py")
if _prior_module is _sentinel:
    del sys.modules["phase0_prepare_data"]
else:
    sys.modules["phase0_prepare_data"] = _prior_module

followthrough_flag = _age_gate_phase0.followthrough_flag
load_gate_columns = _age_gate_phase0.load_gate_columns
post_flip_mfe_by_regime = _age_gate_phase0.post_flip_mfe_by_regime
find_position_cols = _enriched_retrain_phase0.find_position_cols
one_hot_position_cols = _enriched_retrain_phase0.one_hot_position_cols

KEY = ["regime_start_ns", "observation_time"]
ALL_YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
TRAIN_YEARS = (2021, 2022, 2023, 2024)
TIMEOUT_S = 300.0


def build_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Corrected primary label + reused secondary diagnostics.

    `bearish_regime_flip_within_300s`/`600s` and `time_to_bearish_flip_s`
    are PURE arithmetic on `confirm_flip_ns` -- independent of any Policy A
    trade simulation, stop, or timeout mechanics. This is the fix for the
    conflation documented in SPEC.md finding 1.
    """
    df = df.copy()
    df["time_to_bearish_flip_s"] = (df["confirm_flip_ns"] - df["observation_time"]) / 1e9
    df["bearish_regime_flip_within_300s"] = df["time_to_bearish_flip_s"] <= 300.0
    df["bearish_flip_within_600s"] = df["time_to_bearish_flip_s"] <= 600.0
    df["no_flip_before_timeout"] = ~df["bearish_regime_flip_within_300s"]

    # Secondary diagnostic only -- correctly answers "did the stop-relevant
    # adverse move happen," a different question from the primary label,
    # not repurposed as a flip indicator (SPEC.md finding 5).
    df["adverse_move_1p25A_before_bearish_flip"] = df["hit_pre_alignment_stop"].astype(bool)

    df["post_flip_mfe_atr_300s"] = df["post_flip_mfe_points_300s"] / df["atr_at_entry"]
    df["post_flip_mfe_atr_600s"] = df["post_flip_mfe_points_600s"] / df["atr_at_entry"]

    df["bearish_flip_within_300s_and_followthrough_1A"] = followthrough_flag(
        df["bearish_regime_flip_within_300s"], df["post_flip_mfe_atr_300s"])
    df["bearish_flip_within_600s_and_followthrough_1A"] = followthrough_flag(
        df["bearish_flip_within_600s"], df["post_flip_mfe_atr_600s"])
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
    if not (merged["regime_age_s"] >= 120.0).all():
        raise RuntimeError(f"{year}: found rows with regime_age_s < 120 -- gate assumption violated")

    raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close", "volume"])
    validate_raw_bars(raw)
    regime_flips = merged[["regime_start_ns", "confirm_flip_ns"]]
    post_flip = post_flip_mfe_by_regime(year, regime_flips, raw)
    merged = merged.merge(post_flip, on="regime_start_ns", how="left", validate="many_to_one")
    if len(merged) != n_before:
        raise RuntimeError(f"{year}: post-flip join changed row count")

    labeled = build_labels(merged)
    # These two are Policy-A-SIMULATION non-resolution counts (a separate,
    # diagnostic-only concept) -- NOT primary-label censoring. Per SPEC.md
    # finding 2, the primary label itself has 0 censored rows on this
    # population (confirm_flip_ns is always known); report that explicitly
    # rather than conflating it with policy_a_censored below.
    policy_a_censored = int((~labeled["label_available"]).sum()) if "label_available" in labeled else 0
    primary_label_censored = int(labeled["bearish_regime_flip_within_300s"].isna().sum())

    position_cols = find_position_cols(labeled)
    labeled, dummy_cols = one_hot_position_cols(labeled, position_cols)

    out_path = WORK / f"prepared_{year}.parquet"
    labeled.to_parquet(out_path, index=False, compression="zstd")

    return {
        "year": year, "rows": len(labeled),
        "primary_label_censored_rows": primary_label_censored,
        "policy_a_simulation_censored_rows_DIAGNOSTIC_ONLY": policy_a_censored,
        "policy_a_simulation_usable_rows_DIAGNOSTIC_ONLY": len(labeled) - policy_a_censored,
        "join_rate_gate_cols": join_rate,
        "distinct_regimes": int(labeled["regime_start_ns"].nunique()),
        "mean_rows_per_regime": float(len(labeled) / labeled["regime_start_ns"].nunique()),
        "median_rows_per_regime": float(
            labeled.groupby("regime_start_ns").size().median()),
        "positive_label_count": int(labeled["bearish_regime_flip_within_300s"].sum()),
        "positive_label_rate": float(labeled["bearish_regime_flip_within_300s"].mean()),
        "post_flip_mfe_300s_unavailable": int(labeled["post_flip_mfe_atr_300s"].isna().sum()),
        "post_flip_mfe_600s_unavailable": int(labeled["post_flip_mfe_atr_600s"].isna().sum()),
        "n_position_categorical_cols": len(position_cols), "n_position_dummy_cols": len(dummy_cols),
        "runtime_s": round(time.time() - t0, 1),
    }


def main() -> None:
    t0 = time.time()
    feature_sets = json.loads((ENRICHED_RETRAIN / "_work" / "feature_sets.json").read_text(encoding="utf-8"))
    (WORK / "feature_sets.json").write_text(json.dumps(feature_sets, indent=2), encoding="utf-8")

    year_reports = {y: run_year(y) for y in ALL_YEARS}

    train_combined = pd.concat(
        [pd.read_parquet(WORK / f"prepared_{y}.parquet") for y in TRAIN_YEARS], ignore_index=True)
    train_combined.to_parquet(WORK / "train_2021_2024_prepared.parquet", index=False, compression="zstd")

    manifest = {
        "timeout_s": TIMEOUT_S, "year_reports": year_reports,
        "train_2021_2024_rows": len(train_combined),
        "runtime_s": round(time.time() - t0, 1),
        "generator_sha256": sha256_file(Path(__file__).resolve()),
    }
    (RESULTS / "phase0_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(json.dumps(year_reports, indent=2, default=str))
    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
