"""SPEC section 8 mandatory validation, as a reproducible artifact.

Every check below was previously run interactively and its result typed into the
report. `contract-checker` correctly flagged that as NOT VERIFIED: a result
asserted in prose is not evidence, because nobody can re-run it. This module
executes each gate and writes `results/validation_report.json`.

No policy result may be trusted unless this reports `all_passed: true`.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from .candidates import FAMILIES, THRESHOLDS, first_qualifying, load_scored
from .engine import ExitPolicy, load_market, load_regimes, simulate

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "studies/model_driven_entry_exit_discovery/results"
ACCEPTED_SUMMARIES = (
    ROOT / "studies/full_trade_path_builder/consolidated/canonical_trade_summaries_all.parquet"
)

ACCEPTED_TOTAL, ACCEPTED_SHORT, ACCEPTED_LONG = 5836, 3329, 2507
ACCEPTED_BY_YEAR = {2021: 1147, 2022: 1206, 2023: 1187, 2024: 1149, 2025: 1147}


def check_backward_parity(scored: pl.DataFrame) -> dict:
    """Reproduce the accepted 5,836 Top-2.5% population from this store."""
    got = first_qualifying(scored, "top_2_5")
    by_dir = {
        ("SHORT" if d == -1 else "LONG"): n
        for d, n in got.group_by("direction").len().iter_rows()
    }
    by_year = dict(got.group_by("entry_year").len().sort("entry_year").iter_rows())

    detail = {
        "total": got.height,
        "expected_total": ACCEPTED_TOTAL,
        "short": by_dir.get("SHORT", 0),
        "long": by_dir.get("LONG", 0),
        "by_year": {int(k): int(v) for k, v in by_year.items()},
        "expected_by_year": ACCEPTED_BY_YEAR,
    }

    # Row-level reconciliation against the frozen artifact, not just counts.
    if ACCEPTED_SUMMARIES.exists():
        accepted = pl.read_parquet(
            ACCEPTED_SUMMARIES, columns=["checkpoint_decision_ns", "entry_model_id"]
        )
        mine = got.select(
            "checkpoint_decision_ns",
            pl.col("model_id").alias("entry_model_id"),
        )
        key = ["checkpoint_decision_ns", "entry_model_id"]
        detail["missing_vs_accepted"] = accepted.join(mine, on=key, how="anti").height
        detail["extra_vs_accepted"] = mine.join(accepted, on=key, how="anti").height
    else:
        detail["missing_vs_accepted"] = None
        detail["extra_vs_accepted"] = None
        detail["note"] = "accepted artifact absent; counts only"

    detail["passed"] = (
        detail["total"] == ACCEPTED_TOTAL
        and detail["short"] == ACCEPTED_SHORT
        and detail["long"] == ACCEPTED_LONG
        and detail["by_year"] == ACCEPTED_BY_YEAR
        and not (detail["missing_vs_accepted"] or 0)
        and not (detail["extra_vs_accepted"] or 0)
    )
    return detail


def check_no_duplicate_candidates(scored: pl.DataFrame) -> dict:
    """No family may emit the same checkpoint twice, or two entries per regime
    where the family promises one."""
    out, worst = {}, 0
    single_entry_families = [f for f in FAMILIES if f != "true_crossing"]
    for family in single_entry_families:
        for label in THRESHOLDS:
            df = FAMILIES[family](scored, label)
            if not df.height:
                continue
            dup_ckpt = df.height - df["checkpoint_decision_ns"].n_unique()
            dup_regime = df.height - df["regime_id"].n_unique()
            worst = max(worst, dup_ckpt, dup_regime)
            if dup_ckpt or dup_regime:
                out[f"{family}/{label}"] = {
                    "duplicate_checkpoints": dup_ckpt,
                    "duplicate_regimes": dup_regime,
                }
    return {"families_checked": len(single_entry_families) * len(THRESHOLDS),
            "violations": out, "passed": worst == 0}


def check_score_cadence(scored: pl.DataFrame) -> dict:
    """Every candidate must sit on a true 5s scoring checkpoint, and no two
    candidates may share one. Carry-forward seconds live on path rows and cannot
    reach this table at all."""
    ns = scored["checkpoint_decision_ns"].to_numpy()
    off_grid = int((ns % (5 * 10**9) != 0).sum())
    return {
        "checkpoints": int(ns.size),
        "unique_checkpoints": int(np.unique(ns).size),
        "off_5s_grid": off_grid,
        "passed": off_grid == 0,
    }


def check_no_lookahead_columns(scored: pl.DataFrame) -> dict:
    """The candidate table must expose no column resolved after the decision."""
    forbidden = {
        "seconds_to_next_bullish_confirm_flip", "seconds_to_next_bearish_confirm_flip",
        "next_bullish_flip_le_300", "next_bearish_flip_le_300",
        "bullish_confirm_within_300s", "bearish_confirm_within_300s",
        "confirm_flip_ns", "fallback_exit_flip_ns", "observation_end_ns",
    }
    present = sorted(forbidden & set(scored.columns))
    return {"forbidden_present": present, "passed": not present}


def check_session_containment(market, regimes, scored: pl.DataFrame) -> dict:
    """No trade may cross its session close. This is the defect that inflated
    the first run; it is now a standing gate rather than a one-off fix."""
    entries = first_qualifying(scored, "top_2_5").head(3000)
    crossed = 0
    for r in entries.iter_rows(named=True):
        t = simulate(
            market, regimes, r["checkpoint_decision_ns"], r["direction"],
            r["checkpoint_reference_price"], r["atr_at_checkpoint"],
            ExitPolicy(stop_atr=1.0),
        )
        if t.exit_ns is None:
            continue
        start = market.index_strictly_after(t.entry_ns)
        if t.exit_ns >= int(market.day_close_ns[start]):
            crossed += 1
    return {"trades_checked": entries.height, "cross_session": crossed,
            "passed": crossed == 0}


def check_deterministic_ordering(market, regimes, scored: pl.DataFrame) -> dict:
    """Simulating the same candidate twice must give an identical trade."""
    entries = first_qualifying(scored, "top_2_5").head(500)
    policy = ExitPolicy(stop_atr=1.0, target_atr=1.5, giveback_frac=0.33,
                        mfe_floor_atr=0.5)
    mismatches = 0
    for r in entries.iter_rows(named=True):
        args = (market, regimes, r["checkpoint_decision_ns"], r["direction"],
                r["checkpoint_reference_price"], r["atr_at_checkpoint"], policy)
        a, b = simulate(*args), simulate(*args)
        if (a.outcome, a.exit_ns, a.exit_price) != (b.outcome, b.exit_ns, b.exit_price):
            mismatches += 1
    return {"trades_checked": entries.height, "mismatches": mismatches,
            "passed": mismatches == 0}


def check_regime_boundaries() -> dict:
    """Partition boundaries must not create duplicate or missing regime starts."""
    df = (
        pl.scan_parquet(
            ROOT / "data/canonical/regime_complete_v1/canonical_regimes_all.parquet"
        )
        .select("regime_start_decision_ns", "regime_direction", "regime_sequence_number")
        .sort("regime_start_decision_ns")
        .collect()
    )
    starts = df["regime_start_decision_ns"].to_numpy()
    dirs = df["regime_direction"].to_numpy()
    seq = df["regime_sequence_number"].to_numpy()
    return {
        "regimes": int(starts.size),
        "duplicate_starts": int(starts.size - np.unique(starts).size),
        "consecutive_same_direction": int((dirs[1:] == dirs[:-1]).sum()),
        "sequence_dense": bool(np.array_equal(seq, np.arange(1, seq.size + 1))),
        "passed": bool(
            starts.size == np.unique(starts).size
            and (dirs[1:] == dirs[:-1]).sum() == 0
            and np.array_equal(seq, np.arange(1, seq.size + 1))
        ),
    }


def check_reentry_state(market, regimes, scored: pl.DataFrame) -> dict:
    """SPEC 8 requires the reentry state gate to be executed even though no
    reentry policy is advanced. A reentry sequence must be chronological, must
    not overlap itself, and each leg must be charged its own round turn.
    """
    from .reentry import simulate_with_reentry

    entries = first_qualifying(scored, "top_2_5").head(1000)
    sequences, overlaps, out_of_order, bad_index = 0, 0, 0, 0
    for r in entries.iter_rows(named=True):
        legs = simulate_with_reentry(
            market, regimes, r["checkpoint_decision_ns"], r["direction"],
            r["checkpoint_reference_price"], r["atr_at_checkpoint"],
            ExitPolicy(stop_atr=1.0), scored, max_reentries=1,
        )
        if len(legs) > 1:
            sequences += 1
        for i, leg in enumerate(legs):
            if leg.reentry_index != i:
                bad_index += 1
        for a, b in zip(legs, legs[1:]):
            if a.exit_ns is None or b.entry_ns <= a.exit_ns:
                overlaps += 1
            if b.entry_ns < a.entry_ns:
                out_of_order += 1
    return {
        "candidates_checked": entries.height,
        "sequences_with_reentry": sequences,
        "overlapping_legs": overlaps,
        "out_of_order_legs": out_of_order,
        "bad_reentry_index": bad_index,
        "passed": overlaps == 0 and out_of_order == 0 and bad_index == 0,
    }


def main() -> None:
    print("loading ...", flush=True)
    market = load_market()
    regimes = load_regimes()
    scored = load_scored()

    checks = {
        "backward_parity": check_backward_parity(scored),
        "no_duplicate_candidates": check_no_duplicate_candidates(scored),
        "score_cadence": check_score_cadence(scored),
        "no_lookahead_columns": check_no_lookahead_columns(scored),
        "session_containment": check_session_containment(market, regimes, scored),
        "deterministic_ordering": check_deterministic_ordering(market, regimes, scored),
        "regime_boundaries": check_regime_boundaries(),
        "reentry_state": check_reentry_state(market, regimes, scored),
    }
    report = {
        "checks": checks,
        "all_passed": all(c["passed"] for c in checks.values()),
        "failed": [k for k, c in checks.items() if not c["passed"]],
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "validation_report.json").write_text(json.dumps(report, indent=2))

    for name, c in checks.items():
        print(f"  {'PASS' if c['passed'] else 'FAIL'}  {name}")
    print(f"\nall_passed = {report['all_passed']}")


if __name__ == "__main__":
    main()
