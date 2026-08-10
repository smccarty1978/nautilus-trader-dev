"""The eight SPEC 9 gates, executed and written machine-readable.

The predecessor study's `contract-checker` pass found validation asserted in
report prose and never reproducible. That is the failure mode this module
exists to prevent: every gate here runs, and `results/validation_report.json`
is the only thing the report is permitted to cite.

Gate 6 is deliberately an *independent recomputation* rather than a re-read of
the same arrays. It re-derives MAE-to-confirm straight from the canonical 1s
path parquet through a separate code path, so an error in `walks.py` cannot
validate itself.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.candidates import load_scored
from studies.model_driven_entry_exit_discovery.implementation.engine import (  # noqa: F401
    STORE,
    load_market,
    load_regimes,
)

from .arming import (
    ARM_LEVEL,
    LEVEL_SUFFIX,
    LEVELS,
    MIN_REGIME_AGE_S,
    arm_population,
    first_qualifying_population,
    load_observations,
    threshold_expr,
)
from .walks import STOP_ATR, measure_to_confirm

NS = 1_000_000_000
ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "studies/armed_fade_score_path_progression/results"

# From the accepted studies/model_driven_entry_exit_discovery/results/
# regime_lifecycle_600s.json -- the first-qualifying-after-600s population.
ACCEPTED_FIRST_QUALIFYING = {
    "top_1": 3415,
    "top_2_5": 5823,
    "top_5": 7396,
    "top_10": 8988,
}
MAE_SAMPLE_PER_LEVEL = 100
MAE_TOLERANCE = 1e-9


def gate_1_lifecycle_parity(scored: pl.DataFrame, arms: pl.DataFrame) -> dict:
    """Reproduce the accepted counts, and reconcile the arm-population delta.

    The arm rule (crossing from below) is a strict subset of the accepted
    first-qualifying rule. The delta is regimes whose score was *already* at or
    above Top-10 at their first post-600s dispatch, which the arm rule rejects
    by design. Reconciling it to an exact, explained number is the point --
    an unexplained delta between two populations is how a silent filter hides.
    """
    observed = {
        level: first_qualifying_population(scored, level).height for level in LEVELS
    }
    matches = observed == ACCEPTED_FIRST_QUALIFYING

    fq10 = first_qualifying_population(scored, ARM_LEVEL)
    fq_ids = set(fq10["regime_id"].to_list())
    arm_ids = set(arms["regime_id"].to_list())
    only_fq = fq_ids - arm_ids

    # Every excluded regime must be excluded for a documented reason. Both are
    # established by as-of join rather than by the positional shift that
    # `arm_population` uses, so the reconciliation is independent of the code it
    # is reconciling:
    #   (a) the predecessor dispatch already qualified -- no crossing occurred;
    #   (b) there is no predecessor at all -- the first in-domain dispatch of
    #       the regime was already above, so a rise from below was never seen.
    excluded = (
        fq10.filter(pl.col("regime_id").is_in(list(only_fq)))
        .select("regime_id", fq_ns=pl.col("checkpoint_decision_ns"))
        .sort("fq_ns")
    )
    universe = (
        scored.select(
            "regime_id", "checkpoint_decision_ns", "probability",
            "bullish_in_domain", "bearish_in_domain",
        )
        .with_columns(thr=threshold_expr(ARM_LEVEL))
        .select(
            "regime_id",
            prev_ns=pl.col("checkpoint_decision_ns"),
            prev_probability=pl.col("probability"),
            prev_thr=pl.col("thr"),
        )
        .sort("prev_ns")
    )
    reconciled = excluded.join_asof(
        universe,
        left_on="fq_ns",
        right_on="prev_ns",
        by="regime_id",
        strategy="backward",
        allow_exact_matches=False,
    ) if excluded.height else excluded.with_columns(
        prev_ns=pl.lit(None, dtype=pl.Int64),
        prev_probability=pl.lit(None, dtype=pl.Float64),
        prev_thr=pl.lit(None, dtype=pl.Float64),
    )

    no_predecessor = int(reconciled["prev_ns"].is_null().sum()) if reconciled.height else 0
    predecessor_already_above = (
        int(reconciled.filter(
            pl.col("prev_ns").is_not_null()
            & (pl.col("prev_probability") >= pl.col("prev_thr"))
        ).height)
        if reconciled.height else 0
    )
    unexplained = len(only_fq) - no_predecessor - predecessor_already_above

    return {
        "gate": "lifecycle_parity",
        "passed": bool(matches and unexplained == 0 and not (arm_ids - fq_ids)),
        "accepted_first_qualifying": ACCEPTED_FIRST_QUALIFYING,
        "observed_first_qualifying": observed,
        "counts_match": matches,
        "armed_population": len(arm_ids),
        "arm_is_subset_of_first_qualifying": not (arm_ids - fq_ids),
        "excluded_by_arm_rule": len(only_fq),
        "excluded_predecessor_already_qualified": predecessor_already_above,
        "excluded_no_predecessor_dispatch": no_predecessor,
        "excluded_unexplained": unexplained,
        "explanation": "the arm rule requires an observed crossing from below; "
                       "excluded regimes either had a predecessor that already "
                       "qualified, or had no predecessor dispatch at all",
        "method": "reconciled by as-of join, independent of the positional "
                  "shift used in arm_population",
    }


def gate_2_true_dispatch_cadence(scored: pl.DataFrame) -> dict:
    """No carried-forward second may be counted as a score observation.

    Structural, but verified rather than trusted: the score table must carry one
    row per (regime, decision ns) with no carry-forward column present at all,
    and its row count must equal the distinct dispatch count.

    Also asserts the observation stream is fully scored. An in-domain dispatch
    with a null probability is a dispatch but not an observation; it is dropped
    upstream in `load_observations`, and a survivor here would NaN-poison every
    running peak it touched.
    """
    raw = load_scored()
    unscored = int(raw["probability"].is_null().sum())
    nulls_in_stream = int(scored["probability"].is_null().sum())

    dup = scored.height - scored.select(
        pl.struct("regime_id", "checkpoint_decision_ns").n_unique()
    ).item()
    path_cols = pl.scan_parquet(
        STORE / "canonical_regime_paths_all.parquet"
    ).collect_schema().names()
    carry_lives_on_paths = "is_carried_forward" in path_cols
    carry_on_scores = "is_carried_forward" in scored.columns

    gaps = (
        scored.sort("checkpoint_decision_ns")
        .with_columns(
            dt=(pl.col("checkpoint_decision_ns")
                - pl.col("checkpoint_decision_ns").shift(1).over("regime_id")) / NS
        )["dt"].drop_nulls()
    )
    return {
        "gate": "true_dispatch_cadence",
        "passed": bool(
            dup == 0
            and carry_lives_on_paths
            and not carry_on_scores
            and nulls_in_stream == 0
        ),
        "in_domain_dispatches_raw": raw.height,
        "in_domain_dispatches_unscored": unscored,
        "score_observations": scored.height,
        "nulls_remaining_in_stream": nulls_in_stream,
        "duplicate_regime_timestamp_pairs": int(dup),
        "carry_forward_column_on_paths": carry_lives_on_paths,
        "carry_forward_column_on_scores": carry_on_scores,
        "modal_gap_s": float(gaps.mode().to_list()[0]) if gaps.len() else None,
        "gap_gt_5s_pct": round(100 * float((gaps > 5.0).mean()), 3) if gaps.len() else None,
    }


def gate_3_arm_definition(scored: pl.DataFrame, arms: pl.DataFrame) -> dict:
    """One arm per regime; every arm a genuine post-600s crossing from below.

    The from-below check is derived **independently** of `arm_population`. That
    matters: pass 1 of the audit flagged that recomputing `prev_q` with the same
    `shift(1).over(...)` expression over the same table can only ever agree with
    itself, so it verifies nothing. Here the predecessor is instead recovered by
    an as-of join -- for each arm, the latest dispatch in the same regime
    strictly before the arm timestamp -- and its probability is compared against
    the frozen threshold directly. A shift bug and a join bug do not share a
    failure mode.
    """
    one_per_regime = arms.height == arms["regime_id"].n_unique()
    all_old_enough = bool((arms["seconds_from_regime_start"] > MIN_REGIME_AGE_S).all())

    from .arming import THRESHOLDS
    bull, bear = THRESHOLDS[ARM_LEVEL]
    above = arms.with_columns(
        thr=pl.when(pl.col("bullish_in_domain")).then(pl.lit(bull)).otherwise(pl.lit(bear))
    )
    all_above = bool((above["probability"] >= above["thr"]).all())

    # Independent predecessor recovery: latest same-regime dispatch strictly
    # before the arm, found by as-of join rather than by positional shift.
    universe = (
        scored.select(
            "regime_id",
            "checkpoint_decision_ns",
            "probability",
            "bullish_in_domain",
            "bearish_in_domain",
        )
        .with_columns(thr=threshold_expr(ARM_LEVEL))
        .with_columns(prev_ns=pl.col("checkpoint_decision_ns"))
        .sort("checkpoint_decision_ns")
    )
    arm_keys = arms.select(
        "regime_id", arm_ns=pl.col("checkpoint_decision_ns")
    ).sort("arm_ns")
    predecessor = arm_keys.join_asof(
        universe.select(
            "regime_id",
            "prev_ns",
            prev_probability=pl.col("probability"),
            prev_thr=pl.col("thr"),
        ).sort("prev_ns"),
        left_on="arm_ns",
        right_on="prev_ns",
        by="regime_id",
        strategy="backward",
        allow_exact_matches=False,
    )

    missing_predecessor = int(predecessor["prev_ns"].is_null().sum())
    qualifying_predecessor = int(
        predecessor.filter(
            pl.col("prev_ns").is_not_null()
            & (pl.col("prev_probability") >= pl.col("prev_thr"))
        ).height
    )
    from_below = missing_predecessor == 0 and qualifying_predecessor == 0

    return {
        "gate": "arm_definition",
        "passed": bool(one_per_regime and all_old_enough and all_above and from_below),
        "armed_regimes": arms.height,
        "one_arm_per_regime": one_per_regime,
        "all_regime_age_gt_600s": all_old_enough,
        "all_at_or_above_top10": all_above,
        "all_crossings_from_below": from_below,
        "arms_without_a_predecessor_dispatch": missing_predecessor,
        "arms_whose_predecessor_already_qualified": qualifying_predecessor,
        "min_regime_age_s": float(arms["seconds_from_regime_start"].min()),
        "method": "predecessor recovered by as-of join, independent of the "
                  "positional shift used in arm_population",
    }


def gate_4_event_ordering(paths: pl.DataFrame) -> dict:
    """Event ordering, timestamp monotonicity, and walk agreement at Top-10."""
    valid = paths.filter(pl.col("valid"))
    checks: dict[str, int] = {}

    confirmed = valid.filter(pl.col("walk_a_confirm_reached_uncensored"))
    checks["confirm_before_arm"] = confirmed.filter(
        pl.col("walk_a_confirm_ns") < pl.col("arm_top10_ns")
    ).height

    # Threshold sequence timestamps must be non-decreasing. Not strictly
    # increasing: a dispatch that jumps several levels stamps them all with one
    # timestamp, so equality is correct and a strict test would fire on it.
    order = ["top10", "top5", "top2_5", "top1"]
    non_monotonic = 0
    multi_level_same_dispatch = 0
    for a, b in zip(order, order[1:]):
        pair = valid.filter(
            pl.col(f"{a}_ns").is_not_null() & pl.col(f"{b}_ns").is_not_null()
        )
        non_monotonic += pair.filter(pl.col(f"{b}_ns") < pl.col(f"{a}_ns")).height
        multi_level_same_dispatch += pair.filter(
            pl.col(f"{b}_ns") == pl.col(f"{a}_ns")
        ).height
    checks["non_monotonic_level_sequence"] = non_monotonic

    # A level cannot be reached before the arm that scopes it.
    for sfx in ("top5", "top2_5", "top1"):
        checks[f"{sfx}_before_arm"] = valid.filter(
            pl.col(f"{sfx}_ns").is_not_null()
            & (pl.col(f"{sfx}_ns") < pl.col("arm_top10_ns"))
        ).height

    # Censored survivors are bounded by the stop, by definition of the bound.
    checks["censored_mae_above_1atr"] = valid.filter(
        pl.col("walk_a_confirm_reached_censored")
        & (pl.col("walk_a_mae_to_confirm_atr") > STOP_ATR)
    ).height

    # Confirmed and stopped-before-confirm are mutually exclusive under the
    # conservative bound; a row satisfying both would mean the tie-break leaked.
    checks["confirmed_and_stopped"] = valid.filter(
        pl.col("walk_a_confirm_reached_censored") & pl.col("walk_a_stop_before_confirm")
    ).height

    # Walk B at Top-10 is the same measurement as Walk A by construction.
    both = valid.filter(
        pl.col("walk_a_mae_to_confirm_atr").is_not_null()
        & pl.col("walk_b_mae_to_confirm_atr_top10").is_not_null()
    )
    checks["walk_a_walk_b_top10_disagreements"] = both.filter(
        (pl.col("walk_a_mae_to_confirm_atr")
         - pl.col("walk_b_mae_to_confirm_atr_top10")).abs() > MAE_TOLERANCE
    ).height

    return {
        "gate": "event_ordering",
        "passed": all(v == 0 for v in checks.values()),
        "violations": checks,
        "multi_level_same_dispatch_pairs": multi_level_same_dispatch,
        "ambiguous_same_bar": int(valid["walk_a_ambiguous"].fill_null(False).sum()),
    }


def gate_5_session_containment(paths: pl.DataFrame, market) -> dict:
    """No path may traverse a session boundary.

    Only RTH bars are loaded, so index i+1 after 14:59:59 is the next session's
    08:30. A window that runs through that gap silently collects an overnight
    move -- in the predecessor study one such trade was the entire apparent edge.
    """
    valid = paths.filter(pl.col("valid") & pl.col("session_close_ns").is_not_null())
    over = valid.filter(pl.col("walk_a_terminal_ns") > pl.col("session_close_ns")).height
    confirm_over = valid.filter(
        pl.col("walk_a_confirm_reached_uncensored")
        & (pl.col("walk_a_confirm_ns") > pl.col("session_close_ns"))
    ).height
    level_over = 0
    for sfx in ("top5", "top2_5", "top1"):
        level_over += valid.filter(
            pl.col(f"{sfx}_ns").is_not_null()
            & (pl.col(f"{sfx}_ns") > pl.col("session_close_ns"))
        ).height
    return {
        "gate": "session_containment",
        "passed": bool(over == 0 and confirm_over == 0 and level_over == 0),
        "trades_checked": valid.height,
        "terminal_after_session_close": over,
        "confirm_after_session_close": confirm_over,
        "level_reach_after_session_close": level_over,
    }


def gate_6_mae_independent_recompute(paths: pl.DataFrame) -> dict:
    """Recompute MAE-to-confirm from the raw 1s parquet, by a separate path.

    Deterministic sample: the first `MAE_SAMPLE_PER_LEVEL` confirmed rows per
    level in `regime_id` order. No randomness, so the gate is reproducible.
    """
    lf = pl.scan_parquet(STORE / "canonical_regime_paths_all.parquet").select(
        "path_init_ns", "high", "low", "session"
    )
    results = {}
    all_pass = True
    for level in LEVELS:
        sfx = LEVEL_SUFFIX[level]
        sample = (
            paths.filter(
                pl.col("valid")
                & pl.col(f"walk_b_confirm_reached_uncensored_{sfx}")
                & pl.col(f"walk_b_mae_to_confirm_atr_{sfx}").is_not_null()
            )
            .sort("regime_id")
            .head(MAE_SAMPLE_PER_LEVEL)
        )
        if sample.height == 0:
            results[sfx] = {"n": 0, "mismatches": 0, "note": "no confirmed rows"}
            continue

        lo_ns = int(sample[f"{sfx}_ns"].min())
        hi_ns = int(sample["walk_a_confirm_ns"].fill_null(0).max())
        hi_ns = max(hi_ns, int(sample[f"{sfx}_ns"].max()) + 86_400 * NS)
        bars = (
            lf.filter(
                (pl.col("session") == "RTH")
                & (pl.col("path_init_ns") > lo_ns)
                & (pl.col("path_init_ns") <= hi_ns)
            )
            .sort("path_init_ns")
            .unique(subset=["path_init_ns"], keep="first")
            .collect()
        )
        ts = bars["path_init_ns"].to_numpy()
        hi_arr = bars["high"].to_numpy()
        lo_arr = bars["low"].to_numpy()

        mismatches = 0
        checked = 0
        for row in sample.iter_rows(named=True):
            entry_ns = int(row[f"{sfx}_ns"])
            # Walk B's confirming flip, recovered from its own recorded seconds.
            secs = row[f"walk_b_seconds_to_confirm_{sfx}"]
            if secs is None:
                continue
            confirm_ns = entry_ns + int(round(float(secs) * NS))
            a = int(np.searchsorted(ts, entry_ns, side="right"))
            b = int(np.searchsorted(ts, confirm_ns, side="right"))
            if b <= a:
                continue
            price = float(row[f"price_at_{sfx}"])
            atr = float(row[f"atr_at_{sfx}"])
            direction = int(row["direction"])
            adverse = (
                (price - lo_arr[a:b]) if direction > 0 else (hi_arr[a:b] - price)
            )
            recomputed = float(np.maximum(adverse, 0.0).max() / atr)
            checked += 1
            if abs(recomputed - float(row[f"walk_b_mae_to_confirm_atr_{sfx}"])) > 1e-6:
                mismatches += 1
        results[sfx] = {"n": checked, "mismatches": mismatches}
        all_pass = all_pass and mismatches == 0 and checked > 0

    return {
        "gate": "mae_independent_recompute",
        "passed": bool(all_pass),
        "sample_per_level": MAE_SAMPLE_PER_LEVEL,
        "by_level": results,
        "method": "re-derived from canonical_regime_paths_all.parquet via a "
                  "separate code path, not by re-reading walks.py arrays",
    }


def gate_7_assertions(paths: pl.DataFrame) -> dict:
    """The SPEC 9 assertions, as executed checks rather than prose."""
    valid = paths.filter(pl.col("valid"))
    checks = {}
    for level in LEVELS:
        sfx = LEVEL_SUFFIX[level]
        conf = valid.filter(pl.col(f"walk_b_confirm_reached_uncensored_{sfx}"))
        checks[f"confirm_before_entry_{sfx}"] = conf.filter(
            pl.col(f"walk_b_seconds_to_confirm_{sfx}") < 0
        ).height
        cen = valid.filter(pl.col(f"walk_b_confirm_reached_censored_{sfx}"))
        checks[f"censored_mae_above_1atr_{sfx}"] = cen.filter(
            pl.col(f"walk_b_mae_to_confirm_atr_{sfx}") > STOP_ATR
        ).height
        checks[f"negative_elapsed_to_{sfx}"] = valid.filter(
            pl.col(f"seconds_top10_to_{sfx}").is_not_null()
            & (pl.col(f"seconds_top10_to_{sfx}") < 0)
        ).height
    checks["shape_class_null"] = valid.filter(
        pl.col("shape_class_0_05").is_null()
    ).height
    checks["deeper_reached_without_shallower"] = valid.filter(
        pl.col("top1_reached") & ~pl.col("top2_5_reached")
    ).height + valid.filter(
        pl.col("top2_5_reached") & ~pl.col("top5_reached")
    ).height
    return {
        "gate": "assertions",
        "passed": all(v == 0 for v in checks.values()),
        "violations": checks,
    }


def gate_8_audit_gates() -> dict:
    """Read the audit gates' machine-readable verdicts. Never prose."""
    audit = ROOT / "studies/armed_fade_score_path_progression/audit"
    out = {"gate": "audit_gates"}
    for name, path in (
        ("causal_lint", audit / "lint.json"),
        ("lookahead_auditor", audit / "status.json"),
        ("contract_checker", audit / "contract_status.json"),
    ):
        if path.exists():
            payload = json.loads(path.read_text())
            out[name] = payload
        else:
            out[name] = {"present": False}
    verdicts = []
    for key in ("lookahead_auditor", "contract_checker"):
        payload = out.get(key, {})
        verdict = str(payload.get("verdict", payload.get("status", ""))).upper()
        # Both gates emit a clean verdict as either PASS or CLEAR depending on
        # the agent definition; a nonzero CRITICAL count is disqualifying either
        # way, so it is checked independently rather than trusted to the label.
        verdicts.append(
            verdict in ("CLEAR", "PASS") and int(payload.get("critical", 0) or 0) == 0
        )
    lint = out.get("causal_lint", {})
    lint_clean = lint.get("critical", lint.get("critical_count", 1)) in (0, "0")
    out["passed"] = bool(all(verdicts) and lint_clean)
    return out


def main() -> None:
    print("loading substrate for validation ...", flush=True)
    scored = load_observations()
    market = load_market()
    arms = arm_population(scored)
    paths = pl.read_parquet(RESULTS / "armed_regime_score_paths.parquet")

    gates = [
        gate_1_lifecycle_parity(scored, arms),
        gate_2_true_dispatch_cadence(scored),
        gate_3_arm_definition(scored, arms),
        gate_4_event_ordering(paths),
        gate_5_session_containment(paths, market),
        gate_6_mae_independent_recompute(paths),
        gate_7_assertions(paths),
        gate_8_audit_gates(),
    ]
    report = {
        "all_passed": all(g["passed"] for g in gates),
        "gates": {g["gate"]: g for g in gates},
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "validation_report.json").write_text(
        json.dumps(report, indent=2, default=str)
    )
    for g in gates:
        print(f"  {'PASS' if g['passed'] else 'FAIL'}  {g['gate']}", flush=True)
    print(f"\nall_passed = {report['all_passed']}")


if __name__ == "__main__":
    main()
