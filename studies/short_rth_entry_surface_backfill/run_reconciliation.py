"""2025-2026 reconciliation smoke for the score-independent short-RTH entry
surface (`entry_surface.py`).

Proves the new established/RTH/prevailing-bullish surface builder is a
strict causal superset of the known W4-threshold-crossing candidate
population (650 candidates in 2025, 222 in 2026, per
`fable5_short_rth_threshold_ladder`), *before* touching 2021-2024. Does not
train, select, or optimize anything. Does not use the frozen W4 score to
build the surface itself -- the score is used here only as a reconciliation
overlay against the already-audited crossing logic, exactly as approved.

See studies/short_rth_entry_surface_backfill/SPEC.md.
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
RESULTS, AUDIT = HERE / "results", HERE / "audit"
for d in (RESULTS, AUDIT):
    d.mkdir(parents=True, exist_ok=True)

for p in (HERE,
          ROOT / "studies" / "fable5_short_rth_threshold_ladder",
          ROOT / "studies" / "fable5_specialized_w4",
          ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair",
          ROOT / "studies" / "regime_sequence_chop_context"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import entry_surface as ES  # noqa: E402
from CODEX_5_X_common import RAW_1S, year_atlas_path, sha256_file  # noqa: E402
from CODEX_5_X_run_established_fade import (  # noqa: E402
    is_rth, progress_window_counts, validate_raw_bars,
)
import run_ladder as LADDER  # noqa: E402

POLICY_PATH = (ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
               / "CODEX_5_X_established_fade_policy.json")
YEARS = (2025, 2026)


def reconcile_year(year: int, policy: dict, filt: dict) -> dict:
    t0 = time.time()
    raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close", "volume"])
    validate_raw_bars(raw)

    # --- score-independent surface (this study's actual deliverable) ---
    stream_no_score = ES.load_atlas_stream(year_atlas_path(year))
    surface, attrition = ES.build_surface(
        year, stream_no_score, raw, filt, is_rth, progress_window_counts)
    surface["year"] = year

    # --- crossing-based comparator, reusing run_ladder.py verbatim ---
    # This is the ONLY place the frozen W4 score is touched, and only for
    # 2025-2026 reconciliation -- never as a surface-generation input.
    stream_with_score = LADDER.load_checkpoint_stream(year, policy)
    crossing = LADDER.generate_entries(year, raw, stream_with_score, LADDER.CONTROL, filt)
    try:
        gate = LADDER.gate_candidate(year, crossing)
        gate_error = None
    except (RuntimeError, AssertionError) as exc:
        gate = None
        gate_error = str(exc)

    # --- per-row reconciliation: every crossing checkpoint must appear in
    # the score-independent surface, established+RTH+valid, with identical
    # fill identity. ---
    surf_idx = surface.set_index(["regime_start_ns", "observation_time"])
    missing, mismatched = [], []
    for c in crossing.itertuples(index=False):
        key = (int(c.regime_start_ns), int(c.signal_decision_ts))
        if key not in surf_idx.index:
            missing.append(key)
            continue
        row = surf_idx.loc[key]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        if (int(row["fill_ts"]) != int(c.entry_fill_ts)
                or not np.isclose(row["fill_px"], c.entry_px, rtol=0, atol=1e-9)
                or not np.isclose(row["atr_at_checkpoint"], c.atr_at_checkpoint,
                                   rtol=0, atol=1e-12)):
            mismatched.append(key)

    expected = LADDER.YEAR_CAND_COUNT[year]
    report = {
        "year": year,
        "expected_control": expected,
        "crossing_candidates": len(crossing),
        "gate_result": gate,
        "gate_error": gate_error,
        "missing_from_surface": len(missing),
        "missing_keys_sample": missing[:5],
        "mismatched_identity": len(mismatched),
        "mismatched_keys_sample": mismatched[:5],
        "runtime_s": round(time.time() - t0, 1),
        "attrition": attrition,
    }
    return report, surface


def main() -> str:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    filt = policy["filter"]

    reports, surfaces, counts_rows = {}, [], []
    for year in YEARS:
        report, surface = reconcile_year(year, policy, filt)
        reports[year] = report
        surfaces.append(surface)
        row = {"year": year, "crossing_candidates": report["crossing_candidates"],
               "expected_control": report["expected_control"]}
        row.update({f"checkpoints_{k}": v for k, v in report["attrition"]["checkpoints"].items()})
        row.update({f"regimes_{k}": v for k, v in report["attrition"]["distinct_regimes"].items()})
        counts_rows.append(row)

    surface_all = pd.concat(surfaces, ignore_index=True)
    counts_df = pd.DataFrame(counts_rows)

    overall_pass = all(
        reports[y]["crossing_candidates"] == reports[y]["expected_control"]
        and reports[y]["gate_error"] is None
        and reports[y]["missing_from_surface"] == 0
        and reports[y]["mismatched_identity"] == 0
        for y in YEARS
    )
    decision = "BACKFILL_RECONCILIATION_PASS" if overall_pass else "BACKFILL_RECONCILIATION_FAIL"

    surface_all.to_parquet(RESULTS / "reconciliation_2025_2026_surface.parquet", index=False)
    counts_df.to_csv(RESULTS / "reconciliation_2025_2026_counts.csv", index=False)

    manifest = {
        "decision": decision,
        "reports": reports,
        "policy_sha256": sha256_file(POLICY_PATH),
        "atlas_sha256": {str(y): sha256_file(year_atlas_path(y)) for y in YEARS},
        "raw_sha256": {str(y): sha256_file(RAW_1S[y]) for y in YEARS},
        "generator_sha256": sha256_file(HERE / "entry_surface.py"),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
    }
    (RESULTS / "reconciliation_2025_2026_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    lines = [
        "# 2025-2026 Short-RTH Entry Surface — Reconciliation Smoke",
        "",
        f"## Decision: `{decision}`",
        "",
        "Score-independent surface builder (`entry_surface.py`) reconciled ",
        "against the known W4-threshold-crossing candidate population.",
        "",
        "| Year | Crossing candidates | Expected control | Gate | Missing from surface | Mismatched identity |",
        "|--|--:|--:|--|--:|--:|",
    ]
    for y in YEARS:
        r = reports[y]
        gate_str = "PASS" if r["gate_error"] is None else f"FAIL: {r['gate_error']}"
        lines.append(f"| {y} | {r['crossing_candidates']} | {r['expected_control']} | "
                      f"{gate_str} | {r['missing_from_surface']} | {r['mismatched_identity']} |")
    lines += ["", "## Attrition (checkpoints / distinct regimes)", ""]
    for y in YEARS:
        a = reports[y]["attrition"]
        lines.append(f"### {y}")
        lines.append("")
        lines.append("| Stage | Checkpoints | Distinct regimes |")
        lines.append("|--|--:|--:|")
        for stage in ("all", "bullish_regime", "established", "rth", "valid_fill",
                      "rth_boundary_divergence"):
            lines.append(f"| {stage} | {a['checkpoints'][stage]} | {a['distinct_regimes'][stage]} |")
        lines.append("")
    lines += [
        "## Runtime",
        "",
        *[f"- {y}: {reports[y]['runtime_s']}s" for y in YEARS],
        "",
        "## Notes",
        "",
        "- The surface builder never reads a W4 score. The crossing "
        "comparator reads the frozen score for 2025-2026 only, purely to "
        "prove the surface contains every known crossing opportunity with "
        "identical fill identity (ts/px/ATR).",
        "- `gate_candidate` (imported unmodified from "
        "`fable5_short_rth_threshold_ladder/run_ladder.py`) independently "
        "checks the crossing population itself against the audited "
        "multi-candidate-reentry 650/222 population.",
    ]
    (RESULTS / "reconciliation_2025_2026_summary.md").write_text(
        "\n".join(lines), encoding="utf-8")

    print("DECISION:", decision)
    print(counts_df.to_string(index=False))
    for y in YEARS:
        print(f"\n--- {y} ---")
        print(json.dumps(reports[y], indent=2, default=str))
    return decision


if __name__ == "__main__":
    main()
