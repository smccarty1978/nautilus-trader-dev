"""Phases 1-11 and the two primary tables (SPEC section 4, section 8 manifest).

Every function here is purely descriptive (SPEC section 6/11): none produces
a threshold used by any policy, because there is no policy in this study.
The grouping variable throughout is `with_5m_at_p90` (SPEC section 5's
adjudicated decision-timestamp rule) except Phase 5's transition matrix and
Phase 6's label-only frame, which are explicitly scoped otherwise.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from studies.p90_5m_regime_context.implementation.regime_5m import Regime5m

ROOT = Path(__file__).resolve().parents[3]
SIBLING = ROOT / "studies/p90_conditional_losing_5s_exit/results"

GROUP_ORDER = ("WITH_5M", "AGAINST_5M", "UNINIT")


def _group_col(with_5m: pl.Expr, against_5m: pl.Expr, uninit: pl.Expr) -> pl.Expr:
    return (
        pl.when(with_5m).then(pl.lit("WITH_5M"))
        .when(against_5m).then(pl.lit("AGAINST_5M"))
        .otherwise(pl.lit("UNINIT"))
    )


def build_base(arms: pl.DataFrame, classification: pl.DataFrame) -> pl.DataFrame:
    """Arms joined with the core classification -- the base frame for
    Phases 1, 2, 3, 4, 5, 7, 10 (SPEC section 4)."""
    cls = classification.select(
        "regime_id", "with_5m_at_p90", "against_5m_at_p90", "uninit_at_p90",
        "regime_age_s_at_p90", "regime_age_bars_at_p90", "age_bucket",
        "with_5m_at_confirm",
    )
    return arms.join(cls, on="regime_id", how="left").with_columns(
        group=_group_col(pl.col("with_5m_at_p90"), pl.col("against_5m_at_p90"),
                         pl.col("uninit_at_p90"))
    )


def _pctl(s: pl.Series, q: float) -> float:
    return float(s.quantile(q)) if s.len() else float("nan")


def _safe_mean(s: pl.Series) -> float:
    return float(s.mean()) if s.len() else float("nan")


def _safe_median(s: pl.Series) -> float:
    return float(s.median()) if s.len() else float("nan")


# --------------------------------------------------------------- Phase 1 ---

def phase1_context(base: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for side in (None, "LONG", "SHORT"):
        for year in (None, *sorted(base["entry_year"].unique().to_list())):
            sub = base
            if side is not None:
                sub = sub.filter(pl.col("side") == side)
            if year is not None:
                sub = sub.filter(pl.col("entry_year") == year)
            n_total = sub.height
            for g in GROUP_ORDER:
                gsub = sub.filter(pl.col("group") == g)
                for ab in ("0-5min", "5-15min", "15-30min", "30-60min", ">60min", None):
                    absub = gsub if ab is None else gsub.filter(pl.col("age_bucket") == ab)
                    rows.append({
                        "group": g, "side": side or "ALL", "entry_year": year or 0,
                        "age_bucket": ab or "ALL", "n": absub.height,
                        "pct_population": (absub.height / n_total) if n_total else float("nan"),
                    })
    return pl.DataFrame(rows)


# --------------------------------------------------------------- Phase 2 ---

def _pre_confirm_row(sub: pl.DataFrame, group: str, stratum: str, stratum_value) -> dict:
    n = sub.height
    conf = sub.filter(pl.col("walk_a_confirm_reached_censored"))
    mae, mfe = conf["walk_a_mae_to_confirm_atr"], conf["walk_a_mfe_to_confirm_atr"]
    sec, ret = conf["walk_a_seconds_to_confirm"], conf["walk_a_return_at_confirm_atr"]
    return {
        "stratum": stratum, "stratum_value": str(stratum_value), "group": group, "n": n,
        "p_confirm_lt_1atr": _safe_mean(sub["walk_a_confirm_reached_censored"].cast(pl.Float64)),
        "p_stop_before_confirm": (float((sub["terminal_label_full"] == "STOPPED_BEFORE_CONFIRM").mean())
                                  if n else float("nan")),
        "sec_to_confirm_mean": _safe_mean(sec), "sec_to_confirm_median": _safe_median(sec),
        "sec_to_confirm_p25": _pctl(sec, 0.25), "sec_to_confirm_p75": _pctl(sec, 0.75),
        "sec_to_confirm_p90": _pctl(sec, 0.90),
        "mae_to_confirm_mean": _safe_mean(mae), "mae_to_confirm_p50": _pctl(mae, 0.50),
        "mae_to_confirm_p75": _pctl(mae, 0.75), "mae_to_confirm_p80": _pctl(mae, 0.80),
        "mae_to_confirm_p90": _pctl(mae, 0.90), "mae_to_confirm_p95": _pctl(mae, 0.95),
        "mfe_to_confirm_mean": _safe_mean(mfe), "mfe_to_confirm_median": _safe_median(mfe),
        "mfe_to_confirm_p75": _pctl(mfe, 0.75), "mfe_to_confirm_p90": _pctl(mfe, 0.90),
        "return_at_confirm_mean": _safe_mean(ret), "return_at_confirm_median": _safe_median(ret),
    }


def phase2_pre_confirm(base: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for g in GROUP_ORDER:
        gsub = base.filter(pl.col("group") == g)
        rows.append(_pre_confirm_row(gsub, g, "ALL", "ALL"))
        for side in ("LONG", "SHORT"):
            rows.append(_pre_confirm_row(gsub.filter(pl.col("side") == side), g, "side", side))
        for year in sorted(base["entry_year"].unique().to_list()):
            rows.append(_pre_confirm_row(gsub.filter(pl.col("entry_year") == year), g, "entry_year", year))
    return pl.DataFrame(rows)


# --------------------------------------------------------------- Phase 3 ---

SPEED_EDGES = (60, 120, 300)
SPEED_LABELS = ("<=60s", "61-120s", "121-300s", ">300s")


def phase3_confirmation_speed(base: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for g in GROUP_ORDER:
        gsub = base.filter(pl.col("group") == g)
        n_group = gsub.height
        conf = gsub.filter(pl.col("walk_a_confirm_reached_censored"))
        sec = conf["walk_a_seconds_to_confirm"].to_numpy()
        idx = np.searchsorted(SPEED_EDGES, sec, side="right")
        bucket = np.array(SPEED_LABELS, dtype=object)[np.clip(idx, 0, len(SPEED_LABELS) - 1)]
        conf = conf.with_columns(speed_bucket=pl.Series(bucket))
        for b in (*SPEED_LABELS, "NO_CONFIRM"):
            if b == "NO_CONFIRM":
                sub = gsub.filter(~pl.col("walk_a_confirm_reached_censored"))
            else:
                sub = conf.filter(pl.col("speed_bucket") == b)
            rows.append({
                "group": g, "speed_bucket": b, "n": sub.height,
                "confirm_rate": (sub.height / n_group) if n_group else float("nan"),
                "mae_to_confirm_mean": _safe_mean(sub["walk_a_mae_to_confirm_atr"]) if b != "NO_CONFIRM" else float("nan"),
                "mfe_to_confirm_mean": _safe_mean(sub["walk_a_mfe_to_confirm_atr"]) if b != "NO_CONFIRM" else float("nan"),
                "return_at_confirm_mean": _safe_mean(sub["walk_a_return_at_confirm_atr"]) if b != "NO_CONFIRM" else float("nan"),
                "eventual_maxmfe_mean": _safe_mean(sub["full_mfe_atr"]),
                "terminal_return_mean": _safe_mean(sub["full_net_atr"]),
            })
    return pl.DataFrame(rows)


# --------------------------------------------------------------- Phase 4 ---

MFE_EDGES = (1.0, 2.0, 3.0, 4.0)
MFE_LABELS = ("<1.0 ATR", "1.0-2.0 ATR", "2.0-3.0 ATR", "3.0-4.0 ATR", ">=4.0 ATR")


def phase4_mfe_quality(base: pl.DataFrame) -> pl.DataFrame:
    conf = base.filter(pl.col("walk_a_confirm_reached_censored"))
    idx = np.searchsorted(MFE_EDGES, conf["full_mfe_atr"].to_numpy(), side="right")
    bucket = np.array(MFE_LABELS, dtype=object)[np.clip(idx, 0, len(MFE_LABELS) - 1)]
    conf = conf.with_columns(mfe_bucket=pl.Series(bucket))
    n_conf = conf.height
    rows = []
    for mb in MFE_LABELS:
        bsub = conf.filter(pl.col("mfe_bucket") == mb)
        n_bucket = bsub.height
        for g in GROUP_ORDER:
            gsub = bsub.filter(pl.col("group") == g)
            g_total = conf.filter(pl.col("group") == g).height
            rows.append({
                "mfe_bucket": mb, "group": g, "n": gsub.height,
                "pct_of_group": (gsub.height / g_total) if g_total else float("nan"),
                "pct_of_bucket": (gsub.height / n_bucket) if n_bucket else float("nan"),
            })
    return pl.DataFrame(rows)


# --------------------------------------------------------------- Phase 5 ---

def phase5_transition_matrix(base: pl.DataFrame) -> pl.DataFrame:
    conf = base.filter(pl.col("walk_a_confirm_reached_censored")
                       & pl.col("with_5m_at_confirm").is_not_null())
    n_conf = conf.height
    conf = conf.with_columns(
        transition=pl.when(pl.col("with_5m_at_p90") & pl.col("with_5m_at_confirm"))
        .then(pl.lit("WITH_WITH"))
        .when(pl.col("with_5m_at_p90") & ~pl.col("with_5m_at_confirm"))
        .then(pl.lit("WITH_AGAINST"))
        .when(~pl.col("with_5m_at_p90") & pl.col("with_5m_at_confirm"))
        .then(pl.lit("AGAINST_WITH"))
        .otherwise(pl.lit("AGAINST_AGAINST")),
        additional_mfe=(pl.col("full_mfe_atr") - pl.col("walk_a_mfe_to_confirm_atr")).clip(0),
        giveback=(pl.col("full_mfe_atr") - pl.col("full_net_atr")),
    )
    rows = []
    for t in ("WITH_WITH", "WITH_AGAINST", "AGAINST_WITH", "AGAINST_AGAINST"):
        sub = conf.filter(pl.col("transition") == t)
        n = sub.height
        flip_exits = sub.filter(pl.col("terminal_label_full").is_in(
            ["FINAL_FLIP_EXIT_WINNER", "FINAL_FLIP_EXIT_LOSER"]))
        rows.append({
            "transition": t, "n": n,
            "pct_of_confirming": (n / n_conf) if n_conf else float("nan"),
            "return_at_confirm_mean": _safe_mean(sub["walk_a_return_at_confirm_atr"]),
            "mfe_at_confirm_mean": _safe_mean(sub["walk_a_mfe_to_confirm_atr"]),
            "mae_to_confirm_mean": _safe_mean(sub["walk_a_mae_to_confirm_atr"]),
            "sec_to_confirm_mean": _safe_mean(sub["walk_a_seconds_to_confirm"]),
            "subsequent_additional_mfe_mean": _safe_mean(sub["additional_mfe"]),
            "eventual_maxmfe_mean": _safe_mean(sub["full_mfe_atr"]),
            "terminal_return_mean": _safe_mean(sub["full_net_atr"]),
            "flip_exit_win_rate": (float((flip_exits["terminal_label_full"]
                                         == "FINAL_FLIP_EXIT_WINNER").mean())
                                   if flip_exits.height else float("nan")),
            "confirmed_then_stopped_pct": (float((sub["terminal_label_full"]
                                                  == "CONFIRMED_THEN_STOPPED").mean())
                                           if n else float("nan")),
            "session_exit_pct": (float((sub["terminal_label_full"] == "SESSION_EXIT").mean())
                                 if n else float("nan")),
            "giveback_mean": _safe_mean(sub["giveback"]), "giveback_median": _safe_median(sub["giveback"]),
            "p_mfe_ge_3atr": (float((sub["full_mfe_atr"] >= 3.0).mean()) if n else float("nan")),
            "p_mfe_ge_4atr": (float((sub["full_mfe_atr"] >= 4.0).mean()) if n else float("nan")),
        })
    return pl.DataFrame(rows)


def phase5_against_with_deep_dive(transition_matrix: pl.DataFrame) -> pl.DataFrame:
    keep = ("WITH_WITH", "AGAINST_WITH", "AGAINST_AGAINST")
    sub = transition_matrix.filter(pl.col("transition").is_in(keep))
    return sub.select(
        "transition", "n",
        pl.col("sec_to_confirm_mean").alias("confirmation_speed_median_s"),
        pl.col("mae_to_confirm_mean").alias("mae_mean"),
        "return_at_confirm_mean", "eventual_maxmfe_mean",
        "p_mfe_ge_3atr", "p_mfe_ge_4atr", "terminal_return_mean",
    )


# --------------------------------------------------------------- Phase 6 ---

def phase6_timing(phase6_labels: pl.DataFrame, arms: pl.DataFrame) -> pl.DataFrame:
    """One row per arm (SPEC section 8 manifest #9, amended during
    implementation to resolve a per-arm/per-bucket granularity mismatch).
    Per-bucket confirmation rate / MFE / MAE / terminal return (the
    aggregates Phase 6's prose describes) are obtained by grouping this
    table on `timing_bucket` -- see `phase6_bucket_summary` below, produced
    for the REPORT.md narrative but not itself a manifest deliverable."""
    return phase6_labels.join(
        arms.select("regime_id", "walk_a_confirm_reached_censored", "full_mfe_atr",
                    "full_mae_atr", "full_net_atr"),
        on="regime_id", how="left",
    ).select(
        "regime_id", "direction", "side", "entry_year",
        "label_only_p90_relative_to_5m_flip", "label_only_p90_to_5m_flip_s", "timing_bucket",
        pl.col("walk_a_confirm_reached_censored").alias("confirmed"),
        pl.col("full_mfe_atr").alias("mfe_atr"), pl.col("full_mae_atr").alias("mae_atr"),
        pl.col("full_net_atr").alias("terminal_return_atr"),
    )


def phase6_bucket_summary(phase6_timing: pl.DataFrame) -> pl.DataFrame:
    """Report-only aggregate (not a manifest deliverable): groups
    `phase6_timing.csv` by `timing_bucket` for REPORT.md's narrative."""
    rows = []
    for bucket in phase6_timing["timing_bucket"].unique().sort().to_list():
        sub = phase6_timing.filter(pl.col("timing_bucket") == bucket)
        n = sub.height
        rows.append({
            "timing_bucket": bucket, "n": n,
            "label_only_p90_relative_to_5m_flip": sub["label_only_p90_relative_to_5m_flip"][0],
            "confirm_rate": (float(sub["confirmed"].mean()) if n else float("nan")),
            "mfe_mean": _safe_mean(sub["mfe_atr"]), "mae_mean": _safe_mean(sub["mae_atr"]),
            "terminal_return_mean": _safe_mean(sub["terminal_return_atr"]),
        })
    return pl.DataFrame(rows)


# --------------------------------------------------------------- Phase 7 ---

def phase7_regime_age(base: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for g in ("WITH_5M", "AGAINST_5M"):
        gsub = base.filter(pl.col("group") == g)
        for ab in ("0-5min", "5-15min", "15-30min", "30-60min", ">60min"):
            sub = gsub.filter(pl.col("age_bucket") == ab)
            n = sub.height
            conf = sub.filter(pl.col("walk_a_confirm_reached_censored"))
            rows.append({
                "group": g, "age_bucket": ab, "n": n,
                "p_confirm": (conf.height / n) if n else float("nan"),
                "mae_to_confirm_mean": _safe_mean(conf["walk_a_mae_to_confirm_atr"]),
                "return_at_confirm_mean": _safe_mean(conf["walk_a_return_at_confirm_atr"]),
                "eventual_maxmfe_mean": _safe_mean(sub["full_mfe_atr"]),
                "p_mfe_ge_3atr": (float((sub["full_mfe_atr"] >= 3.0).mean()) if n else float("nan")),
                "terminal_return_mean": _safe_mean(sub["full_net_atr"]),
            })
    return pl.DataFrame(rows)


# --------------------------------------------------------------- Phase 8 ---

def phase8_5s_failure(arms: pl.DataFrame, classification: pl.DataFrame, r5m: Regime5m) -> pl.DataFrame:
    flips = pl.read_parquet(SIBLING / "adverse_5s_flip_events.parquet")
    n_5s_entered = pl.read_parquet(SIBLING / "baseline_100.parquet", columns=["regime_id"]).height
    n_total = arms.height
    n_not_entered = n_total - n_5s_entered

    qualifying = flips.filter(pl.col("is_losing") & pl.col("before_confirm"))
    first = (qualifying.sort("flip_number").group_by("regime_id")
             .agg(pl.first("flip_ns").alias("flip_ns"),
                  pl.first("current_return_atr").alias("current_return_atr")))
    first = first.join(
        arms.select("regime_id", "direction", "walk_a_confirm_reached_censored",
                    "walk_a_return_at_confirm_atr"),
        on="regime_id", how="left",
    ).join(classification.select("regime_id", "with_5m_at_p90"), on="regime_id", how="left")

    d = first["direction"].to_numpy()
    fns = first["flip_ns"].to_numpy()
    state_at_flip = r5m.state_at(fns)
    with_at_flip = (state_at_flip == d) & (state_at_flip != 0)
    first = first.with_columns(
        group_at_flip=pl.Series(np.where(with_at_flip, "FAILURE_SIGNAL_WITH_5M",
                                         "FAILURE_SIGNAL_AGAINST_5M")),
        group_at_p90=pl.when(pl.col("with_5m_at_p90")).then(pl.lit("FAILURE_SIGNAL_WITH_5M"))
        .otherwise(pl.lit("FAILURE_SIGNAL_AGAINST_5M")),
    )

    rows = []
    for join_point, gcol in (("AT_5S_FLIP", "group_at_flip"), ("AT_P90", "group_at_p90")):
        for g in ("FAILURE_SIGNAL_WITH_5M", "FAILURE_SIGNAL_AGAINST_5M"):
            sub = first.filter(pl.col(gcol) == g)
            n = sub.height
            conf = sub.filter(pl.col("walk_a_confirm_reached_censored"))
            rows.append({
                "join_point": join_point, "group": g, "n": n,
                "n_total_8950": n_total, "n_5s_entered_8379": n_5s_entered,
                "n_not_5s_entered_571": n_not_entered,
                "confirm_pct": (conf.height / n) if n else float("nan"),
                "failure_pct": ((n - conf.height) / n) if n else float("nan"),
                "ppv_failure": ((n - conf.height) / n) if n else float("nan"),
                "conditional_exit_return_mean": _safe_mean(sub["current_return_atr"]),
                "accepted_continuation_return_mean": _safe_mean(conf["walk_a_return_at_confirm_atr"]),
            })
        rows.append({
            "join_point": join_point, "group": "NOT_5S_ENTERED", "n": n_not_entered,
            "n_total_8950": n_total, "n_5s_entered_8379": n_5s_entered,
            "n_not_5s_entered_571": n_not_entered,
            "confirm_pct": float("nan"), "failure_pct": float("nan"),
            "ppv_failure": float("nan"), "conditional_exit_return_mean": float("nan"),
            "accepted_continuation_return_mean": float("nan"),
        })
    return pl.DataFrame(rows)


# --------------------------------------------------------------- Phase 9 ---

def phase9_stop_context(base: pl.DataFrame) -> pl.DataFrame:
    b100 = pl.read_parquet(SIBLING / "baseline_100.parquet",
                           columns=["regime_id", "net_atr", "terminal_label_full"]
                           ).rename({"net_atr": "net_100"})
    b075 = pl.read_parquet(SIBLING / "baseline_075.parquet",
                           columns=["regime_id", "net_atr"]).rename({"net_atr": "net_075"})
    n_total = base.height
    n_5s_entered = b100.height
    n_not_entered = n_total - n_5s_entered

    joined = base.join(b100, on="regime_id", how="left").join(b075, on="regime_id", how="left")
    rows = []
    for g in ("WITH_5M", "AGAINST_5M"):
        gsub = joined.filter(pl.col("group") == g)
        conf = gsub.filter(pl.col("walk_a_confirm_reached_censored"))
        n_conf = conf.height
        failures = gsub.filter((pl.col("terminal_label_full") == "STOPPED_BEFORE_CONFIRM")
                               & pl.col("net_100").is_not_null())
        reduction = (
            (_safe_mean(failures["net_100"]) - _safe_mean(failures["net_075"]))
            if failures.height else float("nan")
        )
        rows.append({
            "group": g, "n_confirming": n_conf, "n_total_8950": n_total,
            "n_5s_entered_8379": n_5s_entered, "n_not_5s_entered_571": n_not_entered,
            "pct_mae_gt_075": (float((conf["walk_a_mae_to_confirm_atr"] > 0.75).mean())
                              if n_conf else float("nan")),
            "failure_loss_reduction_075_vs_100": reduction,
        })
    gsub = joined.filter(pl.col("net_100").is_null())
    conf = gsub.filter(pl.col("walk_a_confirm_reached_censored"))
    rows.append({
        "group": "NOT_5S_ENTERED", "n_confirming": conf.height, "n_total_8950": n_total,
        "n_5s_entered_8379": n_5s_entered, "n_not_5s_entered_571": n_not_entered,
        "pct_mae_gt_075": (float((conf["walk_a_mae_to_confirm_atr"] > 0.75).mean())
                          if conf.height else float("nan")),
        "failure_loss_reduction_075_vs_100": float("nan"),
    })
    return pl.DataFrame(rows)


# -------------------------------------------------------------- Phase 10 ---

def _max_drawdown(net: np.ndarray, order: np.ndarray) -> float:
    if net.size == 0:
        return 0.0
    curve = np.cumsum(net[np.argsort(order, kind="stable")])
    return float(np.max(np.maximum.accumulate(curve) - curve))


def _economics_row(sub: pl.DataFrame, key: dict) -> dict:
    if sub.height == 0:
        # SPEC section 8.1: an empty bucket/cell is retained with n=0, never
        # silently dropped from the table.
        nan = float("nan")
        return {**key, "n_arms": 0, "expectancy_per_arm": nan, "gross_atr_total": nan,
                "net_atr_total": nan, "profit_factor": nan, "win_rate": nan,
                "max_dd_atr": nan, "mean_winner": nan, "mean_loser": nan,
                "flip_exit_winner_pct": nan, "flip_exit_loser_pct": nan,
                "confirmed_then_stopped_pct": nan, "mfe_mean": nan, "mae_mean": nan,
                "giveback_mean": nan, "capture_ratio_mean": nan}
    net = sub["full_net_atr"].to_numpy()
    gross = sub["full_gross_atr"].to_numpy()
    mfe, mae = sub["full_mfe_atr"].to_numpy(), sub["full_mae_atr"].to_numpy()
    wins, losses = net[net > 0], net[net < 0]
    flip_exits = sub.filter(pl.col("terminal_label_full").is_in(
        ["FINAL_FLIP_EXIT_WINNER", "FINAL_FLIP_EXIT_LOSER"]))
    capture = np.where(mfe > 0, net / mfe, np.nan)
    return {
        **key, "n_arms": sub.height,
        "expectancy_per_arm": float(net.mean()) if net.size else float("nan"),
        "gross_atr_total": float(gross.sum()), "net_atr_total": float(net.sum()),
        "profit_factor": (float(wins.sum() / -losses.sum())
                          if losses.size and losses.sum() != 0 else float("nan")),
        "win_rate": float((net > 0).mean()) if net.size else float("nan"),
        "max_dd_atr": _max_drawdown(net, sub["arm_top10_ns"].to_numpy()),
        "mean_winner": float(wins.mean()) if wins.size else float("nan"),
        "mean_loser": float(losses.mean()) if losses.size else float("nan"),
        "flip_exit_winner_pct": float((sub["terminal_label_full"] == "FINAL_FLIP_EXIT_WINNER").mean()),
        "flip_exit_loser_pct": float((sub["terminal_label_full"] == "FINAL_FLIP_EXIT_LOSER").mean()),
        "confirmed_then_stopped_pct": float((sub["terminal_label_full"] == "CONFIRMED_THEN_STOPPED").mean()),
        "mfe_mean": float(np.nanmean(mfe)) if mfe.size else float("nan"),
        "mae_mean": float(np.nanmean(mae)) if mae.size else float("nan"),
        "giveback_mean": float(np.nanmean(mfe - net)) if mfe.size else float("nan"),
        "capture_ratio_mean": float(np.nanmean(capture)) if capture.size else float("nan"),
    }


def phase10_full_economics(base: pl.DataFrame) -> pl.DataFrame:
    return pl.DataFrame([_economics_row(base.filter(pl.col("group") == g), {"group": g})
                         for g in GROUP_ORDER])


def phase10_by_year(base: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for g in GROUP_ORDER:
        for y in sorted(base["entry_year"].unique().to_list()):
            sub = base.filter((pl.col("group") == g) & (pl.col("entry_year") == y))
            if sub.height:
                rows.append(_economics_row(sub, {"group": g, "entry_year": y}))
    return pl.DataFrame(rows)


def phase10_by_side(base: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for g in GROUP_ORDER:
        for s in ("LONG", "SHORT"):
            sub = base.filter((pl.col("group") == g) & (pl.col("side") == s))
            if sub.height:
                rows.append(_economics_row(sub, {"group": g, "side": s}))
    return pl.DataFrame(rows)


# -------------------------------------------------------------- Phase 11 ---

def phase11_matched_control(base: pl.DataFrame, strata: pl.DataFrame) -> pl.DataFrame:
    """Exposure-weighted stratified delta (SPEC section 4, Phase 11). Not a
    fitted propensity model -- descriptive stratify-then-average only."""
    j = base.filter(pl.col("group") != "UNINIT").join(
        strata.select("regime_id", "time_of_day", "arm_score_quartile", "regime_age_1m_bucket"),
        on="regime_id", how="left",
    )
    j = j.with_columns(
        mfe_ge_3atr=(pl.col("full_mfe_atr") >= 3.0),
        confirm=pl.col("walk_a_confirm_reached_censored"),
    )
    cells = j.group_by("entry_year", "side", "time_of_day", "arm_score_quartile",
                       "regime_age_1m_bucket", "group").agg(
        n=pl.len(), confirm_rate=pl.col("confirm").mean(),
        return_at_confirm=pl.col("walk_a_return_at_confirm_atr").mean(),
        p_mfe_ge_3atr=pl.col("mfe_ge_3atr").mean(),
    )
    wide = cells.pivot(on="group", index=["entry_year", "side", "time_of_day",
                                          "arm_score_quartile", "regime_age_1m_bucket"],
                       values=["n", "confirm_rate", "return_at_confirm", "p_mfe_ge_3atr"])
    with_n = pl.col("n_WITH_5M").fill_null(0)
    against_n = pl.col("n_AGAINST_5M").fill_null(0)
    both = (with_n > 0) & (against_n > 0)
    valid = wide.filter(both)
    n_cells = wide.height

    def _weighted_delta(a_col: str, b_col: str) -> tuple[float, float]:
        # A cell can have arms on both sides (both >= 1 by construction) but
        # zero CONFIRMING arms on one side, leaving a null mean for
        # confirm-conditioned metrics (return_at_confirm). Such cells cannot
        # contribute to this metric's delta and are dropped here, not
        # silently propagated as NaN through the whole average.
        a_vals = valid[a_col].to_numpy().astype(float)
        b_vals = valid[b_col].to_numpy().astype(float)
        n_a = valid["n_WITH_5M"].to_numpy().astype(float)
        n_b = valid["n_AGAINST_5M"].to_numpy().astype(float)
        finite = np.isfinite(a_vals) & np.isfinite(b_vals)
        if not finite.any():
            return float("nan"), float("nan")
        a_vals, b_vals, n_a, n_b = a_vals[finite], b_vals[finite], n_a[finite], n_b[finite]
        weight = n_a + n_b
        delta = a_vals - b_vals
        raw_a = float((a_vals * n_a).sum() / n_a.sum()) if n_a.sum() else float("nan")
        raw_b = float((b_vals * n_b).sum() / n_b.sum()) if n_b.sum() else float("nan")
        stratified = float(np.average(delta, weights=weight)) if weight.sum() else float("nan")
        return raw_a - raw_b, stratified

    raw_confirm, strat_confirm = _weighted_delta("confirm_rate_WITH_5M", "confirm_rate_AGAINST_5M")
    raw_ret, strat_ret = _weighted_delta("return_at_confirm_WITH_5M", "return_at_confirm_AGAINST_5M")
    raw_mfe3, strat_mfe3 = _weighted_delta("p_mfe_ge_3atr_WITH_5M", "p_mfe_ge_3atr_AGAINST_5M")

    # bootstrap CI over cells for the stratified confirm-rate delta
    rng = np.random.default_rng(20260812)
    n_a = valid["n_WITH_5M"].to_numpy()
    n_b = valid["n_AGAINST_5M"].to_numpy()
    weight = n_a + n_b
    delta = valid["confirm_rate_WITH_5M"].to_numpy() - valid["confirm_rate_AGAINST_5M"].to_numpy()
    if delta.size:
        idx = rng.integers(0, delta.size, size=(2000, delta.size))
        boots = np.array([np.average(delta[i], weights=weight[i]) if weight[i].sum() else np.nan
                          for i in idx])
        ci_low, ci_high = np.nanpercentile(boots, [2.5, 97.5])
    else:
        ci_low, ci_high = float("nan"), float("nan")

    return pl.DataFrame([{
        "stratum_vars": "entry_year,side,time_of_day,arm_score_quartile,regime_age_1m_bucket",
        "n_cells": n_cells, "n_cells_both_present": valid.height,
        "n_with": int(wide["n_WITH_5M"].fill_null(0).sum()),
        "n_against": int(wide["n_AGAINST_5M"].fill_null(0).sum()),
        "raw_delta_confirm_rate": raw_confirm, "stratified_delta_confirm_rate": strat_confirm,
        "raw_delta_return_at_confirm": raw_ret, "stratified_delta_return_at_confirm": strat_ret,
        "raw_delta_p_mfe_ge_3atr": raw_mfe3, "stratified_delta_p_mfe_ge_3atr": strat_mfe3,
        "delta_ci_low": float(ci_low), "delta_ci_high": float(ci_high),
        "ci_excludes_zero": bool(ci_low > 0 or ci_high < 0) if np.isfinite(ci_low) else False,
    }])


# ------------------------------------------------------------- primary -----

def primary_table(base: pl.DataFrame) -> pl.DataFrame:
    w = base.filter(pl.col("group") == "WITH_5M")
    a = base.filter(pl.col("group") == "AGAINST_5M")

    def col(sub: pl.DataFrame) -> dict:
        conf = sub.filter(pl.col("walk_a_confirm_reached_censored"))
        mae = conf["walk_a_mae_to_confirm_atr"]
        return {
            "P90 arms": sub.height, "% population": sub.height / base.height,
            "P(confirm<1ATR)": _safe_mean(sub["walk_a_confirm_reached_censored"].cast(pl.Float64)),
            "median sec to confirm": _safe_median(conf["walk_a_seconds_to_confirm"]),
            "MAE->confirm p50": _pctl(mae, 0.50), "MAE->confirm p75": _pctl(mae, 0.75),
            "MAE->confirm p90": _pctl(mae, 0.90),
            "median return @ confirm": _safe_median(conf["walk_a_return_at_confirm_atr"]),
            "median eventual MaxMFE": _safe_median(sub["full_mfe_atr"]),
            "P(MFE>=3ATR)": float((sub["full_mfe_atr"] >= 3.0).mean()),
            "P(MFE>=4ATR)": float((sub["full_mfe_atr"] >= 4.0).mean()),
            "baseline net ATR / P90 arm": _safe_mean(sub["full_net_atr"]),
            "MaxDD": _max_drawdown(sub["full_net_atr"].to_numpy(), sub["arm_top10_ns"].to_numpy()),
        }

    wcol, acol = col(w), col(a)
    return pl.DataFrame([{"metric": k, "WITH_5M": wcol[k], "AGAINST_5M": acol[k]} for k in wcol])
