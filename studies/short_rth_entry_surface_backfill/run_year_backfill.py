"""Generalized per-year 5s-cadence backfill: atlas rebuild + score-independent
surface + feature completeness + seq-1 Policy A feasibility, for 2022-2024.

Reuses, unchanged, the exact functions already validated:
- `build_5s_atlas_smoke.build_raw_checkpoints_5s` /
  `build_5s_atlas_smoke.intrinsic_causal_audit` (smoke-tested on 2021);
- `entry_surface.load_atlas_stream` / `entry_surface.build_surface`
  (reconciled exact against the known 2025/2026 candidate population, fixed
  post-audit to classify RTH on fill-time);
- `smoke_2021_surface.gap_scan` / `feature_completeness` /
  `policy_a_feasibility` (the last now parameterized by year).

No new causal logic is introduced here beyond a gap classifier (weekend/
holiday/daily-maintenance vs suspicious-intraday), which is a read-only
diagnostic over already-computed gaps, not a change to any causal boundary.
Outputs use this expansion phase's `backfill_{year}_*` naming (2021's
already-accepted `smoke_2021_*` files are left as-is).
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
ROOT = HERE.parents[1]
WORK, RESULTS, AUDIT = HERE / "_work", HERE / "results", HERE / "audit"
for d in (WORK, RESULTS, AUDIT):
    d.mkdir(parents=True, exist_ok=True)

for p in (HERE,
          ROOT / "studies" / "fable5_specialized_w4",
          ROOT / "studies" / "fable5_short_rth_threshold_ladder",
          ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair",
          ROOT / "studies" / "regime_sequence_chop_context"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import build_5s_atlas_smoke as ATLAS  # noqa: E402
import entry_surface as ES  # noqa: E402
import smoke_2021_surface as SMOKE  # noqa: E402
from CODEX_5_X_common import RAW_1S, sha256_file  # noqa: E402
from CODEX_5_X_run_established_fade import (  # noqa: E402
    is_rth, progress_window_counts, validate_raw_bars,
)
from train_weakness_model import CENTER_FEATS, SEQUENCE_FEATS  # noqa: E402

POLICY_PATH = (ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
               / "CODEX_5_X_established_fade_policy.json")


def classify_gap(gap: dict) -> str:
    """Read-only diagnostic over an already-computed (start,end,duration)
    gap -- does not touch any causal boundary used elsewhere in this study."""
    start = pd.Timestamp(gap["gap_start"])
    end = pd.Timestamp(gap["gap_end"])
    hours = gap["gap_s"] / 3600.0
    if hours < 2.0:
        return "daily_maintenance_break"
    span_days = (end.normalize() - start.normalize()).days + 1
    covers_saturday = any(
        (start.normalize() + pd.Timedelta(days=d)).weekday() == 5
        for d in range(span_days)
    )
    if covers_saturday or hours >= 40.0:
        return "weekend_or_holiday"
    start_ct = start.tz_convert("America/Chicago")
    end_ct = end.tz_convert("America/Chicago")

    def _in_rth(t: pd.Timestamp) -> bool:
        m = t.hour * 60 + t.minute
        return 8 * 60 + 30 <= m < 15 * 60

    if start.normalize() == end.normalize() and (_in_rth(start_ct) or _in_rth(end_ct)):
        return "SUSPICIOUS_INTRADAY"
    return "multi_day_holiday_likely"


def run_year(year: int) -> dict:
    t0 = time.time()
    out, contracts = ATLAS.build_raw_checkpoints_5s(year)
    build_s = time.time() - t0
    atlas_audit = ATLAS.intrinsic_causal_audit(year, out)
    atlas_audit["build_runtime_s"] = round(build_s, 1)
    atlas_audit["raw_sha256"] = sha256_file(RAW_1S[year])

    out_path = WORK / f"atlas_5s_backfill_{year}.parquet"
    out.to_parquet(out_path, index=False, compression="zstd")
    atlas_audit["output_path"] = str(out_path)
    atlas_audit["output_sha256"] = sha256_file(out_path)

    t1 = time.time()
    raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close", "volume"])
    validate_raw_bars(raw)
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    filt = policy["filter"]
    stream = ES.load_atlas_stream(out_path)
    surface, attrition = ES.build_surface(year, stream, raw, filt, is_rth, progress_window_counts)
    surface_runtime = time.time() - t1
    surface.to_parquet(WORK / f"surface_{year}.parquet", index=False)

    gaps = SMOKE.gap_scan(raw, threshold_s=300)
    gap_classes: dict[str, int] = {}
    suspicious = []
    for g in gaps:
        cls = classify_gap(g)
        gap_classes[cls] = gap_classes.get(cls, 0) + 1
        if cls == "SUSPICIOUS_INTRADAY":
            suspicious.append(g)

    surface_keys = (pd.MultiIndex.from_frame(surface[["regime_start_ns", "observation_time"]])
                    if len(surface) else pd.MultiIndex.from_arrays([[], []]))
    completeness = SMOKE.feature_completeness(out, surface_keys)
    policy_a = SMOKE.policy_a_feasibility(surface, raw, year)

    return {
        "year": year,
        "atlas_audit": atlas_audit,
        "surface_attrition": attrition,
        "surface_runtime_s": round(surface_runtime, 1),
        "surface_rows": len(surface),
        "raw_gaps_over_300s": len(gaps),
        "raw_gap_classes": gap_classes,
        "raw_gaps_top10": gaps[:10],
        "suspicious_intraday_gaps": suspicious,
        "feature_completeness": completeness,
        "policy_a_feasibility": policy_a,
        "policy_sha256": sha256_file(POLICY_PATH),
        "generator_sha256": {
            "build_5s_atlas_smoke": sha256_file(HERE / "build_5s_atlas_smoke.py"),
            "entry_surface": sha256_file(HERE / "entry_surface.py"),
            "smoke_2021_surface": sha256_file(HERE / "smoke_2021_surface.py"),
            "run_year_backfill": sha256_file(Path(__file__).resolve()),
        },
    }


def write_year_outputs(year: int, report: dict) -> None:
    a = report["atlas_audit"]
    att = report["surface_attrition"]
    pa = report["policy_a_feasibility"]

    (RESULTS / f"backfill_{year}_manifest.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8")

    counts = pd.DataFrame([{
        "year": year, "cadence": "5s",
        "atlas_rows": a["rows"], "atlas_regimes": a["distinct_regimes"],
        **{f"checkpoints_{k}": v for k, v in att["checkpoints"].items()},
        **{f"regimes_{k}": v for k, v in att["distinct_regimes"].items()},
        "seq1_candidates": pa.get("seq1_candidates", 0),
        "policy_a_labeled": pa.get("labeled", 0),
        "policy_a_errors": pa.get("label_errors", 0),
        "raw_gaps_over_300s": report["raw_gaps_over_300s"],
        "suspicious_intraday_gaps": len(report["suspicious_intraday_gaps"]),
    }])
    counts.to_csv(RESULTS / f"backfill_{year}_counts.csv", index=False)

    lines = [
        f"# {year} 5s-Cadence Short-RTH Entry Surface — Backfill",
        "",
        "## Atlas rebuild (Option A: 5s cadence, no legacy parity)",
        "",
        f"- Runtime: {a['build_runtime_s']}s",
        f"- Checkpoints: {a['rows']:,} across {a['distinct_regimes']:,} regimes",
        f"- Causal audit: {a['negative_excursion_cells']} negative excursion cells, "
        f"{a['running_mfe_monotonicity_violations']} MFE monotonicity violations, "
        f"{a['running_mae_monotonicity_violations']} MAE monotonicity violations",
        f"- Feature columns present: {a['feature_columns_present']} "
        f"(expected {len(CENTER_FEATS) + len(SEQUENCE_FEATS)})",
        "",
        "## Score-independent surface funnel (checkpoints / distinct regimes)",
        "",
        "| Stage | Checkpoints | Distinct regimes |",
        "|--|--:|--:|",
    ]
    for stage in ("all", "bullish_regime", "established", "rth", "valid_fill",
                  "rth_boundary_divergence"):
        lines.append(f"| {stage} | {att['checkpoints'][stage]:,} | "
                      f"{att['distinct_regimes'][stage]:,} |")
    lines += [
        "",
        f"Surface build runtime: {report['surface_runtime_s']}s",
        "",
        "## RTH boundary diagnostic (decision-time vs fill-time)",
        "",
        f"- Diverging checkpoints: {att['checkpoints']['rth_boundary_divergence']}",
        f"- Affected regimes: {att['distinct_regimes']['rth_boundary_divergence']}",
        "- Final surface uses fill-time classification (remediated convention, "
        "matches `run_ladder.py`).",
        "- These checkpoints are counted, not silently dropped or misclassified "
        "-- divergence does not change candidate eligibility because RTH is "
        "evaluated once, on `fill_ts`, at the point the row is (or isn't) "
        "admitted to the surface.",
        "",
        "## Missing-data gap scan (>300s)",
        "",
        f"- Total gaps: {report['raw_gaps_over_300s']}",
        f"- Classification: {report['raw_gap_classes']}",
    ]
    if report["suspicious_intraday_gaps"]:
        lines.append(f"- **SUSPICIOUS_INTRADAY gaps found: "
                      f"{len(report['suspicious_intraday_gaps'])}** -- review before trusting this year:")
        for g in report["suspicious_intraday_gaps"][:10]:
            lines.append(f"  - {g['gap_start']} -> {g['gap_end']} ({g['gap_s']:.0f}s)")
    else:
        lines.append("- No SUSPICIOUS_INTRADAY gaps found; all gaps classify as "
                      "daily maintenance breaks, weekends, or holidays.")
    lines += [
        "",
        "Top 10 gaps by duration:",
        "",
    ]
    for g in report["raw_gaps_top10"]:
        lines.append(f"  - {g['gap_start']} -> {g['gap_end']} ({g['gap_s']:.0f}s) "
                      f"[{classify_gap(g)}]")
    c = report["feature_completeness"]
    lines += [
        "",
        "## Feature completeness",
        "",
        f"- Expected feature columns: {c['expected_feature_columns']}, "
        f"present: {c['present_feature_columns']}",
        f"- Missing columns: {c['missing_feature_columns'] or 'none'}",
        f"- Overall NaN rate (all checkpoints): {c['overall_nan_rate']:.4f}",
        f"- Surface-row NaN rate: {c['surface_row_nan_rate']:.4f}",
        f"- Top-NaN columns: {c['top10_nan_rate_columns']}",
        "",
        "## Policy A label availability (seq-1-per-regime feasibility check)",
        "",
        f"- Seq-1 candidates: {pa.get('seq1_candidates', 0):,}",
        f"- Labeled successfully: {pa.get('labeled', 0):,}",
        f"- Label errors: {pa.get('label_errors', 0)}",
        f"- Exit-reason counts: {pa.get('exit_reason_counts', {})}",
        f"- Exit-reason PnL: {pa.get('exit_reason_pnl', {})}",
    ]
    if pa.get("labeled", 0):
        lines += [
            f"- pre_alignment_stop_rate: {pa['pre_alignment_stop_rate']:.4f}, "
            f"timeout_rate: {pa['timeout_rate']:.4f}, "
            f"post_alignment_stop_rate: {pa['post_alignment_stop_rate']:.4f}, "
            f"opposing_flip_rate: {pa['opposing_flip_rate']:.4f}",
            f"- Net PnL sum / mean (sanity check only, NOT a claimed result): "
            f"${pa['net_pnl_sum']:,.0f} / ${pa['net_pnl_mean']:,.2f}",
        ]
    else:
        lines.append("- exit-reason rates / PnL: n/a")
    (RESULTS / f"backfill_{year}_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True, choices=(2022, 2023, 2024))
    args = ap.parse_args()
    report = run_year(args.year)
    write_year_outputs(args.year, report)
    print(f"[{args.year}] done: {report['atlas_audit']['rows']:,} checkpoints, "
          f"{report['surface_rows']:,} surface rows, "
          f"{report['policy_a_feasibility'].get('label_errors', 'n/a')} label errors, "
          f"{len(report['suspicious_intraday_gaps'])} suspicious gaps")


if __name__ == "__main__":
    main()
