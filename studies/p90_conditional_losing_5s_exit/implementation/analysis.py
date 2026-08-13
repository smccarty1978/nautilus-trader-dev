"""Phases 1-11: every table in the SPEC section 8 manifest.

Conventions that hold in every table:

* **Both denominators.** Economics is carried per ENTERED trade and per ORIGINAL
  P90 ARM (8,950; the 571 non-aligned arms contribute 0.0). A per-entry figure
  alone flatters any selective rule.
* **Cohorts are defined by the ACCEPTED lifecycle, not by the policy under test.**
  "Failure" means `NOT walk_a_confirm_reached_censored` -- a property of the arm.
  That is what lets four policies be compared on the same trades.
* **Phases 1, 2, 9 and 10 are descriptive** and may not produce a rule used by
  any policy here (SPEC section 11).
"""
from __future__ import annotations

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import NS
from studies.p90_conditional_losing_5s_exit.implementation.policy import (
    LOSING_5S_FLIP_EXIT, STOPPED_BEFORE_CONFIRM, CONFIRMED_THEN_STOPPED,
)

ARMED_REQUIRED = 8950
BOOT = 2000
SEED = 20260812


# ----------------------------------------------------------------- economics


def max_drawdown(net: np.ndarray, order: np.ndarray) -> float:
    if net.size == 0:
        return 0.0
    curve = np.cumsum(net[np.argsort(order, kind="stable")])
    return float(np.max(np.maximum.accumulate(curve) - curve))


def per_arm_series(walks: pl.DataFrame) -> np.ndarray:
    """One value per ORIGINAL arm; non-entries and censored arms contribute 0.0."""
    v = np.zeros(ARMED_REQUIRED, dtype=float)
    e = walks.filter(pl.col("entered"))
    v[: e.height] = e["net_atr"].to_numpy()
    return v


def economics(walks: pl.DataFrame, policy: str, rng: np.random.Generator) -> dict:
    e = walks.filter(pl.col("entered"))
    net, gross = e["net_atr"].to_numpy(), e["gross_atr"].to_numpy()
    wins, losses = net[net > 0], net[net < 0]

    arm = np.zeros(ARMED_REQUIRED)
    arm[: net.size] = net
    idx = rng.integers(0, ARMED_REQUIRED, size=(BOOT, ARMED_REQUIRED))
    band = np.percentile(arm[idx].mean(axis=1), [2.5, 97.5])

    return {
        "policy": policy,
        "n_original_arms": ARMED_REQUIRED,
        "n_entered": e.height,
        "entry_coverage": e.height / ARMED_REQUIRED,
        "win_rate": float((net > 0).mean()) if net.size else float("nan"),
        "mean_atr": float(net.mean()) if net.size else float("nan"),
        "median_atr": float(np.median(net)) if net.size else float("nan"),
        "mean_winner": float(wins.mean()) if wins.size else float("nan"),
        "mean_loser": float(losses.mean()) if losses.size else float("nan"),
        "profit_factor": (float(wins.sum() / -losses.sum())
                          if losses.size and losses.sum() != 0 else float("nan")),
        "gross_atr_total": float(gross.sum()),
        "net_atr_total": float(net.sum()),
        "exp_per_entry_gross": float(gross.mean()) if gross.size else float("nan"),
        "exp_per_entry_net": float(net.mean()) if net.size else float("nan"),
        "exp_per_arm_gross": float(gross.sum() / ARMED_REQUIRED),
        "exp_per_arm_net": float(net.sum() / ARMED_REQUIRED),
        "ci_low": float(band[0]), "ci_high": float(band[1]),
        "max_dd_atr": max_drawdown(net, e["entry_ns"].to_numpy()),
        "median_hold_s": float(e["hold_s"].median()) if e.height else float("nan"),
        "n_conditional_exits": int((e["outcome"] == LOSING_5S_FLIP_EXIT).sum()),
        "pct_ambiguous": float(e["ambiguous"].mean()) if e.height else 0.0,
    }


def paired_delta(a: pl.DataFrame, b: pl.DataFrame,
                 rng: np.random.Generator) -> dict:
    """b - a, paired on the arm, bootstrapped over ARMS (not entered trades).

    Paired by joining on `regime_id`, never by row position: two policy frames
    can legitimately differ in row order, and a positional pairing would silently
    difference unrelated trades. Arms absent from either side contribute 0.0, so
    the denominator stays 8,950.
    """
    j = (a.filter(pl.col("entered")).select("regime_id", a_net="net_atr")
         .join(b.filter(pl.col("entered")).select("regime_id", b_net="net_atr"),
               on="regime_id", how="inner"))
    d = np.zeros(ARMED_REQUIRED, dtype=float)
    d[: j.height] = (j["b_net"] - j["a_net"]).to_numpy()
    idx = rng.integers(0, d.size, size=(BOOT, d.size))
    ci = np.percentile(d[idx].mean(axis=1), [2.5, 97.5])
    return {"n_paired": j.height,
            "delta_per_arm": float(d.mean()),
            "delta_ci_low": float(ci[0]), "delta_ci_high": float(ci[1]),
            "delta_ci_excludes_zero": bool(ci[0] > 0 or ci[1] < 0)}


# ------------------------------------------------- Phase 1: flip geometry


def flip_geometry(flips: pl.DataFrame) -> pl.DataFrame:
    rows = []
    groups = [("ALL", flips)]
    groups += [(s, flips.filter(pl.col("side") == s)) for s in ("LONG", "SHORT")]
    groups += [(str(y), flips.filter(pl.col("entry_year") == y))
               for y in sorted(flips["entry_year"].unique().to_list())]
    for name, g in groups:
        for cohort, pred in (("ALL", pl.lit(True)),
                             ("confirming", pl.col("walk_a_confirmed")),
                             ("failure", ~pl.col("walk_a_confirmed"))):
            d = g.filter(pred)
            if d.height == 0:
                continue
            rows.append({
                "group": name, "cohort": cohort, "n_flips": d.height,
                "pct_losing": float(d["is_losing"].mean()),
                "median_return_atr": float(d["current_return_atr"].median()),
                "median_seconds_since_entry": float(d["seconds_since_entry"].median()),
                "median_giveback_atr": float(d["giveback_from_hwm_atr"].median()),
                "median_mfe_atr": float(d["current_mfe_atr"].median()),
                "pct_before_confirm": float(d["before_confirm"].mean()),
            })
    return pl.DataFrame(rows)


# --------------------------------------------- Phase 2: trade-level coverage


def signal_coverage(base: pl.DataFrame, flips: pl.DataFrame,
                    arms: pl.DataFrame) -> pl.DataFrame:
    e = base.filter(pl.col("entered"))
    meta = arms.select("regime_id", "walk_a_confirm_reached_censored",
                       "walk_a_confirm_ns", "walk_a_stop_ns", "walk_a_terminal_ns")
    d = e.join(meta, on="regime_id", how="left")
    f = flips.join(meta, on="regime_id", how="left")

    # a losing flip located against the ACCEPTED walk-A landmarks
    los = f.filter(pl.col("is_losing"))
    first_los = (los.sort("flip_ns").group_by("regime_id")
                 .agg(first_losing_ns=pl.col("flip_ns").first(),
                      first_losing_return=pl.col("current_return_atr").first(),
                      first_losing_secs=pl.col("seconds_since_entry").first()))
    d = d.join(first_los, on="regime_id", how="left")

    rows = []
    for cohort, pred in (("ALL", pl.lit(True)),
                         ("confirming", pl.col("walk_a_confirm_reached_censored")),
                         ("failure", ~pl.col("walk_a_confirm_reached_censored"))):
        s = d.filter(pred)
        if s.height == 0:
            continue
        fl = s["first_losing_ns"].to_numpy().astype("float64")
        stop_ns = s["walk_a_stop_ns"].to_numpy().astype("float64")
        conf_ns = s["walk_a_confirm_ns"].to_numpy().astype("float64")
        # Path landmarks measured on the baseline walk, so the 0.75 comparison
        # does not depend on the accepted lifecycle having a 0.75 stop (it has
        # only a 1.00 one, which is why `walk_a_stop_ns` cannot answer it).
        adv075 = s["adverse_075_ns"].to_numpy().astype("float64")
        adv100 = s["adverse_100_ns"].to_numpy().astype("float64")
        has = np.isfinite(fl)
        rows.append({
            "cohort": cohort, "n_trades": s.height,
            "pct_any_adverse_flip": float((s["n_adverse_flips"] > 0).mean()),
            "pct_any_losing_flip": float((s["n_losing_flips"] > 0).mean()),
            "pct_losing_before_075": float(
                np.mean(has & np.isfinite(adv075) & (fl < adv075))),
            "pct_losing_before_100": float(
                np.mean(has & np.isfinite(adv100) & (fl < adv100))),
            # `pct_losing_before_1atr` is the manifest's literal name; the
            # `_stop` suffix is kept as the self-describing alias.
            "pct_losing_before_1atr": float(
                np.mean(has & np.isfinite(stop_ns) & (fl < stop_ns))),
            "pct_losing_before_1atr_stop": float(
                np.mean(has & np.isfinite(stop_ns) & (fl < stop_ns))),
            "pct_losing_before_confirm": float(
                np.mean(has & np.isfinite(conf_ns) & (fl < conf_ns))),
            "median_seconds_to_first_losing": float(
                np.nanmedian(s["first_losing_secs"].to_numpy())) if has.any() else float("nan"),
            "median_return_at_first_losing": float(
                np.nanmedian(s["first_losing_return"].to_numpy())) if has.any() else float("nan"),
            "mean_adverse_flips": float(s["n_adverse_flips"].mean()),
            "mean_losing_flips": float(s["n_losing_flips"].mean()),
        })
    return pl.DataFrame(rows)


# ------------------------------------------------ Phase 3: confusion matrix


def confusion(base: pl.DataFrame, flips: pl.DataFrame,
              arms: pl.DataFrame) -> pl.DataFrame:
    """SIGNAL = a losing adverse flip before the accepted walk-A horizon.
    TARGET = eventual failure to confirm under the accepted 1.00 ATR lifecycle."""
    meta = arms.select("regime_id", "walk_a_confirm_reached_censored",
                       "walk_a_terminal_ns", "side", "entry_year")
    los = flips.filter(pl.col("is_losing")).join(
        meta.select("regime_id", "walk_a_terminal_ns"), on="regime_id", how="left")
    sig_ids = set(los.filter(pl.col("flip_ns") <= pl.col("walk_a_terminal_ns"))
                  ["regime_id"].to_list())

    d = (base.filter(pl.col("entered"))
         .join(meta.drop("side", "entry_year"), on="regime_id", how="left")
         .with_columns(signal=pl.col("regime_id").is_in(list(sig_ids)),
                       target=~pl.col("walk_a_confirm_reached_censored")))
    rows = []
    groups = [("ALL", d)]
    groups += [(s, d.filter(pl.col("side") == s)) for s in ("LONG", "SHORT")]
    groups += [(str(y), d.filter(pl.col("entry_year") == y))
               for y in sorted(d["entry_year"].unique().to_list())]
    for name, g in groups:
        s, t = g["signal"].to_numpy(), g["target"].to_numpy()
        tp = int((s & t).sum()); fp = int((s & ~t).sum())
        tn = int((~s & ~t).sum()); fn = int((~s & t).sum())
        rows.append({
            "group": name, "n": g.height, "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "sensitivity": tp / (tp + fn) if tp + fn else float("nan"),
            "specificity": tn / (tn + fp) if tn + fp else float("nan"),
            "ppv": tp / (tp + fp) if tp + fp else float("nan"),
            "npv": tn / (tn + fn) if tn + fn else float("nan"),
            "prevalence": float(t.mean()) if t.size else float("nan"),
            "signal_rate": float(s.mean()) if s.size else float("nan"),
        })
    return pl.DataFrame(rows)


# --------------------------------------------------- Phase 5: failure harvest


def failure_harvest(base: pl.DataFrame, cond: pl.DataFrame, arms: pl.DataFrame,
                    policy: str) -> pl.DataFrame:
    fail_ids = arms.filter(~pl.col("walk_a_confirm_reached_censored"))["regime_id"]
    b = base.filter(pl.col("entered") & pl.col("regime_id").is_in(fail_ids))
    c = cond.filter(pl.col("entered") & pl.col("regime_id").is_in(fail_ids))
    j = b.select("regime_id", b_net="net_atr", b_out="outcome").join(
        c.select("regime_id", c_net="net_atr", c_out="outcome"),
        on="regime_id", how="inner")
    intercepted = j.filter(pl.col("c_out") == LOSING_5S_FLIP_EXIT)
    saved = (intercepted["c_net"] - intercepted["b_net"]).to_numpy()
    still_stop = j.filter(pl.col("c_out").is_in(
        [STOPPED_BEFORE_CONFIRM, CONFIRMED_THEN_STOPPED]))
    return pl.DataFrame([{
        "policy": policy,
        "n_failure_arms": int(fail_ids.len()),
        "n_failure_entered": j.height,
        "n_intercepted": intercepted.height,
        "interception_pct": intercepted.height / j.height if j.height else float("nan"),
        "mean_baseline_failure": float(j["b_net"].mean()),
        "mean_conditional_failure": float(j["c_net"].mean()),
        "median_baseline_failure": float(j["b_net"].median()),
        "median_conditional_failure": float(j["c_net"].median()),
        "atr_saved_per_intercepted": float(saved.mean()) if saved.size else float("nan"),
        "atr_saved_total": float((j["c_net"] - j["b_net"]).sum()),
        "atr_saved_per_failure_arm": float((j["c_net"] - j["b_net"]).sum() / j.height)
        if j.height else float("nan"),
        "atr_saved_per_original_arm": float((j["c_net"] - j["b_net"]).sum() / ARMED_REQUIRED),
        "n_still_reaching_stop": still_stop.height,
        "pct_still_reaching_stop": still_stop.height / j.height if j.height else float("nan"),
    }])


# ----------------------------------------------- Phase 6: good-trade destruction


def good_trade_destruction(base: pl.DataFrame, cond: pl.DataFrame,
                           arms: pl.DataFrame, policy: str,
                           source: str) -> pl.DataFrame:
    """Confirming-baseline trades cut short, split by WHICH rule cut them."""
    ok = arms.filter(pl.col("walk_a_confirm_reached_censored"))
    ids = ok["regime_id"]
    b = base.filter(pl.col("entered") & pl.col("regime_id").is_in(ids))
    c = cond.filter(pl.col("entered") & pl.col("regime_id").is_in(ids))
    j = (b.select("regime_id", b_net="net_atr", b_out="outcome", b_mfe="mfe_atr")
         .join(c.select("regime_id", c_net="net_atr", c_out="outcome"),
               on="regime_id", how="inner")
         .join(ok.select("regime_id", "walk_a_return_at_confirm_atr",
                         "walk_a_mfe_to_confirm_atr"), on="regime_id", how="left"))
    if source == "losing_5s":
        dest = j.filter((pl.col("c_out") == LOSING_5S_FLIP_EXIT)
                        & (pl.col("b_out") != LOSING_5S_FLIP_EXIT))
    else:  # tighter_stop
        dest = j.filter(pl.col("c_out").is_in(
            [STOPPED_BEFORE_CONFIRM, CONFIRMED_THEN_STOPPED])
            & ~pl.col("b_out").is_in([STOPPED_BEFORE_CONFIRM, CONFIRMED_THEN_STOPPED]))
    forfeited = (dest["c_net"] - dest["b_net"]).to_numpy()
    return pl.DataFrame([{
        "policy": policy, "source": source,
        "n_confirming_baseline": j.height,
        "n_destroyed": dest.height,
        "pct_destroyed": dest.height / j.height if j.height else float("nan"),
        "mean_exit_return": float(dest["c_net"].mean()) if dest.height else float("nan"),
        "mean_baseline_return": float(dest["b_net"].mean()) if dest.height else float("nan"),
        "mean_eventual_return_at_confirm": float(
            dest["walk_a_return_at_confirm_atr"].mean()) if dest.height else float("nan"),
        "mean_eventual_mfe_at_confirm": float(
            dest["walk_a_mfe_to_confirm_atr"].mean()) if dest.height else float("nan"),
        "atr_forfeited_total": float(forfeited.sum()) if forfeited.size else 0.0,
        "atr_forfeited_per_confirming": float(forfeited.sum() / j.height)
        if j.height else float("nan"),
        "atr_forfeited_per_original_arm": float(
            (forfeited.sum() if forfeited.size else 0.0) / ARMED_REQUIRED),
    }])


# --------------------------------------------- Phase 8: before/after confirm


def pre_post_confirm(base: pl.DataFrame, cond: pl.DataFrame,
                     policy: str) -> pl.DataFrame:
    c = cond.filter(pl.col("entered") & (pl.col("outcome") == LOSING_5S_FLIP_EXIT))
    b = base.filter(pl.col("entered")).select(
        "regime_id", b_net="net_atr", b_out="outcome")
    j = c.join(b, on="regime_id", how="left")
    rows = []
    for phase, pred in (("BEFORE_CONFIRM", ~pl.col("confirmed_before_exit")),
                        ("AFTER_CONFIRM", pl.col("confirmed_before_exit"))):
        d = j.filter(pred)
        rows.append({
            "policy": policy, "phase": phase, "n": d.height,
            "pct": d.height / j.height if j.height else float("nan"),
            "pct_of_original_arms": d.height / ARMED_REQUIRED,
            "mean_net_atr": float(d["net_atr"].mean()) if d.height else float("nan"),
            "median_net_atr": float(d["net_atr"].median()) if d.height else float("nan"),
            "mean_return_at_fire": float(d["return_at_fire_atr"].mean()) if d.height else float("nan"),
            "mean_eventual_baseline_atr": float(d["b_net"].mean()) if d.height else float("nan"),
            "atr_delta_vs_baseline": float((d["net_atr"] - d["b_net"]).mean())
            if d.height else float("nan"),
            "atr_delta_total": float((d["net_atr"] - d["b_net"]).sum()) if d.height else 0.0,
            "median_seconds_since_entry": float(d["hold_s"].median()) if d.height else float("nan"),
        })
    return pl.DataFrame(rows)


# ----------------------------------------------- Phase 9: which flip fires


def flip_sequence(base: pl.DataFrame, cond: pl.DataFrame, arms: pl.DataFrame,
                  policy: str) -> pl.DataFrame:
    c = (cond.filter(pl.col("entered") & (pl.col("outcome") == LOSING_5S_FLIP_EXIT))
         .join(base.filter(pl.col("entered")).select("regime_id", b_net="net_atr"),
               on="regime_id", how="left")
         .join(arms.select("regime_id", "walk_a_confirm_reached_censored"),
               on="regime_id", how="left"))
    rows = []
    buckets = {"1": (1, 1), "2": (2, 2), "3": (3, 3), "4+": (4, 10**9)}
    for name, (lo, hi) in buckets.items():
        d = c.filter((pl.col("fired_flip_number") >= lo)
                     & (pl.col("fired_flip_number") <= hi))
        rows.append({
            "policy": policy, "fired_flip_number": name, "n": d.height,
            "pct": d.height / c.height if c.height else float("nan"),
            "median_seconds_since_entry": float(d["hold_s"].median()) if d.height else float("nan"),
            "median_return_at_fire": float(d["return_at_fire_atr"].median()) if d.height else float("nan"),
            "mean_net_atr": float(d["net_atr"].mean()) if d.height else float("nan"),
            "mean_baseline_net_atr": float(d["b_net"].mean()) if d.height else float("nan"),
            "pct_baseline_failures": float(
                (~d["walk_a_confirm_reached_censored"]).mean()) if d.height else float("nan"),
        })
    return pl.DataFrame(rows)


# ------------------------------------------- Phase 10: stop x rule interaction


def stop_interaction(c100: pl.DataFrame, c075: pl.DataFrame,
                     arms: pl.DataFrame) -> pl.DataFrame:
    j = (c100.filter(pl.col("entered")).select(
            "regime_id", n100="net_atr", o100="outcome")
         .join(c075.filter(pl.col("entered")).select(
             "regime_id", n075="net_atr", o075="outcome"),
             on="regime_id", how="inner")
         .join(arms.select("regime_id", "walk_a_confirm_reached_censored"),
               on="regime_id", how="left"))
    stops = [STOPPED_BEFORE_CONFIRM, CONFIRMED_THEN_STOPPED]
    cats = {
        "cond_5s_fires_before_either_stop":
            (pl.col("o100") == LOSING_5S_FLIP_EXIT) & (pl.col("o075") == LOSING_5S_FLIP_EXIT),
        "075_stops_but_100_cond_5s_catches_it":
            pl.col("o075").is_in(stops) & (pl.col("o100") == LOSING_5S_FLIP_EXIT),
        "075_stops_and_cond_5s_never_catches":
            pl.col("o075").is_in(stops) & pl.col("o100").is_in(stops),
        "075_kills_an_eventual_confirmation":
            pl.col("o075").is_in(stops) & (pl.col("o100") != pl.col("o075"))
            & pl.col("walk_a_confirm_reached_censored"),
    }
    rows = []
    for name, pred in cats.items():
        d = j.filter(pred)
        rows.append({
            "category": name, "n": d.height,
            "pct": d.height / j.height if j.height else float("nan"),
            "mean_net_atr_100": float(d["n100"].mean()) if d.height else float("nan"),
            "mean_net_atr_075": float(d["n075"].mean()) if d.height else float("nan"),
            "delta_075_minus_100": float((d["n075"] - d["n100"]).mean())
            if d.height else float("nan"),
            "delta_total": float((d["n075"] - d["n100"]).sum()) if d.height else 0.0,
        })
    return pl.DataFrame(rows)


# ------------------------------------------------- stability breakdowns


def by_group(walks: pl.DataFrame, policy: str, col: str,
             arms: pl.DataFrame) -> pl.DataFrame:
    """Per-group economics on BOTH denominators.

    The per-arm denominator comes from `arms`, not from the walks frame: the
    walks frame holds only entered trades, so using its own group size would
    quietly turn "per original arm" into "per entered trade" and inflate every
    group by the entry-coverage factor.
    """
    arm_counts = {r[col]: int(r["len"]) for r in
                  arms.group_by(col).len().iter_rows(named=True)}
    rows = []
    for key in sorted(arm_counts):
        ed = walks.filter(pl.col("entered") & (pl.col(col) == key))
        net = ed["net_atr"].to_numpy()
        n_arms = arm_counts[key]
        rows.append({
            "policy": policy, col: key, "n_arms": n_arms, "n_entered": ed.height,
            "win_rate": float((net > 0).mean()) if net.size else float("nan"),
            "exp_per_entry_net": float(net.mean()) if net.size else float("nan"),
            "exp_per_arm_net": float(net.sum() / n_arms),
            "max_dd_atr": max_drawdown(net, ed["entry_ns"].to_numpy()),
        })
    return pl.DataFrame(rows)
