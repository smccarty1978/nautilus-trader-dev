"""Phases 2-7: deterioration events, their economics, and runner protection.

Everything here is a query over `results/post_confirm_paths.parquet`.

The core object is the **first firing** of each candidate event within a trade.
First-firing is causal: it is the earliest dispatch at which the condition is
true given only rows at or before it. Every economic figure is read at that row,
and the "remaining" figures are read from rows strictly after it -- which is the
one place this study looks forward, and it looks forward from the *event*, never
from the terminal label.

Vocabulary warning, per SPEC 1.1: on stream B the deterioration direction is
**escalation** (score rising = our regime is likely ending). Events are named
ESCALATION_* so the sign error cannot re-enter through habit. Stream C keeps the
brief's retreat framing, where that sign is correct.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "studies/post_confirmation_score_deterioration/results"
PANEL = OUT / "post_confirm_paths.parquet"

FAIL = ("CONFIRMED_THEN_STOPPED", "FINAL_FLIP_EXIT_LOSER")
WINNER = "FINAL_FLIP_EXIT_WINNER"
YEARS = (2021, 2022, 2023, 2024, 2025)
RUNNER_BUCKETS = ((0.0, 1.0), (1.0, 2.0), (2.0, 2.5), (2.5, 3.0), (3.0, np.inf))


# --------------------------------------------------------------- events

def event_specs() -> dict[str, pl.Expr]:
    """Candidate deterioration conditions, evaluated per row.

    Distribution-free by necessity (SPEC 1.3): the frozen percentile contracts
    were calibrated in-domain and do not transfer to stream B, so no
    threshold-loss event can be constructed without inventing a second
    incompatible threshold definition.
    """
    ev: dict[str, pl.Expr] = {}
    for x in (0.03, 0.05, 0.10):
        tag = f"{x:.2f}".replace(".", "_")
        # Escalation off the post-confirmation trough: the score has risen x
        # above the lowest conviction-of-flip seen so far in this trade.
        ev[f"ESCALATION_{tag}_from_min"] = pl.col("escalation_from_min") >= x
        # Escalation relative to the score standing at confirmation.
        ev[f"ESCALATION_{tag}_from_confirm"] = pl.col("escalation_from_confirm") >= x
    # Stream C in the brief's original sign: the exploratory model's conviction
    # retreating. Correct polarity on C, wrong on B -- see SPEC 1.1.
    for x in (0.03, 0.05):
        tag = f"{x:.2f}".replace(".", "_")
        ev[f"STREAMC_RETREAT_{tag}"] = pl.col("c_retreat_from_max") >= x
    # Price/score divergence (Phase 3): price sets a new favorable extreme for
    # the trade while stream B simultaneously sets a new high -- the regime is
    # still paying, but the model's conviction that it is about to end is at its
    # worst so far. Deliberately the simplest interpretable form; no search.
    ev["DIVERGENCE_price_high_score_high"] = (
        (pl.col("open_pnl_atr_conf") >= pl.col("run_mfe_atr") - 1e-12)
        & (pl.col("open_pnl_atr_conf") > 0)
        & (pl.col("score_b") >= pl.col("score_b_running_max") - 1e-12)
        & (pl.col("obs_index") >= 2)
    )
    return ev


def with_derived(panel: pl.DataFrame) -> pl.DataFrame:
    return panel.with_columns(
        c_running_max=pl.col("score_c").cum_max().over("regime_id"),
    ).with_columns(
        c_retreat_from_max=(pl.col("c_running_max") - pl.col("score_c")),
    )


def first_firings(panel: pl.DataFrame, name: str, cond: pl.Expr) -> pl.DataFrame:
    """First row per trade where `cond` holds, plus what happened afterwards."""
    fired = (
        panel.filter(cond)
        .sort("checkpoint_decision_ns")
        .group_by("regime_id")
        .first()
        .select(
            "regime_id", "terminal_label", "is_failure", "side", "entry_year",
            "elapsed_s", "open_pnl_atr_conf", "run_mfe_atr", "run_mae_atr",
            "giveback_atr", "score_b", "full_mfe_atr", "hold_s",
            fire_ns="checkpoint_decision_ns",
        )
        .rename({
            "elapsed_s": "fire_elapsed_s",
            "open_pnl_atr_conf": "fire_open_pnl_atr",
            "run_mfe_atr": "fire_mfe_atr",
            "run_mae_atr": "fire_mae_atr",
            "giveback_atr": "fire_giveback_atr",
            "score_b": "fire_score_b",
        })
    )
    if fired.height == 0:
        return fired

    # What remained AFTER the event. Forward-looking from the event only.
    after = (
        panel.join(fired.select("regime_id", "fire_ns"), on="regime_id", how="inner")
        .filter(pl.col("checkpoint_decision_ns") > pl.col("fire_ns"))
        .group_by("regime_id")
        .agg(
            max_pnl_after=pl.col("open_pnl_atr_conf").max(),
            final_pnl=pl.col("open_pnl_atr_conf").last(),
            min_score_after=pl.col("score_b").min(),
            n_after=pl.len(),
        )
    )
    return (
        fired.join(after, on="regime_id", how="left")
        .with_columns(
            remaining_mfe_atr=(
                pl.col("max_pnl_after").fill_null(pl.col("fire_open_pnl_atr"))
                - pl.col("fire_open_pnl_atr")
            ),
            seconds_to_terminal=(pl.col("hold_s") - pl.col("fire_elapsed_s")),
            event=pl.lit(name),
        )
    )


# --------------------------------------------------------------- metrics

def _q(s: pl.Series, q: float) -> float | None:
    s = s.drop_nulls()
    return round(float(s.quantile(q)), 4) if s.len() else None


def _med(s: pl.Series) -> float | None:
    return _q(s, 0.5)


def event_row(fired: pl.DataFrame, universe: pl.DataFrame, name: str) -> dict:
    """Sensitivity, precision, runner touch, and the economics at firing."""
    tot_fail = int(universe["is_failure"].sum())
    tot_win = int((universe["terminal_label"] == WINNER).sum())

    f_fail = fired.filter(pl.col("is_failure"))
    f_win = fired.filter(pl.col("terminal_label") == WINNER)
    n_fired = fired.height

    row = {
        "event": name,
        "n_fired": n_fired,
        "fire_rate": round(n_fired / universe.height, 4) if universe.height else None,
        "failures_caught": f_fail.height,
        "sensitivity": round(f_fail.height / tot_fail, 4) if tot_fail else None,
        "winner_touch_rate": round(f_win.height / tot_win, 4) if tot_win else None,
        "precision_p_failure_given_event": (
            round(f_fail.height / n_fired, 4) if n_fired else None
        ),
        "base_failure_rate": round(tot_fail / universe.height, 4) if universe.height else None,
    }

    # Economics at the moment of firing -- the question that decides usefulness.
    for label, sub in (("all", fired), ("failures", f_fail), ("winners", f_win)):
        if sub.height == 0:
            row[f"econ_{label}"] = {"n": 0}
            continue
        row[f"econ_{label}"] = {
            "n": sub.height,
            "median_fire_elapsed_s": _med(sub["fire_elapsed_s"]),
            "median_open_pnl_atr": _med(sub["fire_open_pnl_atr"]),
            "p25_open_pnl_atr": _q(sub["fire_open_pnl_atr"], 0.25),
            "p75_open_pnl_atr": _q(sub["fire_open_pnl_atr"], 0.75),
            "median_mfe_at_fire_atr": _med(sub["fire_mfe_atr"]),
            "median_giveback_at_fire_atr": _med(sub["fire_giveback_atr"]),
            "median_remaining_mfe_atr": _med(sub["remaining_mfe_atr"]),
            "median_seconds_to_terminal": _med(sub["seconds_to_terminal"]),
        }

    # Gate 2: runner touch by achieved-MFE bucket.
    winners = universe.filter(pl.col("terminal_label") == WINNER)
    touch = {}
    for lo, hi in RUNNER_BUCKETS:
        key = f"{lo:g}-{'inf' if np.isinf(hi) else format(hi, 'g')}"
        pool = winners.filter(
            (pl.col("full_mfe_atr") >= lo)
            & (pl.col("full_mfe_atr") < (hi if np.isfinite(hi) else 1e18))
        )
        hit = f_win.filter(
            (pl.col("full_mfe_atr") >= lo)
            & (pl.col("full_mfe_atr") < (hi if np.isfinite(hi) else 1e18))
        )
        touch[key] = {
            "n_runners": pool.height,
            "n_touched": hit.height,
            "touch_rate": round(hit.height / pool.height, 4) if pool.height else None,
            "median_mfe_at_touch_atr": _med(hit["fire_mfe_atr"]) if hit.height else None,
            "median_remaining_mfe_after_touch_atr": (
                _med(hit["remaining_mfe_atr"]) if hit.height else None
            ),
        }
    row["runner_touch_by_mfe_bucket"] = touch
    for thr in (2.0, 2.5, 3.0):
        tag = format(thr, "g").replace(".", "_")
        pool = winners.filter(pl.col("full_mfe_atr") >= thr)
        hit = f_win.filter(pl.col("full_mfe_atr") >= thr)
        row[f"touch_rate_ge_{tag}atr"] = (
            round(hit.height / pool.height, 4) if pool.height else None
        )
        row[f"n_runners_ge_{tag}atr"] = pool.height
    return row


def stability(fired: pl.DataFrame, universe: pl.DataFrame, name: str) -> dict:
    out = {"event": name, "by_direction": {}, "by_year": {}}
    for side in ("SHORT", "LONG"):
        u = universe.filter(pl.col("side") == side)
        f = fired.filter(pl.col("side") == side)
        out["by_direction"][side] = _slice_metrics(f, u)
    for y in YEARS:
        u = universe.filter(pl.col("entry_year") == y)
        f = fired.filter(pl.col("entry_year") == y)
        out["by_year"][str(y)] = _slice_metrics(f, u)
    return out


def _slice_metrics(fired: pl.DataFrame, universe: pl.DataFrame) -> dict:
    tot_fail = int(universe["is_failure"].sum())
    tot_win = int((universe["terminal_label"] == WINNER).sum())
    f_fail = fired.filter(pl.col("is_failure"))
    f_win = fired.filter(pl.col("terminal_label") == WINNER)
    winners = universe.filter(
        (pl.col("terminal_label") == WINNER) & (pl.col("full_mfe_atr") >= 2.5)
    )
    hit25 = f_win.filter(pl.col("full_mfe_atr") >= 2.5)
    return {
        "n": universe.height,
        "sensitivity": round(f_fail.height / tot_fail, 4) if tot_fail else None,
        "winner_touch_rate": round(f_win.height / tot_win, 4) if tot_win else None,
        "precision": round(f_fail.height / fired.height, 4) if fired.height else None,
        "touch_rate_ge_2_5atr": (
            round(hit25.height / winners.height, 4) if winners.height else None
        ),
        "median_open_pnl_atr_at_fire": _med(fired["fire_open_pnl_atr"]) if fired.height else None,
    }


# ------------------------------------------------------------------ main

def main() -> None:
    panel = with_derived(pl.read_parquet(PANEL))
    universe = (
        panel.group_by("regime_id")
        .agg(
            terminal_label=pl.col("terminal_label").first(),
            is_failure=pl.col("is_failure").first(),
            side=pl.col("side").first(),
            entry_year=pl.col("entry_year").first(),
            full_mfe_atr=pl.col("full_mfe_atr").first(),
            hold_s=pl.col("hold_s").first(),
        )
        # SESSION_EXIT is excluded from the target per SPEC 3 but reported.
        .filter(pl.col("terminal_label").is_in(list(FAIL) + [WINNER]))
    )
    print(f"universe: {universe.height:,} trades "
          f"({int(universe['is_failure'].sum()):,} failures)", flush=True)

    table, stab, fired_all = [], [], {}
    for name, cond in event_specs().items():
        fired = first_firings(panel, name, cond)
        fired = fired.filter(
            pl.col("terminal_label").is_in(list(FAIL) + [WINNER])
        ) if fired.height else fired
        fired_all[name] = fired
        if fired.height == 0:
            table.append({"event": name, "n_fired": 0})
            continue
        table.append(event_row(fired, universe, name))
        stab.append(stability(fired, universe, name))
        r = table[-1]
        print(f"  {name:34s} fired={r['n_fired']:>5} "
              f"sens={r['sensitivity']} touch={r['winner_touch_rate']} "
              f"prec={r['precision_p_failure_given_event']} "
              f"touch>=2.5={r['touch_rate_ge_2_5atr']} "
              f"pnl@fire={r['econ_all']['median_open_pnl_atr']}", flush=True)

    (OUT / "deterioration_event_table.json").write_text(
        json.dumps({
            "base_failure_rate": round(float(universe["is_failure"].mean()), 4),
            "universe_n": universe.height,
            "polarity_note": (
                "On stream B the deterioration direction is ESCALATION (score "
                "rising = the new regime is likely ending). Stream C events keep "
                "the brief's retreat framing, where that sign is correct."
            ),
            "not_applicable": {
                "events": ["loss of Top-1", "loss of Top-2.5", "loss of Top-5",
                           "loss of Top-10"],
                "reason": (
                    "The frozen percentile contracts were calibrated in-domain. "
                    "Stream B reads each model outside its contractual domain, so "
                    "the thresholds do not transfer. Constructing new cutoffs "
                    "would be a second incompatible threshold definition, which "
                    "Phase 0 rule 4 forbids."
                ),
            },
            "events": table,
        }, indent=2, default=str)
    )
    (OUT / "stability.json").write_text(json.dumps(stab, indent=2, default=str))

    # Runner-touch detail is large; give Gate 2 its own artifact.
    (OUT / "runner_touch.json").write_text(
        json.dumps({
            e["event"]: {
                "runner_touch_by_mfe_bucket": e.get("runner_touch_by_mfe_bucket"),
                "touch_rate_ge_2atr": e.get("touch_rate_ge_2atr"),
                "touch_rate_ge_2_5atr": e.get("touch_rate_ge_2_5atr"),
                "touch_rate_ge_3atr": e.get("touch_rate_ge_3atr"),
                "sensitivity": e.get("sensitivity"),
                "econ_winners": e.get("econ_winners"),
            }
            for e in table if e.get("n_fired")
        }, indent=2, default=str)
    )
    print("\nwrote deterioration_event_table.json, stability.json, runner_touch.json")


if __name__ == "__main__":
    main()
