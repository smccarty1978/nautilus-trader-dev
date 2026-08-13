"""Phase 3/4 — candidate triggers and their trade evaluation.

Every rule is a query over the cached post-arm stream. A trigger fires at the
FIRST post-arm true dispatch satisfying it, using only columns that are causal at
that dispatch (running maxima are expanding; persistence counts true dispatches).

The armed regime bounds every trigger structurally: post-arm rows carry the old
regime's id, so nothing can fire at or after the confirming flip.

Trade evaluation reuses the accepted `measure_to_confirm` primitive, which
anchors the 1 ATR stop at the CANDIDATE entry price with the CANDIDATE's own
frozen ATR -- the arm's stop is not carried forward (SPEC 1).
"""
from __future__ import annotations

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    NS, load_market, load_regimes,
)
from studies.armed_fade_score_path_progression.implementation.walks import (
    measure_to_confirm,
)
from .paths import INTERPOLATED, LEVELS

# ------------------------------------------------------------- baselines
# Fixed thresholds, measured AFTER arming. Not discoveries (SPEC 2).
BASELINES = {
    "A_IMMEDIATE_TOP10": pl.col("obs_index") == 0,
    "B_FIRST_TOP5": pl.col("ge_top_5"),
    "C_FIRST_TOP2_5": pl.col("ge_top_2_5"),
    "D_FIRST_TOP1": pl.col("ge_top_1"),
}

# --------------------------------------------------- discovered candidates
# Cap 8 (SPEC 3), nominated from Phase 2 evidence. Family E (fast progression)
# is deliberately NOT nominated: slope AUC peaked at 0.62-0.67 with heavy
# coverage gaps (slope_60s unusable at every landmark) and DECLINED with elapsed
# time, so timing did not earn a slot against better-supported families.
CANDIDATES = {
    # Family A -- intermediate INTERPOLATED levels (NOT percentiles).
    "A1_INTERP_L1": pl.col("ge_INTERP_L1"),
    "A2_INTERP_L2": pl.col("ge_INTERP_L2"),
    # Family B -- persistence in true dispatches above Top-10.
    "B1_PERSIST_TOP10_x2": pl.col("consec_top_10") >= 2,
    "B2_PERSIST_TOP10_x3": pl.col("consec_top_10") >= 3,
    # Family C -- score progression above the arm score.
    "C1_PROGRESS_0_03": pl.col("delta_from_arm") >= 0.03,
    "C2_PROGRESS_0_06": pl.col("delta_from_arm") >= 0.06,
    # Family D -- retreat then re-expansion to a new post-arm high.
    "D1_REEXPANSION_0_05": pl.col("reexpanded_0_05"),
    # Family F -- one hybrid: persistence AND an intermediate level. Both
    # components separate independently in Phase 2.
    "F1_PERSIST_x2_AT_INTERP_L2": (pl.col("consec_INTERP_L2") >= 2),
}
ALL_RULES = {**BASELINES, **CANDIDATES}


def with_reexpansion(stream: pl.DataFrame, retreat: float) -> pl.DataFrame:
    """Flag the first dispatch that sets a new post-arm high AFTER a retreat.

    Causal: the retreat must already have occurred at or before the flagged bar,
    and the new high is compared against the running max of PRIOR observations.
    """
    tag = f"{retreat:.2f}".replace(".", "_")
    prev_max = pl.col("score").shift(1).cum_max().over("regime_id")
    had_retreat = (
        ((pl.col("score_running_max") - pl.col("score")) >= retreat)
        .cum_sum().over("regime_id").shift(1, fill_value=0) > 0
    )
    return stream.with_columns(**{
        f"reexpanded_{tag}": had_retreat & (pl.col("score") > prev_max)
    })


def first_firings(stream: pl.DataFrame, name: str, cond: pl.Expr) -> pl.DataFrame:
    """First post-arm dispatch satisfying `cond`, one row per armed regime."""
    return (
        stream.filter(cond)
        .sort("checkpoint_decision_ns")
        .group_by("regime_id")
        .first()
        .select(
            "regime_id", "direction", "side", "entry_year",
            "arm_ns", "arm_price", "arm_atr", "arm_score", "arm_outcome",
            "arm_stop_ns",
            entry_ns="checkpoint_decision_ns",
            entry_price="checkpoint_reference_price",
            entry_atr="atr_at_checkpoint",
            entry_score="score",
            entry_obs_index="obs_index",
        )
        .with_columns(
            rule=pl.lit(name),
            seconds_arm_to_entry=((pl.col("entry_ns") - pl.col("arm_ns")) / NS),
            price_move_arm_to_entry_atr=(
                (pl.col("entry_price") - pl.col("arm_price"))
                * pl.col("direction") / pl.col("arm_atr")
            ),
            # Fairness disclosure (SPEC 1.1): did the arm-anchored path already
            # take a 1 ATR hit before this trigger fired? Immediate Top-10 would
            # have been stopped there; this candidate gets a second life.
            entered_after_arm_1atr_adverse=(
                pl.col("arm_stop_ns").is_not_null()
                & (pl.col("entry_ns") >= pl.col("arm_stop_ns"))
            ),
        )
        .sort("entry_ns")
    )


def evaluate(entries: pl.DataFrame) -> pl.DataFrame:
    """Walk each candidate trade with its OWN entry price, ATR and 1 ATR stop."""
    market, regimes = load_market(), load_regimes()
    rows = []
    for r in entries.iter_rows(named=True):
        m = measure_to_confirm(
            market, regimes, int(r["entry_ns"]), int(r["direction"]),
            r["entry_price"], r["entry_atr"],
        )
        if not m.get("valid"):
            continue
        rows.append({
            **{k: r[k] for k in (
                "rule", "regime_id", "direction", "side", "entry_year",
                "arm_ns", "arm_score", "arm_outcome", "entry_ns", "entry_price",
                "entry_atr", "entry_score", "entry_obs_index",
                "seconds_arm_to_entry", "price_move_arm_to_entry_atr",
                "entered_after_arm_1atr_adverse")},
            "confirmed": bool(m["confirm_reached_censored"]),
            "stopped_before_confirm": bool(m["stop_before_confirm"]),
            "session_unresolved": bool(m["session_close_unresolved"]),
            "ambiguous": bool(m["ambiguous"]),
            "seconds_entry_to_confirm": m.get("seconds_to_confirm"),
            "return_at_confirm_atr": m.get("return_at_confirm_atr"),
            "mfe_to_confirm_atr": m.get("mfe_to_confirm_atr"),
            "mae_to_confirm_atr": m.get("mae_to_confirm_atr"),
            "net_return_at_confirm_atr": m.get("net_return_at_confirm_atr"),
            "terminal_label": m["terminal_label"],
            "gross_atr": m["gross_atr"],
            "net_atr": m["net_atr"],
        })
    return pl.DataFrame(rows, infer_schema_length=None)
