"""Phase 0 data readiness for short_rth_w4_retrain_entry_strength.

Closes the two gaps found by the SPEC's scout pass:

1. Joins the 149 causal CENTER_FEATS+SEQUENCE_FEATS onto the already-labeled
   2021-2024 surface (`short_rth_entry_surface_backfill/results/
   full_surface_labels_{year}.parquet`), keyed 1:1 on
   (regime_start_ns, observation_time).
2. Builds full-surface Policy A labels for 2025-2026 using the exact same
   reused functions as 2021-2024 (`label_full_surface.label_row`,
   `add_derived_targets`, `data_quality_checks` -- imported, not
   reimplemented), sourced from the already-computed and already-reconciled
   `reconciliation_2025_2026_surface.parquet`, then joins the same 149
   features from the CODEX_5_X repaired atlas.

Writes exclusively into THIS study's own `_work/`/`results/` -- the
already-accepted `short_rth_entry_surface_backfill` directory is read-only
input here, never modified.

No model is trained in this script. No feature is selected (all 149 are
carried through). No W4 score is used to define 2021-2024 candidates.
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
BACKFILL = ROOT / "studies" / "short_rth_entry_surface_backfill"
WORK, RESULTS, AUDIT = HERE / "_work", HERE / "results", HERE / "audit"
for d in (WORK, RESULTS, AUDIT):
    d.mkdir(parents=True, exist_ok=True)

for p in (BACKFILL,
          ROOT / "studies" / "fable5_specialized_w4",
          ROOT / "studies" / "fable5_short_rth_threshold_ladder",
          ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair",
          ROOT / "studies" / "regime_sequence_chop_context"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import label_full_surface as LFS  # noqa: E402 (reused verbatim, unmodified)
from CODEX_5_X_common import RAW_1S, sha256_file, year_atlas_path  # noqa: E402
from CODEX_5_X_run_established_fade import (  # noqa: E402
    canonical_regime_timeline, validate_raw_bars,
)
from train_weakness_model import CENTER_FEATS, SEQUENCE_FEATS  # noqa: E402
import run_ladder as LADDER  # noqa: E402

FEATURE_COLS = CENTER_FEATS + SEQUENCE_FEATS
TRAIN_YEARS = (2021, 2022, 2023, 2024)
KEY = ["regime_start_ns", "observation_time"]


def join_features_2021_2024() -> dict:
    """Step 1: join the 149 features onto the already-labeled surface."""
    report = {}
    frames = []
    for year in TRAIN_YEARS:
        labels = pd.read_parquet(BACKFILL / "results" / f"full_surface_labels_{year}.parquet")
        atlas_cols = KEY + FEATURE_COLS
        atlas = pd.read_parquet(
            BACKFILL / "_work" / f"atlas_5s_backfill_{year}.parquet", columns=atlas_cols)
        if atlas.duplicated(KEY).any():
            raise RuntimeError(f"{year}: duplicate atlas keys, cannot join 1:1")
        merged = labels.merge(atlas, on=KEY, how="left", validate="many_to_one")
        # A row's join fails iff none of its feature columns got a match.
        join_rate = float((~merged[FEATURE_COLS].isna().all(axis=1)).mean())
        report[year] = {
            "rows": len(labels), "join_rows": len(merged),
            "join_rate_any_feature_present": join_rate,
            "fully_missing_features": int(merged[FEATURE_COLS].isna().all(axis=1).sum()),
        }
        if len(merged) != len(labels):
            raise RuntimeError(f"{year}: join changed row count {len(labels)} -> {len(merged)}")
        out_path = WORK / f"labeled_featured_{year}.parquet"
        merged.to_parquet(out_path, index=False, compression="zstd")
        report[year]["output_path"] = str(out_path)
        frames.append(merged)
    combined = pd.concat(frames, ignore_index=True)
    combined.to_parquet(WORK / "train_2021_2024_featured.parquet", index=False, compression="zstd")
    report["combined_rows"] = len(combined)
    report["combined_output"] = str(WORK / "train_2021_2024_featured.parquet")
    return report


def build_2025_2026_labels_and_features() -> dict:
    """Step 2: full-surface Policy A labels + feature join for 2025-2026,
    sourced from the already-reconciled surface (no rebuild)."""
    recon_surface = pd.read_parquet(
        BACKFILL / "results" / "reconciliation_2025_2026_surface.parquet")
    report = {}
    for year in (2025, 2026):
        t0 = time.time()
        surface = recon_surface[recon_surface["year"] == year].reset_index(drop=True)

        raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close", "volume"])
        validate_raw_bars(raw)
        ts = raw.index.view(np.int64)
        opens, highs, lows = (raw[c].to_numpy(float) for c in ("open", "high", "low"))
        timeline = canonical_regime_timeline(year, raw)
        next_ends = timeline.set_index("regime_start_ns")["regime_end_ns"].to_dict()

        records = [LFS.label_row(row, ts, opens, highs, lows, next_ends)
                   for row in surface.itertuples(index=False)]
        labels = LFS.add_derived_targets(pd.DataFrame(records))
        runtime_s = time.time() - t0
        dq = LFS.data_quality_checks(labels)

        atlas = pd.read_parquet(year_atlas_path(year), columns=KEY + FEATURE_COLS)
        if atlas.duplicated(KEY).any():
            raise RuntimeError(f"{year}: duplicate atlas keys, cannot join 1:1")
        merged = labels.merge(atlas, on=KEY, how="left", validate="many_to_one")
        if len(merged) != len(labels):
            raise RuntimeError(f"{year}: join changed row count {len(labels)} -> {len(merged)}")
        join_rate = float((~merged[FEATURE_COLS].isna().all(axis=1)).mean())

        out_path = WORK / f"labeled_featured_{year}.parquet"
        merged.to_parquet(out_path, index=False, compression="zstd")

        n = len(merged)
        n_labeled = int(merged["label_available"].sum())
        report[year] = {
            "surface_rows": len(surface), "rows_labeled": n_labeled,
            "rows_censored": int((~merged["label_available"] & ~merged["label_error"]).sum()),
            "label_errors": int(merged["label_error"].sum()),
            "join_rate_any_feature_present": join_rate,
            "runtime_s": round(runtime_s, 1),
            "data_quality_checks": dq,
            "output_path": str(out_path),
        }
    return report


def reconcile_controls() -> dict:
    """Re-verify the known 650/222 candidate-basis controls on the
    feature-joined 2025-2026 output, using the exact same reused
    generate_entries/gate_candidate logic already validated in
    short_rth_entry_surface_backfill."""
    policy = json.loads(
        (ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
         / "CODEX_5_X_established_fade_policy.json").read_text(encoding="utf-8"))
    filt = policy["filter"]
    report = {}
    for year in (2025, 2026):
        raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close", "volume"])
        validate_raw_bars(raw)
        stream = LADDER.load_checkpoint_stream(year, policy)
        crossing = LADDER.generate_entries(year, raw, stream, LADDER.CONTROL, filt)
        try:
            gate = LADDER.gate_candidate(year, crossing)
            gate_error = None
        except (RuntimeError, AssertionError) as exc:
            gate = None
            gate_error = str(exc)

        featured = pd.read_parquet(WORK / f"labeled_featured_{year}.parquet",
                                   columns=KEY + ["label_available"])
        fk = pd.MultiIndex.from_frame(featured[KEY].astype("int64"))
        missing = 0
        for c in crossing.itertuples(index=False):
            key = (int(c.regime_start_ns), int(c.signal_decision_ts))
            if key not in fk:
                missing += 1
        report[year] = {
            "crossing_candidates": len(crossing),
            "expected_control": LADDER.YEAR_CAND_COUNT[year],
            "gate_result": gate, "gate_error": gate_error,
            "missing_from_featured_surface": missing,
        }
    return report


def main() -> None:
    t0 = time.time()
    r1 = join_features_2021_2024()
    r2 = build_2025_2026_labels_and_features()
    r3 = reconcile_controls()

    passed = (
        all(r1[y]["join_rate_any_feature_present"] == 1.0 for y in TRAIN_YEARS)
        and all(r2[y]["join_rate_any_feature_present"] == 1.0 for y in (2025, 2026))
        and all(r2[y]["label_errors"] == 0 for y in (2025, 2026))
        and all(r3[y]["crossing_candidates"] == r3[y]["expected_control"] for y in (2025, 2026))
        and all(r3[y]["gate_error"] is None for y in (2025, 2026))
        and all(r3[y]["missing_from_featured_surface"] == 0 for y in (2025, 2026))
    )
    decision = "PHASE0_PASS" if passed else "SHORT_RTH_PARITY_FAIL"

    manifest = {
        "decision": decision,
        "join_2021_2024": r1,
        "labels_features_2025_2026": r2,
        "control_reconciliation": r3,
        "feature_columns": len(FEATURE_COLS),
        "runtime_s": round(time.time() - t0, 1),
        "generator_sha256": sha256_file(Path(__file__).resolve()),
    }
    (RESULTS / "phase0_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    lines = [
        "# Phase 0 — Data Readiness",
        "",
        f"## Decision: `{decision}`",
        "",
        "## 2021-2024 feature join",
        "",
        "| Year | Rows | Join rate | Fully-missing-feature rows |",
        "|--:|--:|--:|--:|",
    ]
    for y in TRAIN_YEARS:
        lines.append(f"| {y} | {r1[y]['rows']:,} | {r1[y]['join_rate_any_feature_present']:.4f} | "
                      f"{r1[y]['fully_missing_features']} |")
    lines += ["", "## 2025-2026 full-surface labeling + feature join", "",
              "| Year | Surface rows | Labeled | Censored | Errors | Join rate |",
              "|--:|--:|--:|--:|--:|--:|"]
    for y in (2025, 2026):
        lines.append(f"| {y} | {r2[y]['surface_rows']:,} | {r2[y]['rows_labeled']:,} | "
                      f"{r2[y]['rows_censored']} | {r2[y]['label_errors']} | "
                      f"{r2[y]['join_rate_any_feature_present']:.4f} |")
    lines += ["", "## Control reconciliation (crossing-based, 650/222)", "",
              "| Year | Crossing candidates | Expected | Gate | Missing from featured surface |",
              "|--:|--:|--:|--|--:|"]
    for y in (2025, 2026):
        r = r3[y]
        gate_str = "PASS" if r["gate_error"] is None else f"FAIL: {r['gate_error']}"
        lines.append(f"| {y} | {r['crossing_candidates']} | {r['expected_control']} | "
                      f"{gate_str} | {r['missing_from_featured_surface']} |")
    lines += ["", f"Combined 2021-2024 rows: {r1['combined_rows']:,}", ""]
    (RESULTS / "phase0_summary.md").write_text("\n".join(lines), encoding="utf-8")

    print("DECISION:", decision)
    print(json.dumps(manifest, indent=2, default=str)[:3000])


if __name__ == "__main__":
    main()
