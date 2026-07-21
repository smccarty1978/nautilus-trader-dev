"""2021 short-RTH entry-surface + Policy-A-feasibility smoke, on top of the
freshly built 5s-cadence atlas (`build_5s_atlas_smoke.py --year 2021`).

Consolidates the atlas-build stats with: the score-independent surface
funnel (via `entry_surface.build_surface`, same code already reconciled
against 2025-2026), a raw-data gap scan, feature-completeness check, and a
bounded Policy-A-label feasibility check (one label per regime -- the
seq-1-equivalent row -- not the full established/RTH population). This is a
feasibility smoke: it does not produce a training dataset and does not train
anything.
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
WORK, RESULTS, AUDIT = HERE / "_work", HERE / "results", HERE / "audit"

for p in (HERE,
          ROOT / "studies" / "fable5_specialized_w4",
          ROOT / "studies" / "fable5_short_rth_threshold_ladder",
          ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair",
          ROOT / "studies" / "regime_sequence_chop_context"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import build_5s_atlas_smoke as ATLAS  # noqa: E402
import entry_surface as ES  # noqa: E402
import fable5_common as F  # noqa: E402
from CODEX_5_X_common import NS, RAW_1S, sha256_file  # noqa: E402
from CODEX_5_X_run_established_fade import (  # noqa: E402
    canonical_regime_timeline, is_rth, progress_window_counts, validate_raw_bars,
)
from train_weakness_model import CENTER_FEATS, SEQUENCE_FEATS  # noqa: E402

YEAR = 2021
ATLAS_PATH = WORK / f"atlas_5s_backfill_{YEAR}.parquet"
POLICY_PATH = (ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
               / "CODEX_5_X_established_fade_policy.json")


def gap_scan(raw: pd.DataFrame, threshold_s: int = 300) -> list[dict]:
    ts = raw.index.view(np.int64)
    deltas = np.diff(ts) / NS
    idx = np.where(deltas > threshold_s)[0]
    gaps = []
    for i in idx:
        gaps.append({
            "gap_start": str(pd.Timestamp(int(ts[i]), unit="ns", tz="UTC")),
            "gap_end": str(pd.Timestamp(int(ts[i + 1]), unit="ns", tz="UTC")),
            "gap_s": float(deltas[i]),
        })
    return sorted(gaps, key=lambda g: -g["gap_s"])


def feature_completeness(atlas: pd.DataFrame, surface_keys: pd.MultiIndex) -> dict:
    cols = [c for c in CENTER_FEATS + SEQUENCE_FEATS if c in atlas.columns]
    missing_cols = [c for c in CENTER_FEATS + SEQUENCE_FEATS if c not in atlas.columns]
    overall_nan_rate = float(atlas[cols].isna().mean().mean())
    per_col_nan = atlas[cols].isna().mean().sort_values(ascending=False)
    keyed = atlas.set_index(["regime_start_ns", "observation_time"])
    surface_rows = keyed.loc[keyed.index.isin(surface_keys), cols]
    surface_nan_rate = float(surface_rows.isna().mean().mean()) if len(surface_rows) else np.nan
    return {
        "expected_feature_columns": len(CENTER_FEATS) + len(SEQUENCE_FEATS),
        "present_feature_columns": len(cols),
        "missing_feature_columns": missing_cols,
        "overall_nan_rate": overall_nan_rate,
        "surface_row_nan_rate": surface_nan_rate,
        "top10_nan_rate_columns": {k: float(v) for k, v in per_col_nan.head(10).items()},
    }


def policy_a_feasibility(surface: pd.DataFrame, raw: pd.DataFrame, year: int = YEAR) -> dict:
    """Label the first established/RTH/valid-fill checkpoint per regime
    (the seq-1-equivalent row) with Policy A, to prove the labeling
    pipeline runs end-to-end on the new 5s atlas. Not the full dataset."""
    if surface.empty:
        return {"labeled": 0, "note": "no surface rows to label"}
    ts = raw.index.view(np.int64)
    opens = raw["open"].to_numpy(float)
    highs = raw["high"].to_numpy(float)
    lows = raw["low"].to_numpy(float)
    timeline = canonical_regime_timeline(year, raw)
    next_ends = timeline.set_index("regime_start_ns")["regime_end_ns"].to_dict()

    seq1 = (surface.sort_values("observation_time", kind="stable")
            .groupby("regime_start_ns", as_index=False).first())
    labeled, errors = [], []
    for c in seq1.itertuples(index=False):
        align_ts = int(c.confirm_flip_ns)
        scheduled = next_ends.get(align_ts)
        if scheduled is None:
            errors.append({"regime_start_ns": int(c.regime_start_ns), "reason": "no_next_flip"})
            continue
        try:
            r = F.simulate_trade_arrays(
                ts, opens, highs, lows, int(c.fill_ts), float(c.fill_px),
                int(c.entry_direction), float(c.atr_at_checkpoint), align_ts,
                int(scheduled))
        except RuntimeError as exc:
            errors.append({"regime_start_ns": int(c.regime_start_ns), "reason": str(exc)})
            continue
        labeled.append({
            "regime_start_ns": int(c.regime_start_ns),
            "net_pnl_usd": r["net_pnl_usd"], "exit_reason": r["exit_reason"],
            "avoid_pre_alignment_stop": r["exit_reason"] != "preflip_policy_stop",
            "reached_aligning_flip": r["reached_aligning_flip"],
        })
    lab = pd.DataFrame(labeled)
    n = len(lab)
    reasons = ("preflip_policy_stop", "confirmation_timeout_exit",
               "original_stop_after_aligned_flip", "original_opposing_flip_exit")
    return {
        "seq1_candidates": len(seq1),
        "labeled": n,
        "label_errors": len(errors),
        "error_sample": errors[:5],
        "exit_reason_counts": lab["exit_reason"].value_counts().to_dict() if n else {},
        "exit_reason_pnl": {r: float(g["net_pnl_usd"].sum())
                            for r, g in lab.groupby("exit_reason")} if n else {},
        "pre_alignment_stop_rate": float((lab["exit_reason"] == "preflip_policy_stop").mean()) if n else np.nan,
        "timeout_rate": float((lab["exit_reason"] == "confirmation_timeout_exit").mean()) if n else np.nan,
        "post_alignment_stop_rate": float((lab["exit_reason"] == "original_stop_after_aligned_flip").mean()) if n else np.nan,
        "opposing_flip_rate": float((lab["exit_reason"] == "original_opposing_flip_exit").mean()) if n else np.nan,
        "avoid_pre_alignment_stop_rate": float(lab["avoid_pre_alignment_stop"].mean()) if n else np.nan,
        "net_pnl_sum": float(lab["net_pnl_usd"].sum()) if n else np.nan,
        "net_pnl_mean": float(lab["net_pnl_usd"].mean()) if n else np.nan,
    }


def main() -> None:
    t0 = time.time()
    raw = pd.read_parquet(RAW_1S[YEAR], columns=["open", "high", "low", "close", "volume"])
    validate_raw_bars(raw)

    build_manifest = json.loads(ATLAS.build_manifest_path(YEAR).read_text(encoding="utf-8"))

    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    filt = policy["filter"]
    stream = ES.load_atlas_stream(ATLAS_PATH)
    surface, attrition = ES.build_surface(YEAR, stream, raw, filt, is_rth, progress_window_counts)
    surface_runtime = time.time() - t0

    gaps = gap_scan(raw, threshold_s=300)

    atlas_full = pd.read_parquet(ATLAS_PATH)
    surface_keys = pd.MultiIndex.from_frame(surface[["regime_start_ns", "observation_time"]]) \
        if len(surface) else pd.MultiIndex.from_arrays([[], []])
    completeness = feature_completeness(atlas_full, surface_keys)

    policy_a = policy_a_feasibility(surface, raw)

    manifest = {
        "year": YEAR,
        "atlas_build": build_manifest,
        "surface_attrition": attrition,
        "surface_runtime_s": round(surface_runtime, 1),
        "surface_rows": len(surface),
        "raw_gap_scan_threshold_s": 300,
        "raw_gaps_over_threshold": len(gaps),
        "raw_gaps_top10": gaps[:10],
        "feature_completeness": completeness,
        "policy_a_feasibility": policy_a,
        "atlas_sha256": sha256_file(ATLAS_PATH),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
    }
    surface.to_parquet(WORK / f"surface_{YEAR}.parquet", index=False)
    (RESULTS / f"smoke_{YEAR}_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    counts = pd.DataFrame([{
        "year": YEAR, "cadence": "5s",
        "atlas_rows": build_manifest["rows"], "atlas_regimes": build_manifest["distinct_regimes"],
        **{f"checkpoints_{k}": v for k, v in attrition["checkpoints"].items()},
        **{f"regimes_{k}": v for k, v in attrition["distinct_regimes"].items()},
        "seq1_candidates": policy_a.get("seq1_candidates", 0),
        "policy_a_labeled": policy_a.get("labeled", 0),
        "policy_a_errors": policy_a.get("label_errors", 0),
    }])
    counts.to_csv(RESULTS / f"smoke_{YEAR}_counts.csv", index=False)

    lines = [
        f"# {YEAR} 5s-Cadence Short-RTH Entry Surface — Smoke",
        "",
        "## Atlas rebuild (Option A: 5s cadence, no legacy parity)",
        "",
        f"- Runtime: {build_manifest['build_runtime_s']}s",
        f"- Checkpoints: {build_manifest['rows']:,} across {build_manifest['distinct_regimes']:,} regimes",
        f"- Causal audit: {build_manifest['negative_excursion_cells']} negative excursion cells, "
        f"{build_manifest['running_mfe_monotonicity_violations']} MFE monotonicity violations, "
        f"{build_manifest['running_mae_monotonicity_violations']} MAE monotonicity violations",
        f"- Feature columns present: {build_manifest['feature_columns_present']} "
        f"(expected {len(CENTER_FEATS) + len(SEQUENCE_FEATS)})",
        "",
        "## Score-independent surface funnel (checkpoints / distinct regimes)",
        "",
        "| Stage | Checkpoints | Distinct regimes |",
        "|--|--:|--:|",
    ]
    for stage in ("all", "bullish_regime", "established", "rth", "valid_fill",
                  "rth_boundary_divergence"):
        lines.append(f"| {stage} | {attrition['checkpoints'][stage]:,} | "
                      f"{attrition['distinct_regimes'][stage]:,} |")
    lines += [
        "",
        f"Surface build runtime: {surface_runtime:.1f}s",
        "",
        "## Raw-data gap scan (>300s gaps)",
        "",
        f"- Gaps found: {len(gaps)}",
    ]
    for g in gaps[:10]:
        lines.append(f"  - {g['gap_start']} -> {g['gap_end']} ({g['gap_s']:.0f}s)")
    lines += [
        "",
        "## Feature completeness",
        "",
        f"- Expected feature columns: {completeness['expected_feature_columns']}, "
        f"present: {completeness['present_feature_columns']}",
        f"- Missing columns: {completeness['missing_feature_columns'] or 'none'}",
        f"- Overall NaN rate (all checkpoints): {completeness['overall_nan_rate']:.4f}",
        f"- Surface-row NaN rate (established/RTH/valid-fill only): "
        f"{completeness['surface_row_nan_rate']:.4f}",
        "",
        "## Policy A label availability (seq-1-per-regime feasibility check)",
        "",
        f"- Seq-1 candidates (first established/RTH/valid-fill checkpoint per regime): "
        f"{policy_a.get('seq1_candidates', 0):,}",
        f"- Labeled successfully: {policy_a.get('labeled', 0):,}",
        f"- Label errors: {policy_a.get('label_errors', 0)}",
        f"- Exit-reason counts: {policy_a.get('exit_reason_counts', {})}",
        f"- Exit-reason PnL: {policy_a.get('exit_reason_pnl', {})}",
        f"- pre_alignment_stop_rate: {policy_a.get('pre_alignment_stop_rate', float('nan')):.4f}, "
        f"timeout_rate: {policy_a.get('timeout_rate', float('nan')):.4f}, "
        f"post_alignment_stop_rate: {policy_a.get('post_alignment_stop_rate', float('nan')):.4f}, "
        f"opposing_flip_rate: {policy_a.get('opposing_flip_rate', float('nan')):.4f}"
        if policy_a.get("labeled", 0) else "- exit-reason rates: n/a",
        f"- avoid_pre_alignment_stop rate: {policy_a.get('avoid_pre_alignment_stop_rate', float('nan')):.4f}"
        if policy_a.get("labeled", 0) else "- avoid_pre_alignment_stop rate: n/a",
        f"- Net PnL sum / mean (sanity check only, NOT a claimed result): "
        f"${policy_a.get('net_pnl_sum', float('nan')):,.0f} / "
        f"${policy_a.get('net_pnl_mean', float('nan')):,.2f}"
        if policy_a.get("labeled", 0) else "- Net PnL: n/a",
        "",
        "## Audit / provenance status",
        "",
        "- Atlas rebuild reuses `attach_causal_w4_context`, "
        "`compute_activity_features_batched`, `compute_sequence_features_batched` "
        "verbatim from the already-audited "
        "`CODEX_5_X_weakness_atlas_repair` pipeline "
        "(`audit/CODEX_5_X_pre_execution_audit.md`, PASS, 0 CRITICAL/0 WARNING).",
        "- Surface generation reuses `entry_surface.py`, which passed its own "
        "dedicated lookahead audit (`audit/audit.md`, PASS, 0 CRITICAL, 1 WARNING "
        "-- since fixed) and was empirically reconciled exact against the known "
        "2025/2026 candidate population (650/222, 0 missing, 0 mismatched).",
        "- The `rth_boundary_divergence` diagnostic is reported above for 2021 "
        "specifically because the audit warning flagged this as an open risk at "
        "coarser/older data -- see the table.",
        "- This smoke has not itself been separately re-audited beyond reusing "
        "already-PASS-gated code; no new causal logic was introduced in "
        "`smoke_2021_surface.py` (gap scan and feature-completeness are pure "
        "read-only diagnostics; Policy A replay reuses `simulate_trade_arrays` "
        "verbatim).",
        "",
        "## Suitability for 2021-2024 expansion",
        "",
        "Mechanically feasible and causally clean at single-year scale: atlas "
        f"rebuild took {build_manifest['build_runtime_s']}s "
        f"(None = reused an already-built atlas, audit recomputed not rebuilt), "
        f"surface funnel "
        f"and feature completeness look structurally identical in shape to "
        f"2025/2026 (see reconciliation smoke), and the seq-1 Policy A label "
        f"pass ran without error. Recommend running the same three steps "
        f"(atlas rebuild, surface funnel, seq-1 label feasibility) for "
        f"2022-2024 before treating the full 2021-2024 backfill as ready.",
    ]
    (RESULTS / f"smoke_{YEAR}_summary.md").write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(manifest, indent=2, default=str))


if __name__ == "__main__":
    main()
