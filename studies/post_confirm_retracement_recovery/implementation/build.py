"""Build the two panels every table in this study aggregates from.

Nothing downstream recomputes a path. `phases.py` and `diagnostics.py` only ever
group these panels, so a descriptive table cannot disagree with the causal walk
that produced it.

Panels
------
arm_panel     trade x rung x D            -- one row per cell membership, all strata
state_panel   arm x horizon               -- ARM_FRESH only, causal state + economics

The confirmed population is IMPORTED from the accepted ratchet study, never
re-derived. Re-deriving it would be a fresh chance to get the `arm_top10_ns`
clock or the integer-nanosecond cohort edges wrong, and both have already cost
this program a population error.
"""
from __future__ import annotations

import json
import time

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    load_market, load_regimes,
)
from studies.top10_fast_confirm_runner_path.implementation.build import (
    confirmed_population,
)

from .arms import build_trade, walk
from .common import (
    ACCEPTED, ACCEPTED_PER_RUNG, NAT_OPPOSING_FLIP, RESULTS, RUNGS, SEED,
    STOPPED_BEFORE_CONFIRM, TOL_ATR, YEARS,
    assert_sealed, load_armed_panel, load_rung_events, load_trade_panel,
    write_parquet,
)


def build_panels(years: tuple[int, ...] = YEARS,
                 limit: int | None = None) -> tuple[pl.DataFrame, pl.DataFrame, dict]:
    """Walk every measurable confirmed trade once. Returns (arms, states, diag)."""
    t0 = time.time()
    panel = load_trade_panel(years)
    if limit is not None:
        panel = panel.head(limit)

    # The seal is enforced at the SOURCE SCAN: 2026 bars are never loaded into
    # memory at all, so no downstream slice can reach one. Trades are intraday
    # and forced flat at 15:00 CT, so no window can want a bar from another year.
    market = load_market(years)
    regimes = load_regimes()

    arm_rows: list[dict] = []
    state_rows: list[dict] = []
    diag = {"trades_in": panel.height, "no_window": 0, "walked": 0, "seed": SEED}
    # Seeded once for the whole study: the placebo is reproducible bit-for-bit
    # and can never be re-rolled against an unfavourable result.
    rng = np.random.default_rng(SEED)

    for tr in panel.iter_rows(named=True):
        rt = build_trade(market, regimes, tr)
        if rt is None:
            # A trade whose window cannot be rebuilt is COUNTED, never dropped
            # silently -- a shrinking denominator is how a population error hides.
            diag["no_window"] += 1
            continue
        a, s = walk(rt, rng)
        arm_rows.extend(a)
        state_rows.extend(s)
        diag["walked"] += 1

    arms = pl.DataFrame(arm_rows)
    states = pl.DataFrame(state_rows) if state_rows else pl.DataFrame()
    diag["arm_rows"] = arms.height
    diag["state_rows"] = states.height
    diag["seconds"] = round(time.time() - t0, 1)

    assert_sealed(arms, "entry_ns", "arm_panel")
    if states.height:
        assert_sealed(states, "arm_ts", "state_panel")
    return arms, states, diag


def lineage_reconciliation(arms: pl.DataFrame) -> dict:
    """Phase 0. Reproduce the accepted predecessor population before proceeding.

    Every quantity is compared to the ACCEPTED literal from the ratchet REPORT.
    If lineage materially fails the caller STOPS: this study does not repair a
    predecessor silently.
    """
    armed = load_armed_panel()
    pop = confirmed_population()
    ev = load_rung_events()
    panel = load_trade_panel()

    # The ARMED panel is the entry population; `confirmed_population()` is a
    # filtered view of it and cannot supply either of these two counts.
    n_entries = armed.height
    n_conf = pop.height
    n_meas = panel.height
    pre = armed.filter(pl.col("terminal_label_full") == STOPPED_BEFORE_CONFIRM)

    # Giveback pool and baseline, per ORIGINAL ENTRY (denominator 8,950),
    # reproduced the way the accepted study defines them
    # (post_confirm_profit_ratchet/implementation/validate.py:167-177):
    #   pool     STOP-LIVE giveback over OPPOSING_FLIP terminals ONLY. STOP and
    #            SESSION terminals never gave anything back to recover.
    #   baseline the confirmed cohort's net PLUS the 4,245 trades stopped before
    #            they ever confirmed. Omitting that cohort is not a smaller
    #            baseline, it is a different strategy -- the losers the entry
    #            rule pays for before any exit rule can act.
    pool = float(panel.filter(pl.col("nat_kind") == NAT_OPPOSING_FLIP)
                 ["nat_giveback_atr"].sum()) / ACCEPTED["entries"]
    base = (float(panel["baseline_net_atr"].sum())
            + float(pre["full_net_atr"].fill_null(0.0).sum())) / ACCEPTED["entries"]

    rows = []

    def add(name, obs, acc, exact=True):
        obs_f = float(obs)
        acc_f = float(acc)
        delta = obs_f - acc_f
        ok = (obs_f == acc_f) if exact else (abs(delta) <= TOL_ATR)
        rows.append({"quantity": name, "observed": obs_f, "accepted": acc_f,
                     "delta": delta, "status": "EXACT" if ok else "MISMATCH"})

    add("original_top10_entries", n_entries, ACCEPTED["entries"])
    add("confirmed", n_conf, ACCEPTED["confirmed"])
    add("stopped_before_confirm", n_entries - n_conf,
        ACCEPTED["stopped_before_confirm"])
    # Derived a second, independent way: by terminal label rather than by
    # subtraction. Subtraction alone would still reconcile if both panels were
    # wrong by the same amount.
    add("stopped_before_confirm_by_label", pre.height,
        ACCEPTED["stopped_before_confirm"])
    add("measurable_confirmed", n_meas, ACCEPTED["measurable_confirmed"])
    add("non_measurable", n_conf - n_meas, ACCEPTED["non_measurable"])
    add("giveback_pool_per_entry", pool, ACCEPTED["pool_per_entry"], exact=False)
    add("baseline_net_per_entry", base, ACCEPTED["baseline_net_per_entry"],
        exact=False)
    add("rung_events_post_confirm", ev.height, ACCEPTED["rung_events_post_confirm"])
    add("trades_reaching_1atr", ev.filter(pl.col("rung_atr") == 1.0).height,
        ACCEPTED["trades_reaching_1atr"])

    for X in RUNGS:
        add(f"rung_{X}_events", ev.filter(pl.col("rung_atr") == X).height,
            ACCEPTED_PER_RUNG[X])

    # This study's own rung membership must agree with the imported population,
    # bar for bar. A disagreement means the rebuilt window found a different
    # rung bar from the one the accepted geometry was measured on.
    mine = (arms.filter(pl.col("retracement_d") == 0.50)
            .group_by("rung_atr").agg(pl.len().alias("n")).sort("rung_atr"))
    for r in mine.iter_rows(named=True):
        add(f"rebuilt_rung_{r['rung_atr']}_membership", r["n"],
            ACCEPTED_PER_RUNG[float(r["rung_atr"])])

    # Rung TIMESTAMP agreement, not merely count agreement.
    joined = (arms.filter(pl.col("retracement_d") == 0.50)
              .select("regime_id", "rung_atr", "rung_ts")
              .join(ev.select("regime_id", "rung_atr",
                              pl.col("rung_ts").alias("rung_ts_accepted")),
                    on=["regime_id", "rung_atr"], how="inner"))
    n_ts_mismatch = joined.filter(
        pl.col("rung_ts") != pl.col("rung_ts_accepted")).height
    add("rung_ts_mismatches", n_ts_mismatch, 0)

    failed = [r for r in rows if r["status"] != "EXACT"]
    return {
        "years": list(YEARS),
        "sealed_years_never_read": [2020, 2026],
        "rows": rows,
        "n_checks": len(rows),
        "n_failed": len(failed),
        "lineage_status": "REPRODUCED" if not failed else "FAILED",
        "failed": failed,
    }


def main(limit: int | None = None) -> dict:
    arms, states, diag = build_panels(limit=limit)
    write_parquet(arms, "arm_panel.parquet")
    write_parquet(states, "recovery_state_panel.parquet")

    lin = lineage_reconciliation(arms)
    lin["build_diagnostics"] = diag
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "lineage_reconciliation.json").write_text(
        json.dumps(lin, indent=2), encoding="utf-8")
    return lin
