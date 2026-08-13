"""Cached post-arm score stream + Phase 1 diagnostics. Built once, queried often.

Everything downstream — every candidate trigger, the separation analysis, the
frontier — is a query over the two artifacts this module writes. No candidate
rule re-reads the score store.

Two things here are load-bearing:

* **True dispatches only.** The observation stream is `load_observations()` from
  the accepted arming module, which drops the ~8% of in-domain dispatches that
  carry a null probability. A null is not evidence of a score level, and it
  NaN-poisons every running maximum it touches.
* **The armed regime bounds everything.** Post-arm score rows carry the *old*
  regime's `regime_id`, so a trigger structurally cannot fire at or after the
  confirming flip. That is why the arm needs no explicit cancel (SPEC 1.1).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.candidates import THRESHOLDS
from studies.model_driven_entry_exit_discovery.implementation.engine import (
    NS, load_market, load_regimes,
)
from studies.armed_fade_score_path_progression.implementation.arming import (
    ARM_LEVEL, MIN_REGIME_AGE_S, arm_population, load_observations,
)

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "studies/top10_armed_entry_refinement/results"

ARMED_REQUIRED = 8950
STOP_ATR = 1.0
SLOPE_WINDOWS_S = (10, 20, 30, 60)
LANDMARK_TIMES_S = (5, 10, 15, 20, 30, 45, 60)

# Interpolated research levels (SPEC 1.2). NOT percentiles, NOT contracts.
# Arithmetic between two already-frozen contract values; no calibration data.
def _interp(frac: float) -> tuple[float, float]:
    b10, r10 = THRESHOLDS["top_10"]
    b5, r5 = THRESHOLDS["top_5"]
    return (b10 + (b5 - b10) * frac, r10 + (r5 - r10) * frac)


INTERP_L1 = _interp(1 / 3)
INTERP_L2 = _interp(1 / 2)
LEVELS = {
    "top_10": THRESHOLDS["top_10"],
    "INTERP_L1": INTERP_L1,
    "INTERP_L2": INTERP_L2,
    "top_5": THRESHOLDS["top_5"],
    "top_2_5": THRESHOLDS["top_2_5"],
    "top_1": THRESHOLDS["top_1"],
}
INTERPOLATED = ("INTERP_L1", "INTERP_L2")

SUCCESS, FAILURE, SESSION = "SUCCESS", "FAILURE", "SESSION"


def level_expr(name: str) -> pl.Expr:
    bull, bear = LEVELS[name]
    return pl.when(pl.col("bullish_in_domain")).then(pl.lit(bull)).otherwise(pl.lit(bear))


def build_stream() -> pl.DataFrame:
    """One row per post-arm true dispatch, with causal running state attached."""
    scored = load_observations()
    arms = arm_population(scored)
    if arms.height != ARMED_REQUIRED:
        raise RuntimeError(f"armed population {arms.height} != {ARMED_REQUIRED}")

    keys = arms.select(
        "regime_id",
        arm_ns="checkpoint_decision_ns",
        arm_score="probability",
        arm_price="checkpoint_reference_price",
        arm_atr="atr_at_checkpoint",
        arm_age_s="seconds_from_regime_start",
    )
    s = (
        scored.join(keys, on="regime_id", how="inner")
        .filter(pl.col("checkpoint_decision_ns") >= pl.col("arm_ns"))
        .sort(["regime_id", "checkpoint_decision_ns"])
        .with_columns(
            elapsed_s=((pl.col("checkpoint_decision_ns") - pl.col("arm_ns")) / NS),
            score=pl.col("probability"),
        )
    )
    s = s.with_columns([(pl.col("score") >= level_expr(k)).alias(f"ge_{k}")
                        for k in LEVELS])
    s = s.with_columns(
        obs_index=pl.int_range(pl.len()).over("regime_id"),
        score_running_max=pl.col("score").cum_max().over("regime_id"),
        delta_from_arm=(pl.col("score") - pl.col("arm_score")),
    ).with_columns(
        drawdown_from_max=(pl.col("score_running_max") - pl.col("score")),
    )
    # Consecutive run of observations at or above each level, from the arm.
    # `cum_sum` of the negated flag partitions runs; counting within the current
    # run gives the streak length. Causal at every row.
    for k in ("top_10", "INTERP_L1", "INTERP_L2", "top_5"):
        g = (~pl.col(f"ge_{k}")).cast(pl.Int32).cum_sum().over("regime_id")
        s = s.with_columns(**{f"grp_{k}": g})
        # Count QUALIFYING observations within the run, not row positions. The
        # group boundary increments ON a non-qualifying row, so that row is the
        # first member of the next group; a positional index would credit it and
        # every streak preceded by a miss would read one too high. Cum-summing
        # the flag gives 0 on the non-qualifying row and 1,2,3... on the run.
        s = s.with_columns(**{
            f"consec_{k}": pl.col(f"ge_{k}").cast(pl.Int32)
            .cum_sum().over(["regime_id", f"grp_{k}"])
        })
    s = s.drop([f"grp_{k}" for k in ("top_10", "INTERP_L1", "INTERP_L2", "top_5")])

    # Causal slopes. Only where two REAL dispatches bracket the window; never
    # interpolated across a gap (SPEC 5, Phase 1).
    for w in SLOPE_WINDOWS_S:
        s = s.with_columns(**{
            f"score_{w}s_ago": pl.col("score").shift(1).over("regime_id"),
        })
    s = _real_slopes(s)
    return s


def _real_slopes(s: pl.DataFrame) -> pl.DataFrame:
    """Change in score over each window, using only genuine bracketing dispatches."""
    out_cols: dict[str, list] = {f"slope_{w}s": [] for w in SLOPE_WINDOWS_S}
    out_cols["gap_before_s"] = []
    for _, blk in sorted(s.partition_by("regime_id", as_dict=True).items(),
                         key=lambda kv: str(kv[0])):
        t = blk["elapsed_s"].to_numpy()
        v = blk["score"].to_numpy()
        gap = np.diff(t, prepend=np.nan)
        out_cols["gap_before_s"].extend(gap.tolist())
        for w in SLOPE_WINDOWS_S:
            col = np.full(t.size, np.nan)
            for i in range(t.size):
                target = t[i] - w
                if target < 0:
                    continue
                j = int(np.searchsorted(t, target, side="right")) - 1
                if j < 0:
                    continue
                # Require the bracketing observation to be genuinely near the
                # window edge; a dispatch hole wider than the window itself
                # cannot support a slope over that window.
                if t[i] - t[j] > 2 * w:
                    continue
                col[i] = v[i] - v[j]
            out_cols[f"slope_{w}s"].extend(col.tolist())
    return s.with_columns([pl.Series(k, vals) for k, vals in out_cols.items()])


def arm_outcomes(stream: pl.DataFrame) -> pl.DataFrame:
    """SUCCESS / FAILURE / SESSION, anchored at the ARM (Phase 1 labels only).

    These label the arm's own path and are used to discover where the score
    paths separate. They are NOT the candidate trade outcomes -- Phase 4
    re-evaluates every candidate with its own entry price, ATR and stop.
    """
    market, regimes = load_market(), load_regimes()
    arms = (
        stream.group_by("regime_id")
        .agg(arm_ns=pl.col("arm_ns").first(), arm_price=pl.col("arm_price").first(),
             arm_atr=pl.col("arm_atr").first(), direction=pl.col("direction").first(),
             side=pl.col("side").first() if "side" in stream.columns else pl.lit(None),
             entry_year=pl.col("entry_year").first())
        .sort("arm_ns")
    )
    rows = []
    for r in arms.iter_rows(named=True):
        entry_ns, d = int(r["arm_ns"]), int(r["direction"])
        px, atr = r["arm_price"], r["arm_atr"]
        if atr is None or not np.isfinite(atr) or atr <= 0:
            continue
        start = market.index_strictly_after(entry_ns)
        if start >= market.n:
            continue
        close_ns = int(market.day_close_ns[start])
        sess_end = int(np.searchsorted(market.day_close_ns,
                                       market.day_close_ns[start], side="right"))
        confirm_ns = regimes.next_start_after(entry_ns, d, inclusive=True)
        horizon = close_ns if confirm_ns is None else min(close_ns, confirm_ns)
        end = min(max(market.index_at_or_after(horizon) + 1, start + 1),
                  sess_end, market.n)
        if end <= start:
            continue
        hi, lo, ts = market.high[start:end], market.low[start:end], market.ts[start:end]
        adv = (px - lo) if d > 0 else (hi - px)
        run_mae = np.maximum.accumulate(np.maximum(adv, 0.0)) / atr
        stop_hits = np.flatnonzero(run_mae >= STOP_ATR)
        si = int(stop_hits[0]) if stop_hits.size else -1
        ci = -1
        if confirm_ns is not None and confirm_ns <= int(ts[-1]):
            f = np.flatnonzero(ts >= confirm_ns)
            ci = int(f[0]) if f.size else -1
        if si >= 0 and (ci < 0 or si <= ci):
            lab, term = FAILURE, int(ts[si])
        elif ci >= 0:
            lab, term = SUCCESS, int(ts[ci])
        else:
            lab, term = SESSION, int(ts[-1])
        rows.append({"regime_id": r["regime_id"], "arm_outcome": lab,
                     "arm_terminal_ns": term,
                     "arm_confirm_ns": int(confirm_ns) if confirm_ns is not None else None,
                     "arm_stop_ns": int(ts[si]) if si >= 0 else None,
                     "arm_session_close_ns": close_ns,
                     "arm_ambiguous": bool(si >= 0 and ci >= 0 and si == ci)})
    return pl.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("building post-arm score stream ...", flush=True)
    stream = build_stream()
    print(f"  {stream.height:,} post-arm dispatches over "
          f"{stream['regime_id'].n_unique():,} armed regimes", flush=True)

    print("labelling arm outcomes ...", flush=True)
    outcomes = arm_outcomes(stream)
    stream = stream.join(outcomes, on="regime_id", how="left")
    # The armed window is bounded by the SESSION CLOSE, not by the arm's own
    # 1 ATR stop. An arm is a state, not a position (SPEC 1.1): an adverse move
    # before the trigger costs nothing and a later entry still gets a real price.
    # Bounding at `arm_terminal_ns` instead would silently impose adverse
    # invalidation and delete exactly the second-life cases the fairness
    # disclosure is supposed to surface.
    #
    # The confirming flip needs no explicit bound -- post-arm rows carry the OLD
    # regime's id, so nothing can fire at or after it. The session close does
    # need one, because a regime can span the overnight gap and its later RTH
    # rows would otherwise stitch across sessions.
    stream = stream.filter(
        pl.col("arm_session_close_ns").is_null()
        | (pl.col("checkpoint_decision_ns") <= pl.col("arm_session_close_ns"))
    )
    stream.write_parquet(OUT / "armed_score_path_diagnostics.parquet")
    print(f"  wrote armed_score_path_diagnostics.parquet ({stream.height:,} rows)")
    print(outcomes["arm_outcome"].value_counts().sort("count", descending=True))

    (OUT / "partition_manifest.json").write_text(json.dumps({
        "study": "top10_armed_entry_refinement",
        "armed_regimes": int(stream["regime_id"].n_unique()),
        "armed_required": ARMED_REQUIRED,
        "post_arm_dispatches": stream.height,
        "levels": {k: list(v) for k, v in LEVELS.items()},
        "interpolated_levels": list(INTERPOLATED),
        "interpolated_disclaimer": (
            "INTERPOLATED RESEARCH LEVEL -- NOT A PERCENTILE. Arithmetic between "
            "two frozen contract values (1/3 and 1/2 of the way from Top-10 to "
            "Top-5 in probability space). The frozen calibration distribution is "
            "not recoverable, so a true Top-7.5 percentile cannot be derived; "
            "deriving one from the evaluation population is forbidden."
        ),
        "stop_atr": STOP_ATR,
        "min_regime_age_s": MIN_REGIME_AGE_S,
        "arm_level": ARM_LEVEL,
        "slope_windows_s": list(SLOPE_WINDOWS_S),
        "landmark_times_s": list(LANDMARK_TIMES_S),
        "arm_expiry": "no adverse invalidation; structurally bounded by the armed "
                      "regime's end (post-arm rows carry the old regime_id)",
        "threshold_overlap_disclosure":
            "2025 is NOT threshold-OOS; waiver "
            "studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json",
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
