"""Phases 1-11: every table in the SPEC section 6 manifest.

Two conventions hold everywhere and are not negotiable per-table:

* **Both denominators.** Every economic figure is carried per ENTERED trade and
  per ORIGINAL P90 ARM (denominator 8,950, non-entries contributing 0.0). A
  per-entry figure alone flatters any selective trigger
  (`immediate_top10_entry_is_optimal`, `baseline_must_include_prefilter_losers`).
* **Descriptive phases stay descriptive.** Phases 2, 10 and 11 may not produce a
  filter used by S1 or S075 (SPEC section 10). They exist to say whether a
  *future* study is warranted.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import NS
from studies.p90_5s_regime_impulse.implementation.policy import (
    ALIGNED, FIVE_S_EXIT, OPPOSITE, SESSION_CLOSE, STOP, UNINIT,
)

ARMED_REQUIRED = 8950
BOOT = 2000
SEED = 20260812


# ----------------------------------------------------------------- economics


def max_drawdown(net: np.ndarray, order: np.ndarray) -> float:
    """Peak-to-trough of the cumulative net-ATR curve in chronological order."""
    if net.size == 0:
        return 0.0
    curve = np.cumsum(net[np.argsort(order, kind="stable")])
    return float(np.max(np.maximum.accumulate(curve) - curve))


def _boot_ci(per_arm: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    """Percentile CI for the per-ARM mean, resampling the ARM population.

    `per_arm` has one entry per original arm, zero for non-entries. Resampling
    arms rather than entered trades is what keeps the non-entries inside the
    uncertainty estimate -- they are part of the quantity being estimated.
    """
    if per_arm.size == 0:
        return float("nan"), float("nan")
    idx = rng.integers(0, per_arm.size, size=(BOOT, per_arm.size))
    means = per_arm[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def economics(walks: pl.DataFrame, policy: str) -> dict:
    """One `policy_comparison.csv` row. Carries BOTH denominators."""
    entered = walks.filter(pl.col("entered") & pl.col("gross_atr").is_finite())
    net = entered["net_atr"].to_numpy()
    gross = entered["gross_atr"].to_numpy()
    wins, losses = net[net > 0], net[net < 0]
    rng = np.random.default_rng(SEED)

    # per-ARM series: every one of the 8,950 arms, non-entries contributing 0.0
    per_arm = np.zeros(walks.height, dtype=float)
    mask = (walks["entered"] & walks["gross_atr"].is_finite()).to_numpy()
    per_arm[mask] = net
    lo, hi = _boot_ci(per_arm, rng)

    return {
        "policy": policy,
        "n_arms": walks.height,
        "n_entries": entered.height,
        "entry_coverage": entered.height / walks.height,
        "n_stop": int((entered["outcome"] == STOP).sum()),
        "n_5s_exit": int((entered["outcome"] == FIVE_S_EXIT).sum()),
        "n_session": int((entered["outcome"] == SESSION_CLOSE).sum()),
        "win_rate": float((net > 0).mean()) if net.size else float("nan"),
        "mean_atr": float(net.mean()) if net.size else float("nan"),
        "median_atr": float(np.median(net)) if net.size else float("nan"),
        "mean_winner": float(wins.mean()) if wins.size else float("nan"),
        "median_winner": float(np.median(wins)) if wins.size else float("nan"),
        "mean_loser": float(losses.mean()) if losses.size else float("nan"),
        "median_loser": float(np.median(losses)) if losses.size else float("nan"),
        "profit_factor": (float(wins.sum() / -losses.sum())
                          if losses.size and losses.sum() != 0 else float("nan")),
        "gross_atr_total": float(gross.sum()),
        "net_atr_total": float(net.sum()),
        "exp_per_entry_gross": float(gross.mean()) if gross.size else float("nan"),
        "exp_per_entry_net": float(net.mean()) if net.size else float("nan"),
        "exp_per_arm_gross": float(gross.sum() / walks.height),
        "exp_per_arm_net": float(net.sum() / walks.height),
        "exp_per_arm_net_ci_low": lo,
        "exp_per_arm_net_ci_high": hi,
        "atr_per_100_arms": float(net.sum() / walks.height * 100),
        "max_dd_atr": max_drawdown(net, entered["entry_ns"].to_numpy()),
        "median_hold_s": (float(entered["hold_s"].median())
                          if entered.height else float("nan")),
        "pct_ambiguous": float(entered["ambiguous"].mean()) if entered.height else 0.0,
    }


# ------------------------------------------------------- Phase 1: alignment


def alignment_table(walks: pl.DataFrame) -> pl.DataFrame:
    rows = []
    groups: list[tuple[str, pl.DataFrame]] = [("ALL", walks)]
    groups += [(s, walks.filter(pl.col("side") == s)) for s in ("LONG", "SHORT")]
    groups += [(str(y), walks.filter(pl.col("entry_year") == y))
               for y in sorted(walks["entry_year"].unique().to_list())]
    for name, d in groups:
        n = d.height
        counts = {a: int((d["alignment"] == a).sum())
                  for a in (ALIGNED, OPPOSITE, UNINIT)}
        rows.append({
            "group": name, "n_arms": n,
            "n_aligned": counts[ALIGNED], "pct_aligned": counts[ALIGNED] / n,
            "n_opposite": counts[OPPOSITE], "pct_opposite": counts[OPPOSITE] / n,
            "n_uninit": counts[UNINIT], "pct_uninit": counts[UNINIT] / n,
        })
    return pl.DataFrame(rows)


# -------------------------------------------------------- Phase 2: geometry


def geometry_table(walks: pl.DataFrame, r5, arms: pl.DataFrame) -> pl.DataFrame:
    """Descriptive shape of the aligned 5s regime at and after the arm."""
    e = walks.filter(pl.col("entered") & pl.col("gross_atr").is_finite())
    arm_ns = e["arm_ns"].to_numpy()
    entry_ns = e["entry_ns"].to_numpy()
    direction = e["direction"].to_numpy()
    flip_ts = r5.flip_ts_at(arm_ns)

    age_arm = np.where(flip_ts >= 0, (arm_ns - flip_ts) / NS, np.nan)
    age_entry = np.where(flip_ts >= 0, (entry_ns - flip_ts) / NS, np.nan)
    next_non = np.array([r5.first_non_aligned_after(int(t), int(d))
                         for t, d in zip(arm_ns, direction)], dtype=np.int64)
    secs_to_non = np.where(next_non >= 0, (next_non - arm_ns) / NS, np.nan)

    # "arm relative to the 5s flip that created the aligned state"
    buckets = np.full(age_arm.size, ">30s", dtype=object)
    buckets[age_arm <= 30] = "16-30s"
    buckets[age_arm <= 15] = "6-15s"
    buckets[age_arm <= 5] = "1-5s"
    buckets[age_arm == 0] = "exactly_on_flip"

    return e.select(
        "regime_id", "side", "entry_year", "outcome", "gross_atr", "net_atr",
        "mfe_atr", "mae_atr", "hold_s", "confirmed_before_exit",
    ).with_columns(
        age_5s_at_arm_s=pl.Series(age_arm),
        age_5s_at_entry_s=pl.Series(age_entry),
        secs_since_5s_flip=pl.Series(age_arm),
        secs_to_next_nonaligned=pl.Series(secs_to_non),
        arm_offset_bucket=pl.Series([str(b) for b in buckets]),
        realized_atr=pl.col("net_atr"),
    )


# -------------------------------------- Phases 4 & 5: relation to confirmation


def exit_vs_confirmation(walks: pl.DataFrame, policy: str) -> pl.DataFrame:
    """Which came first, the 5s exit or the 1m confirmation."""
    e = walks.filter(pl.col("entered") & pl.col("gross_atr").is_finite())
    conf = e["confirm_ns"].to_numpy().astype("float64")
    exit_ns = e["exit_ns"].to_numpy().astype("float64")
    outcome = e["outcome"].to_numpy()
    has_conf = np.isfinite(conf)
    before = has_conf & (conf <= exit_ns)

    cls = np.full(e.height, "SESSION_OTHER", dtype=object)
    cls[(outcome == FIVE_S_EXIT) & ~before] = "5S_EXIT_BEFORE_1M_CONFIRM"
    cls[(outcome == FIVE_S_EXIT) & before] = "1M_CONFIRM_BEFORE_5S_EXIT"
    cls[(outcome == STOP) & ~before] = "STOP_BEFORE_1M_CONFIRM"
    cls[(outcome == STOP) & before] = "STOP_AFTER_1M_CONFIRM"

    d = e.with_columns(exit_class=pl.Series([str(c) for c in cls]))
    rows = []
    for name in ("5S_EXIT_BEFORE_1M_CONFIRM", "1M_CONFIRM_BEFORE_5S_EXIT",
                 "STOP_BEFORE_1M_CONFIRM", "STOP_AFTER_1M_CONFIRM", "SESSION_OTHER"):
        s = d.filter(pl.col("exit_class") == name)
        rows.append({
            "policy": policy, "class": name, "n": s.height,
            "pct": s.height / d.height if d.height else float("nan"),
            "pct_of_original_arms": s.height / walks.height,
            "mean_net_atr": float(s["net_atr"].mean()) if s.height else float("nan"),
            "median_net_atr": float(s["net_atr"].median()) if s.height else float("nan"),
            "mean_mfe_atr": float(s["mfe_atr"].mean()) if s.height else float("nan"),
            "mean_mae_atr": float(s["mae_atr"].mean()) if s.height else float("nan"),
        })
    return pl.DataFrame(rows)


def confirmation_capture(walks: pl.DataFrame, policy: str,
                         rng: np.random.Generator) -> pl.DataFrame:
    """Phase 5/6: does holding THROUGH the confirmation add or destroy value?

    Only trades where the confirmation arrived while still in the position can
    answer this -- for anything else the comparison has no confirmation mark.
    Capture ratios are reported with an explicit zero-denominator count rather
    than silently dropping or infinity-poisoning those rows.
    """
    e = walks.filter(
        pl.col("entered") & pl.col("gross_atr").is_finite()
        & pl.col("confirmed_before_exit")
    )
    if e.height == 0:
        return pl.DataFrame([{"policy": policy, "n": 0}])
    ret_c = e["return_at_confirm_atr"].to_numpy()
    mfe_c = e["mfe_at_confirm_atr"].to_numpy()
    realized = e["gross_atr"].to_numpy()
    incr = realized - ret_c

    boot = rng.integers(0, incr.size, size=(BOOT, incr.size))
    ci = np.percentile(incr[boot].mean(axis=1), [2.5, 97.5])

    def ratio(num: np.ndarray, den: np.ndarray) -> tuple[float, int]:
        ok = np.isfinite(den) & (np.abs(den) > 1e-9)
        return (float(np.median(num[ok] / den[ok])) if ok.sum() else float("nan"),
                int((~ok).sum()))

    cap_ret, z_ret = ratio(realized, ret_c)
    cap_mfe, z_mfe = ratio(realized, mfe_c)
    return pl.DataFrame([{
        "policy": policy, "n": e.height,
        "pct_of_entries": e.height / max(int(walks["entered"].sum()), 1),
        # manifest item 11 names these without a statistic prefix; the median is
        # the headline for each, with the mean carried alongside.
        "return_at_confirm": float(np.nanmedian(ret_c)),
        "mfe_at_confirm": float(np.nanmedian(mfe_c)),
        "return_at_5s_exit": float(np.median(realized)),
        "mfe_at_5s_exit": float(e["mfe_atr"].median()),
        "incremental_atr": float(np.median(incr)),
        "n_zero_denominator": int(z_ret + z_mfe),
        "mean_return_at_confirm": float(np.nanmean(ret_c)),
        "median_return_at_confirm": float(np.nanmedian(ret_c)),
        "mean_mfe_at_confirm": float(np.nanmean(mfe_c)),
        "median_mfe_at_confirm": float(np.nanmedian(mfe_c)),
        "mean_return_at_5s_exit": float(realized.mean()),
        "median_return_at_5s_exit": float(np.median(realized)),
        "mean_mfe_at_5s_exit": float(e["mfe_atr"].mean()),
        "median_incremental_atr": float(np.median(incr)),
        "mean_incremental_atr": float(incr.mean()),
        "incremental_ci_low": float(ci[0]), "incremental_ci_high": float(ci[1]),
        "incremental_ci_excludes_zero": bool(ci[0] > 0 or ci[1] < 0),
        "capture_vs_confirm_return": cap_ret,
        "capture_vs_confirm_mfe": cap_mfe,
        "n_zero_denominator_return": z_ret,
        "n_zero_denominator_mfe": z_mfe,
    }])


# ---------------------------------------------------------- Phase 7: failure


def failure_cost(walks: pl.DataFrame, arms: pl.DataFrame, policy: str) -> pl.DataFrame:
    """Economics on the arms the accepted lifecycle could NOT monetise.

    The cohort is defined by the accepted diagnostic lifecycle (did NOT confirm
    before its 1 ATR stop), which is a property of the arm, not of this policy --
    so the same arms are compared across policies.
    """
    fail_ids = arms.filter(~pl.col("walk_a_confirm_reached_censored"))["regime_id"]
    d = walks.filter(pl.col("regime_id").is_in(fail_ids))
    entered = d.filter(pl.col("entered") & pl.col("gross_atr").is_finite())
    net = entered["net_atr"].to_numpy()
    mae = entered["mae_atr"].to_numpy()
    accepted = arms.filter(~pl.col("walk_a_confirm_reached_censored"))
    return pl.DataFrame([{
        "policy": policy,
        "n_failure_arms": d.height,
        "pct_never_entered": float((~d["entered"]).mean()),
        "n_entered": entered.height,
        "mean_loss": float(net.mean()) if net.size else float("nan"),
        "median_loss": float(np.median(net)) if net.size else float("nan"),
        "p75_adverse": float(np.percentile(mae, 75)) if mae.size else float("nan"),
        "p90_adverse": float(np.percentile(mae, 90)) if mae.size else float("nan"),
        "pct_exited_before_075_adverse": float((mae < 0.75).mean()) if mae.size else float("nan"),
        "pct_exited_before_100_adverse": float((mae < 1.00).mean()) if mae.size else float("nan"),
        "net_atr_total": float(net.sum()),
        # manifest item 12 names this `net_atr_per_arm`; the longer alias is kept
        # because "per arm" here means per FAILURE arm, not per original arm
        "net_atr_per_arm": float(net.sum() / d.height) if d.height else float("nan"),
        "net_atr_per_failure_arm": float(net.sum() / d.height) if d.height else float("nan"),
        "accepted_net_atr_per_failure_arm": float(accepted["walk_a_net_atr"].mean()),
        "accepted_mean_gross_atr": float(accepted["walk_a_gross_atr"].mean()),
    }])


# --------------------------------------------------- Phase 8: preservation


def preservation(walks_s1: pl.DataFrame, walks_s075: pl.DataFrame,
                 arms: pl.DataFrame) -> pl.DataFrame:
    """What the fast regime costs on the arms that DO eventually confirm."""
    ok = arms.filter(pl.col("walk_a_confirm_reached_censored"))
    ids = ok["regime_id"]
    rows = []
    for policy, w in (("S1", walks_s1), ("S075", walks_s075)):
        d = w.filter(pl.col("regime_id").is_in(ids))
        e = d.filter(pl.col("entered") & pl.col("gross_atr").is_finite())
        conf_before = e.filter(pl.col("confirmed_before_exit"))
        stopped_pre = e.filter((pl.col("outcome") == STOP) & ~pl.col("confirmed_before_exit"))
        flipped_pre = e.filter((pl.col("outcome") == FIVE_S_EXIT) & ~pl.col("confirmed_before_exit"))
        rows.append({
            "policy": policy,
            "n_confirming_arms": d.height,
            "pct_qualifying": float(d["entered"].mean()),
            "n_entered": e.height,
            "pct_stopped_before_confirm": stopped_pre.height / e.height if e.height else float("nan"),
            "pct_5s_exit_before_confirm": flipped_pre.height / e.height if e.height else float("nan"),
            "pct_open_at_confirm": conf_before.height / e.height if e.height else float("nan"),
            "net_atr_stopped_before": float(stopped_pre["net_atr"].mean()) if stopped_pre.height else float("nan"),
            "net_atr_5s_exit_before": float(flipped_pre["net_atr"].mean()) if flipped_pre.height else float("nan"),
            "net_atr_open_at_confirm": float(conf_before["net_atr"].mean()) if conf_before.height else float("nan"),
            "eventual_return_stopped_before": float(
                ok.filter(pl.col("regime_id").is_in(stopped_pre["regime_id"]))
                ["walk_a_return_at_confirm_atr"].mean()) if stopped_pre.height else float("nan"),
            "eventual_mfe_stopped_before": float(
                ok.filter(pl.col("regime_id").is_in(stopped_pre["regime_id"]))
                ["walk_a_mfe_to_confirm_atr"].mean()) if stopped_pre.height else float("nan"),
            "eventual_return_5s_exit_before": float(
                ok.filter(pl.col("regime_id").is_in(flipped_pre["regime_id"]))
                ["walk_a_return_at_confirm_atr"].mean()) if flipped_pre.height else float("nan"),
            "eventual_mfe_5s_exit_before": float(
                ok.filter(pl.col("regime_id").is_in(flipped_pre["regime_id"]))
                ["walk_a_mfe_to_confirm_atr"].mean()) if flipped_pre.height else float("nan"),
        })
    # GOOD TRADES LOST TO THE TIGHTER STOP: confirming arms that S1 kept alive to
    # its confirmation but S075 stopped first.
    s1e = walks_s1.filter(pl.col("regime_id").is_in(ids) & pl.col("entered"))
    s75e = walks_s075.filter(pl.col("regime_id").is_in(ids) & pl.col("entered"))
    s1_ok = set(s1e.filter(pl.col("outcome") != STOP)["regime_id"].to_list())
    s75_stopped = set(s75e.filter(pl.col("outcome") == STOP)["regime_id"].to_list())
    killed = s1_ok & s75_stopped
    for r in rows:
        r["n_killed_by_075_surviving_100"] = len(killed)
        r["pct_killed_by_075_surviving_100"] = (
            len(killed) / s1e.height if s1e.height else float("nan"))
    return pl.DataFrame(rows)


# --------------------------------------------------- Phase 9: stop comparison


def stop_comparison(walks_s1: pl.DataFrame, walks_s075: pl.DataFrame,
                    arms: pl.DataFrame, e1: dict, e075: dict) -> pl.DataFrame:
    j = (walks_s1.filter(pl.col("entered") & pl.col("gross_atr").is_finite())
         .select("regime_id", s1_net="net_atr", s1_out="outcome")
         .join(walks_s075.filter(pl.col("entered") & pl.col("gross_atr").is_finite())
               .select("regime_id", s075_net="net_atr", s075_out="outcome"),
               on="regime_id", how="inner"))
    diff = (j["s075_net"] - j["s1_net"]).to_numpy()
    better, worse = diff > 0, diff < 0
    conf_ids = set(arms.filter(pl.col("walk_a_confirm_reached_censored"))["regime_id"].to_list())
    destroyed = j.filter(
        (pl.col("s075_out") == STOP) & (pl.col("s1_out") != STOP)
        & pl.col("regime_id").is_in(list(conf_ids)))
    return pl.DataFrame([{
        "n_common_entries": j.height,
        "d_exp_per_entry": e075["exp_per_entry_net"] - e1["exp_per_entry_net"],
        "d_exp_per_arm": e075["exp_per_arm_net"] - e1["exp_per_arm_net"],
        "d_max_dd": e075["max_dd_atr"] - e1["max_dd_atr"],
        "n_losses_avoided": int(better.sum()),
        "atr_saved_on_failures": float(diff[better].sum()),
        "n_winners_destroyed": int(worse.sum()),
        "atr_forfeited_on_successes": float(diff[worse].sum()),
        "n_confirm_trades_destroyed": destroyed.height,
        "atr_forfeited_on_confirm_trades": float(
            (destroyed["s075_net"] - destroyed["s1_net"]).sum()) if destroyed.height else 0.0,
        "net_tradeoff_atr": float(diff.sum()),
        "net_tradeoff_per_arm": float(diff.sum() / ARMED_REQUIRED),
    }])


# ------------------------------------------- Phase 10: non-entry counterfactual


def nonentry_future_alignment(walks: pl.DataFrame, arms: pl.DataFrame, r5,
                              market, regimes) -> pl.DataFrame:
    """DESCRIPTIVE ONLY (SPEC section 10). Never traded in this study.

    For arms where the 5s regime was NOT aligned, when does a fresh aligned 5s
    state first appear, and does it beat the confirmation / the 1 ATR stop there?
    """
    d = walks.filter(~pl.col("entered")).join(
        arms.select("regime_id", "walk_a_confirm_reached_censored",
                    "walk_a_confirm_ns", "walk_a_stop_ns", "walk_a_terminal_ns"),
        on="regime_id", how="left")
    rows = []
    for r in d.iter_rows(named=True):
        arm_ns, dirn = int(r["arm_ns"]), int(r["direction"])
        nxt = r5.first_aligned_after(arm_ns, dirn)
        secs = float("nan") if nxt < 0 else (nxt - arm_ns) / NS
        conf = r["walk_a_confirm_ns"]
        stop = r["walk_a_stop_ns"]
        term = r["walk_a_terminal_ns"]
        rows.append({
            "regime_id": r["regime_id"], "side": r["side"],
            "entry_year": r["entry_year"], "alignment": r["alignment"],
            "secs_to_first_aligned": secs,
            "before_confirm": bool(nxt >= 0 and conf is not None and nxt < int(conf)),
            "before_1atr_stop": bool(nxt >= 0 and stop is not None and nxt < int(stop)),
            "before_invalidation": bool(nxt >= 0 and term is not None and nxt < int(term)),
            "eventually_confirmed": bool(r["walk_a_confirm_reached_censored"]),
        })
    f = pl.DataFrame(rows)
    s = f["secs_to_first_aligned"].to_numpy()
    masks = {
        "<=15": s <= 15, "16-30": (s > 15) & (s <= 30), "31-60": (s > 30) & (s <= 60),
        "61-120": (s > 60) & (s <= 120), ">120": s > 120, "never": ~np.isfinite(s),
    }
    out = []
    for bucket, m in masks.items():
        sub = f.filter(pl.Series(m))
        out.append({
            "bucket": bucket, "n": int(m.sum()),
            "pct": float(m.sum() / f.height) if f.height else float("nan"),
            "pct_before_confirm": float(sub["before_confirm"].mean()) if sub.height else float("nan"),
            "pct_before_1atr_stop": float(sub["before_1atr_stop"].mean()) if sub.height else float("nan"),
            "pct_before_invalidation": float(sub["before_invalidation"].mean()) if sub.height else float("nan"),
            "eventual_confirm_rate": float(sub["eventually_confirmed"].mean()) if sub.height else float("nan"),
        })
    return pl.DataFrame(out)


# ---------------------------------------------------- Phase 11: age diagnostic


def age_diagnostic(geom: pl.DataFrame, policy: str) -> pl.DataFrame:
    """DESCRIPTIVE ONLY. Does 'already aligned' show obvious late entry?"""
    rows = []
    for bucket in ("exactly_on_flip", "1-5s", "6-15s", "16-30s", ">30s"):
        d = geom.filter(pl.col("arm_offset_bucket") == bucket)
        rows.append({
            "policy": policy, "age_bucket": bucket, "n": d.height,
            "pct": d.height / geom.height if geom.height else float("nan"),
            "win_rate": float((d["net_atr"] > 0).mean()) if d.height else float("nan"),
            "mean_net_atr": float(d["net_atr"].mean()) if d.height else float("nan"),
            "median_net_atr": float(d["net_atr"].median()) if d.height else float("nan"),
            "mean_mfe": float(d["mfe_atr"].mean()) if d.height else float("nan"),
            "mean_mae": float(d["mae_atr"].mean()) if d.height else float("nan"),
            "median_hold_s": float(d["hold_s"].median()) if d.height else float("nan"),
        })
    return pl.DataFrame(rows)


# ------------------------------------------------------- stability breakdowns


def by_group(walks: pl.DataFrame, policy: str, col: str) -> pl.DataFrame:
    rows = []
    for key in sorted(walks[col].unique().to_list()):
        d = walks.filter(pl.col(col) == key)
        e = economics(d, policy)
        e[col] = key
        rows.append(e)
    return pl.DataFrame(rows)
