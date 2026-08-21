"""Phases 2-13 and the two primary tables (SPEC section 4, section 7 manifest).

Almost every table here is a direct read or trivial derived arithmetic on
`observation_panel.parquet` (SPEC section 1.1) -- this study performs no
trade-lifecycle simulation. The two genuinely new pieces of logic are the
Phase 6 capture-curve time-to-threshold scan (this file) and the Phase 1
at-confirmation 5m state (join.py). All tables are computed under BOTH
`population_definition` values (TRANSITION using `group_transition`,
STABLE_STATE using `group_stable`, dropping the null rows for the latter),
per SPEC section 4 Phase 0's "conclusions are unchanged" requirement.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from studies.p90_5m_regime_context.implementation.classify import _bucket, time_of_day_bucket

ROOT = Path(__file__).resolve().parents[3]
PANEL_PATH = (ROOT / "studies/post_confirm_forward_opportunity/results"
              / "observation_panel.parquet")

LANDMARKS = (30, 60, 120, 180, 300, 600)
CAPTURE_THRESHOLDS = (0.25, 0.50, 0.75, 0.90)
POP_DEFS = ("TRANSITION", "STABLE_STATE")
GROUPS = ("WITH_5M", "AGAINST_5M")

#: SPEC section 4 Phase 8's frozen four pairs, mapped onto the panel's D6
#: race-column suffixes.
RACE_PAIRS = {
    "0.25_before_0.25": "0_25_before_0_25",
    "0.50_before_0.25": "0_5_before_0_25",
    "0.50_before_0.50": "0_5_before_0_5",
    "1.00_before_0.50": "1_0_before_0_5",
}


# ------------------------------------------------------------------- helpers

def _pctl(s: pl.Series, q: float) -> float:
    return float(s.quantile(q)) if s.len() else float("nan")


def _safe_mean(s: pl.Series) -> float:
    return float(s.mean()) if s.len() and s.drop_nulls().len() else float("nan")


def _safe_median(s: pl.Series) -> float:
    return float(s.median()) if s.len() and s.drop_nulls().len() else float("nan")


def _group_col(pop_def: str) -> str:
    return "group_transition" if pop_def == "TRANSITION" else "group_stable"


def load_panel() -> pl.DataFrame:
    return pl.read_parquet(PANEL_PATH)


def build_joined(panel: pl.DataFrame, confirmation_state: pl.DataFrame) -> pl.DataFrame:
    """Panel rows joined to the Phase 1 freeze, carrying both group
    definitions. `population_definition` is NOT baked in here -- callers
    select `group_transition` or `group_stable` per SPEC section 4 Phase 0."""
    return panel.join(
        confirmation_state.select(
            "regime_id", "group_transition", "group_stable",
            "walk_a_mfe_to_confirm_atr",
        ),
        on="regime_id", how="inner",
    )


def _pop_groups(joined: pl.DataFrame, pop_def: str) -> pl.DataFrame:
    col = _group_col(pop_def)
    return joined.filter(pl.col(col).is_not_null()).with_columns(
        group=pl.col(col)
    )


DENOMINATORS = {
    ("TRANSITION", "WITH_5M"): 629, ("TRANSITION", "AGAINST_5M"): 4027,
    ("STABLE_STATE", "WITH_5M"): 623, ("STABLE_STATE", "AGAINST_5M"): 4018,
}


# --------------------------------------------------------------- Phase 2 ---

def phase2_landmark_attrition(joined: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for pop_def in POP_DEFS:
        pg = _pop_groups(joined, pop_def)
        for g in GROUPS:
            n_denom = DENOMINATORS[(pop_def, g)]
            gsub = pg.filter(pl.col("group") == g)
            for offset in LANDMARKS:
                osub = gsub.filter(pl.col("offset_s") == offset)
                n_alive = osub.height
                n_alive_stop_live = int(osub["alive_stop_live"].sum())
                rows.append({
                    "population_definition": pop_def, "group": g, "offset_s": offset,
                    "n_denominator": n_denom, "n_alive_unconstrained": n_alive,
                    "n_terminal": n_denom - n_alive,
                    "attrition_pct": (n_denom - n_alive) / n_denom if n_denom else float("nan"),
                    "n_alive_stop_live": n_alive_stop_live,
                })
    return pl.DataFrame(rows)


# --------------------------------------------------------------- Phase 3 ---

def phase3_mark_to_market(joined: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for pop_def in POP_DEFS:
        pg = _pop_groups(joined, pop_def)
        for g in GROUPS:
            gsub = pg.filter(pl.col("group") == g)
            for offset in LANDMARKS:
                osub = gsub.filter(pl.col("offset_s") == offset)
                ret = osub["return_from_entry_atr"]
                dret = osub["return_since_confirm_atr"]
                rows.append({
                    "population_definition": pop_def, "group": g, "offset_s": offset,
                    "n_obs": osub.height, "n_unique_trades": osub["regime_id"].n_unique(),
                    "return_from_entry_mean": _safe_mean(ret), "return_from_entry_median": _safe_median(ret),
                    "return_from_entry_p25": _pctl(ret, 0.25), "return_from_entry_p75": _pctl(ret, 0.75),
                    "return_since_confirm_mean": _safe_mean(dret), "return_since_confirm_median": _safe_median(dret),
                    "return_since_confirm_p25": _pctl(dret, 0.25), "return_since_confirm_p75": _pctl(dret, 0.75),
                })
    return pl.DataFrame(rows)


# --------------------------------------------------------------- Phase 4 ---

def phase4_incremental_mfe(joined: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for pop_def in POP_DEFS:
        pg = _pop_groups(joined, pop_def)
        for g in GROUPS:
            gsub = pg.filter(pl.col("group") == g)
            for offset in LANDMARKS:
                osub = gsub.filter(pl.col("offset_s") == offset)
                incr = osub["running_mfe_since_confirm_atr"]
                n = osub.height
                rows.append({
                    "population_definition": pop_def, "group": g, "offset_s": offset,
                    "n_obs": n, "n_unique_trades": osub["regime_id"].n_unique(),
                    "incr_mfe_mean": _safe_mean(incr), "incr_mfe_median": _safe_median(incr),
                    "incr_mfe_p75": _pctl(incr, 0.75), "incr_mfe_p90": _pctl(incr, 0.90),
                    "p_incr_ge_025": (float((incr >= 0.25).mean()) if n else float("nan")),
                    "p_incr_ge_050": (float((incr >= 0.50).mean()) if n else float("nan")),
                    "p_incr_ge_100": (float((incr >= 1.00).mean()) if n else float("nan")),
                    "p_incr_ge_200": (float((incr >= 2.00).mean()) if n else float("nan")),
                })
    return pl.DataFrame(rows)


# --------------------------------------------------------------- Phase 5 ---

def phase5_remaining_mfe(joined: pl.DataFrame) -> pl.DataFrame:
    j = joined.with_columns(
        remaining_mfe=(pl.col("eventual_max_mfe_atr") - pl.col("running_mfe_from_entry_atr"))
    )
    rows = []
    for pop_def in POP_DEFS:
        pg = _pop_groups(j, pop_def)
        for g in GROUPS:
            gsub = pg.filter(pl.col("group") == g)
            for offset in LANDMARKS:
                osub = gsub.filter(pl.col("offset_s") == offset)
                rem = osub["remaining_mfe"]
                n = osub.height
                rows.append({
                    "population_definition": pop_def, "group": g, "offset_s": offset,
                    "n_obs": n, "n_unique_trades": osub["regime_id"].n_unique(),
                    "remaining_mfe_mean": _safe_mean(rem), "remaining_mfe_median": _safe_median(rem),
                    "remaining_mfe_p75": _pctl(rem, 0.75), "remaining_mfe_p90": _pctl(rem, 0.90),
                    "p_remaining_ge_025": (float((rem >= 0.25).mean()) if n else float("nan")),
                    "p_remaining_ge_050": (float((rem >= 0.50).mean()) if n else float("nan")),
                    "p_remaining_ge_100": (float((rem >= 1.00).mean()) if n else float("nan")),
                    "p_remaining_ge_200": (float((rem >= 2.00).mean()) if n else float("nan")),
                })
    return pl.DataFrame(rows)


# --------------------------------------------------------------- Phase 6 ---

def time_to_threshold_single_trade(offsets: np.ndarray, fractions: np.ndarray,
                                   thresholds: tuple[float, ...]) -> dict[float, float | None]:
    """First offset (from a SINGLE trade's sorted-by-offset sequence) at
    which `fractions` crosses each threshold (inclusive, `>=`); None if
    never reached. Pure function, unit-tested against toy trades."""
    out: dict[float, float | None] = {}
    if offsets.size == 0:
        return {t: None for t in thresholds}
    order = np.argsort(offsets)
    offsets, fractions = offsets[order], fractions[order]
    for t in thresholds:
        hits = np.flatnonzero(fractions >= t)
        out[t] = float(offsets[hits[0]]) if hits.size else None
    return out


def phase6_capture_curve(joined: pl.DataFrame, confirmation_state: pl.DataFrame
                         ) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Reconciliation gate V-RECONCILE (SPEC section 4 Phase 6): running MFE
    at the first offset must never be below MFE-at-confirm (monotonicity)."""
    first = (joined.sort("offset_s").group_by("regime_id").first()
             .select("regime_id", "offset_s", "running_mfe_from_entry_atr"))
    check = first.join(
        confirmation_state.select("regime_id", "walk_a_mfe_to_confirm_atr"),
        on="regime_id",
    )
    violations = check.filter(
        pl.col("running_mfe_from_entry_atr") < pl.col("walk_a_mfe_to_confirm_atr") - 1e-9
    )
    if violations.height:
        raise RuntimeError(
            f"SPEC section 8 ABORT -- gate V-RECONCILE: {violations.height} trades have "
            f"running_mfe_from_entry_atr at first offset < walk_a_mfe_to_confirm_atr")

    j = joined.join(
        confirmation_state.select("regime_id", "walk_a_mfe_to_confirm_atr"),
        on="regime_id", how="inner", suffix="_conf",
    ).with_columns(
        post_confirm_total_mfe=(pl.col("eventual_max_mfe_atr") - pl.col("walk_a_mfe_to_confirm_atr"))
    )
    unmeasurable_denom = pl.col("post_confirm_total_mfe") < 0.05
    j = j.with_columns(
        fraction_realized=pl.when(unmeasurable_denom).then(None)
        .otherwise(pl.col("running_mfe_since_confirm_atr") / pl.col("post_confirm_total_mfe"))
    )

    curve_rows = []
    for pop_def in POP_DEFS:
        pg = _pop_groups(j, pop_def)
        for g in GROUPS:
            gsub = pg.filter(pl.col("group") == g)
            n_group_trades = gsub["regime_id"].n_unique()
            n_unmeasurable = gsub.filter(unmeasurable_denom)["regime_id"].n_unique()
            for offset in LANDMARKS:
                osub = gsub.filter(pl.col("offset_s") == offset)
                frac = osub["fraction_realized"].drop_nulls()
                curve_rows.append({
                    "population_definition": pop_def, "group": g, "offset_s": offset,
                    "n_obs": osub.height, "median_fraction_realized": _safe_median(frac),
                    "pct_unmeasurable_denominator": (n_unmeasurable / n_group_trades
                                                     if n_group_trades else float("nan")),
                })
    curve = pl.DataFrame(curve_rows)

    threshold_rows = []
    for pop_def in POP_DEFS:
        pg = _pop_groups(j, pop_def)
        for g in GROUPS:
            gsub = pg.filter(pl.col("group") == g)
            n_group_trades = gsub["regime_id"].n_unique()
            per_trade: dict[float, list[float]] = {t: [] for t in CAPTURE_THRESHOLDS}
            n_unreached: dict[float, int] = {t: 0 for t in CAPTURE_THRESHOLDS}
            for tid, tdf in gsub.group_by("regime_id"):
                offs = tdf["offset_s"].to_numpy().astype(float)
                fracs = tdf["fraction_realized"].fill_null(np.nan).to_numpy()
                valid = ~np.isnan(fracs)
                result = time_to_threshold_single_trade(offs[valid], fracs[valid], CAPTURE_THRESHOLDS)
                for t, v in result.items():
                    if v is None:
                        n_unreached[t] += 1
                    else:
                        per_trade[t].append(v)
            for t in CAPTURE_THRESHOLDS:
                n_reached = len(per_trade[t])
                threshold_rows.append({
                    "population_definition": pop_def, "group": g,
                    "threshold_pct": t, "n_reached": n_reached,
                    "n_unreached_unmeasurable": n_unreached[t],
                    "coverage_pct": (n_reached / n_group_trades) if n_group_trades else float("nan"),
                    "median_time_to_threshold_s": (float(np.median(per_trade[t])) if n_reached else float("nan")),
                })
    threshold_tbl = pl.DataFrame(threshold_rows)
    return curve, threshold_tbl


# --------------------------------------------------------------- Phase 7 ---

def phase7_new_extreme_probability(joined: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for pop_def in POP_DEFS:
        pg = _pop_groups(joined, pop_def)
        for g in GROUPS:
            gsub = pg.filter(pl.col("group") == g)
            for offset in LANDMARKS:
                osub = gsub.filter(pl.col("offset_s") == offset)
                n = osub.height
                p_since = (float((osub["n_new_favorable_extremes_since_confirm"] > 0).mean())
                          if n else float("nan"))
                row = {
                    "population_definition": pop_def, "group": g, "offset_s": offset,
                    "p_new_extreme_since_confirm": p_since,
                }
                for w in (30, 60, 120, 300):
                    future_offset = offset + w
                    fsub = gsub.filter(
                        (pl.col("offset_s") > offset) & (pl.col("offset_s") <= future_offset)
                    )
                    trades_with_new_extreme = (
                        fsub.filter(pl.col("another_favorable_extreme"))["regime_id"].n_unique()
                    )
                    trades_alive = osub["regime_id"].n_unique()
                    row[f"p_new_extreme_next_{w}s"] = (
                        trades_with_new_extreme / trades_alive if trades_alive else float("nan"))
                rows.append(row)
    return pl.DataFrame(rows)


# --------------------------------------------------------------- Phase 8 ---

def phase8_adverse_path(joined: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for pop_def in POP_DEFS:
        pg = _pop_groups(joined, pop_def)
        for g in GROUPS:
            gsub = pg.filter(pl.col("group") == g)
            for offset in LANDMARKS:
                osub = gsub.filter(pl.col("offset_s") == offset)
                mae = osub["running_mae_from_entry_atr"]
                dd = osub["drawdown_from_running_max_atr"]
                n = osub.height
                row = {
                    "population_definition": pop_def, "group": g, "offset_s": offset,
                    "incr_mae_mean": _safe_mean(mae), "incr_mae_median": _safe_median(mae),
                    "drawdown_mean": _safe_mean(dd), "drawdown_median": _safe_median(dd),
                    "drawdown_p25": _pctl(dd, 0.25), "drawdown_p75": _pctl(dd, 0.75),
                }
                for pair_label, col_suffix in RACE_PAIRS.items():
                    col = f"race_{col_suffix}"
                    amb_col = f"{col}_ambiguous"
                    if n:
                        vals = osub[col]
                        row[f"p_adverse_before_favorable_{pair_label}"] = float((vals == "ADVERSE").mean())
                        row[f"p_favorable_before_adverse_{pair_label}"] = float((vals == "FAVORABLE").mean())
                        row[f"p_unresolved_{pair_label}"] = float((vals == "UNRESOLVED").mean())
                        row[f"p_ambiguous_{pair_label}"] = float(osub[amb_col].mean())
                    else:
                        for k in ("p_adverse_before_favorable", "p_favorable_before_adverse",
                                 "p_unresolved", "p_ambiguous"):
                            row[f"{k}_{pair_label}"] = float("nan")
                rows.append(row)
    return pl.DataFrame(rows)


# --------------------------------------------------------------- Phase 9 ---

def phase9_giveback_timing(joined: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for pop_def in POP_DEFS:
        pg = _pop_groups(joined, pop_def)
        for g in GROUPS:
            gsub = pg.filter(pl.col("group") == g)
            for offset in LANDMARKS:
                osub = gsub.filter(pl.col("offset_s") == offset)
                gb = osub["drawdown_from_running_max_atr"]
                term = gsub.unique(subset=["regime_id"])["trade_nat_giveback_atr"]
                rows.append({
                    "population_definition": pop_def, "group": g, "offset_s": offset,
                    "giveback_mean": _safe_mean(gb), "giveback_median": _safe_median(gb),
                    "giveback_p75": _pctl(gb, 0.75), "giveback_p90": _pctl(gb, 0.90),
                    "terminal_giveback_mean": _safe_mean(term), "terminal_giveback_median": _safe_median(term),
                })
    return pl.DataFrame(rows)


# -------------------------------------------------------------- Phase 10 ---

def phase10_continuation_value(joined: pl.DataFrame, rng: np.random.Generator) -> pl.DataFrame:
    rows = []
    for pop_def in POP_DEFS:
        pg = _pop_groups(joined, pop_def)
        for g in GROUPS:
            gsub = pg.filter(pl.col("group") == g)
            for offset in LANDMARKS:
                osub = gsub.filter(pl.col("offset_s") == offset)
                for basis, col in (("stop_live", "cv_stop_live_atr"),
                                   ("unconstrained", "cv_unconstrained_atr")):
                    cv = osub[col].drop_nulls()
                    n = cv.len()
                    if n:
                        arr = cv.to_numpy()
                        idx = rng.integers(0, n, size=(1000, n))
                        boots = arr[idx].mean(axis=1)
                        ci_lo, ci_hi = np.percentile(boots, [2.5, 97.5])
                    else:
                        ci_lo = ci_hi = float("nan")
                    rows.append({
                        "population_definition": pop_def, "group": g, "offset_s": offset,
                        "basis": basis, "cv_mean": _safe_mean(cv), "cv_median": _safe_median(cv),
                        "ci_low": float(ci_lo), "ci_high": float(ci_hi),
                        "p_positive": (float((cv > 0).mean()) if n else float("nan")),
                        "p_negative": (float((cv < 0).mean()) if n else float("nan")),
                    })
    return pl.DataFrame(rows)


# -------------------------------------------------------------- Phase 11 ---

def phase11_mfe_quality_buckets(sub_tables: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Long-format re-aggregation of Phases 3/4/5/9/10 crossed with the
    retrospective, trade-level `runner_bucket` (LABEL_ONLY descriptive
    crosstab -- SPEC section 3.1 item 4's permitted carve-out, never fed
    back into the WITH/AGAINST group definition).

    **Not** the panel's `mfe_bucket` column -- verified directly against the
    real data during the completion audit that `mfe_bucket` is bucketized
    from `running_mfe_from_entry_atr`, a CONTEMPORANEOUS per-offset value
    (60.6% of trades, 2,823/4,656, occupy more than one distinct `mfe_bucket`
    across their own offset rows), not the retrospective eventual-outcome
    tier Phase 11 needs. `runner_bucket` is confirmed constant per trade
    (0/4,656 trades have more than one distinct value) and derived from
    `eventual_max_mfe_atr` (R0<1, R1 1-2, R2 2-3, R3>=3) -- the correct
    source for "does WITH/AGAINST behave differently WITHIN a fixed eventual
    opportunity class."
    """
    joined = sub_tables["joined"]
    rows = []
    for pop_def in POP_DEFS:
        pg = _pop_groups(joined, pop_def)
        for g in GROUPS:
            for bucket in ("R0", "R1", "R2", "R3"):
                bsub = pg.filter((pl.col("group") == g) & (pl.col("runner_bucket") == bucket))
                for offset in LANDMARKS:
                    osub = bsub.filter(pl.col("offset_s") == offset)
                    if osub.height == 0:
                        continue
                    rows.append({
                        "population_definition": pop_def, "group": g, "runner_bucket": bucket,
                        "offset_s": offset, "metric": "incr_mfe_median",
                        "value": _safe_median(osub["running_mfe_since_confirm_atr"]),
                    })
                    rows.append({
                        "population_definition": pop_def, "group": g, "runner_bucket": bucket,
                        "offset_s": offset, "metric": "giveback_median",
                        "value": _safe_median(osub["drawdown_from_running_max_atr"]),
                    })
                    rows.append({
                        "population_definition": pop_def, "group": g, "runner_bucket": bucket,
                        "offset_s": offset, "metric": "cv_stop_live_median",
                        "value": _safe_median(osub["cv_stop_live_atr"].drop_nulls()),
                    })
    return pl.DataFrame(rows)


# -------------------------------------------------------------- Phase 13 ---
# Each fixed offset contributes at most one row per trade (offset_s is a
# grid point, not a bucket a trade can enter/re-enter), so no D8-style
# first-observation-per-bucket dedup is needed here -- filtering to one
# offset already yields one row per trade.

def phase13_year_side_stability(joined: pl.DataFrame) -> pl.DataFrame:
    j = joined.with_columns(
        remaining_mfe=(pl.col("eventual_max_mfe_atr") - pl.col("running_mfe_from_entry_atr"))
    )
    rows = []
    for pop_def in POP_DEFS:
        pg = _pop_groups(j, pop_def)
        for slice_kind, col, values in (
            ("year", "entry_year", sorted(j["entry_year"].unique().to_list())),
            ("side", "side", ["LONG", "SHORT"]),
        ):
            for slice_val in values:
                ssub = pg.filter(pl.col(col) == slice_val)
                for g in GROUPS:
                    gsub = ssub.filter(pl.col("group") == g)
                    for offset in (120, 300, 600):
                        osub = gsub.filter(pl.col("offset_s") == offset)
                        for metric_name, metric_col in (("incr_mfe", "running_mfe_since_confirm_atr"),
                                                        ("remaining_mfe", "remaining_mfe"),
                                                        ("cv_stop_live", "cv_stop_live_atr")):
                            vals = osub[metric_col].drop_nulls()
                            rows.append({
                                "population_definition": pop_def, "slice_kind": slice_kind,
                                "slice": str(slice_val), "group": g, "metric": metric_name,
                                "offset_s": offset, "n_obs": osub.height,
                                "n_unique_trades": osub["regime_id"].n_unique(),
                                "value": _safe_median(vals),
                            })
    return pl.DataFrame(rows)


# ------------------------------------------------------------- primary -----

def primary_table(joined: pl.DataFrame, confirmation_state: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for pop_def in POP_DEFS:
        col = _group_col(pop_def)
        cs = confirmation_state.filter(pl.col(col).is_not_null())
        for g in GROUPS:
            csub = cs.filter(pl.col(col) == g)
            rows.append({"population_definition": pop_def, "group": g, "metric": "n_confirmed",
                        "value": float(csub.height)})
            rows.append({"population_definition": pop_def, "group": g, "metric": "confirm_return_median",
                        "value": _safe_median(csub["walk_a_return_at_confirm_atr"])})
            rows.append({"population_definition": pop_def, "group": g, "metric": "confirm_mfe_median",
                        "value": _safe_median(csub["walk_a_mfe_to_confirm_atr"])})
            rows.append({"population_definition": pop_def, "group": g, "metric": "confirm_mae_median",
                        "value": _safe_median(csub["walk_a_mae_to_confirm_atr"])})

            pg = _pop_groups(joined, pop_def).filter(pl.col("group") == g)
            trade_terms = pg.unique(subset=["regime_id"])
            rows.append({"population_definition": pop_def, "group": g, "metric": "terminal_return",
                        "value": _safe_median(trade_terms["trade_nat_net_atr"])})
            rows.append({"population_definition": pop_def, "group": g, "metric": "terminal_giveback",
                        "value": _safe_median(trade_terms["trade_nat_giveback_atr"])})

            for offset in (60, 120, 180, 300, 600):
                osub = pg.filter(pl.col("offset_s") == offset)
                n_alive = osub["regime_id"].n_unique()
                rows.append({"population_definition": pop_def, "group": g,
                            "metric": f"delta_mark_median_{offset}s",
                            "value": _safe_median(osub["return_since_confirm_atr"])})
                rows.append({"population_definition": pop_def, "group": g,
                            "metric": f"incr_mfe_median_{offset}s",
                            "value": _safe_median(osub["running_mfe_since_confirm_atr"])})
                remaining = osub["eventual_max_mfe_atr"] - osub["running_mfe_from_entry_atr"]
                rows.append({"population_definition": pop_def, "group": g,
                            "metric": f"remaining_mfe_median_{offset}s", "value": _safe_median(remaining)})
                if offset == 60:
                    fut = pg.filter((pl.col("offset_s") > 60) & (pl.col("offset_s") <= 120)
                                    & pl.col("another_favorable_extreme"))["regime_id"].n_unique()
                    rows.append({"population_definition": pop_def, "group": g,
                                "metric": "p_new_extreme_next_60s",
                                "value": (fut / n_alive) if n_alive else float("nan")})
                rows.append({"population_definition": pop_def, "group": g,
                            "metric": f"continuation_value_median_{offset}s",
                            "value": _safe_median(osub["cv_stop_live_atr"].drop_nulls())})
    return pl.DataFrame(rows)


def opportunity_capture_summary(threshold_tbl: pl.DataFrame, joined: pl.DataFrame) -> pl.DataFrame:
    j = joined.with_columns(
        remaining_mfe=(pl.col("eventual_max_mfe_atr") - pl.col("running_mfe_from_entry_atr"))
    )
    rows = []
    for pop_def in POP_DEFS:
        for g in GROUPS:
            tsub = threshold_tbl.filter((pl.col("population_definition") == pop_def)
                                        & (pl.col("group") == g))
            for t in CAPTURE_THRESHOLDS:
                r = tsub.filter(pl.col("threshold_pct") == t)
                rows.append({"population_definition": pop_def, "group": g,
                            "metric": f"time_to_{int(t*100)}pct_s",
                            "value": (float(r["median_time_to_threshold_s"][0]) if r.height else float("nan"))})
                rows.append({"population_definition": pop_def, "group": g,
                            "metric": f"time_to_{int(t*100)}pct_coverage_pct",
                            "value": (float(r["coverage_pct"][0]) if r.height else float("nan"))})
            pg = _pop_groups(j, pop_def).filter(pl.col("group") == g)
            for offset in LANDMARKS:
                osub = pg.filter(pl.col("offset_s") == offset)
                rows.append({"population_definition": pop_def, "group": g,
                            "metric": f"remaining_mfe_median_{offset}s",
                            "value": _safe_median(osub["remaining_mfe"])})
    return pl.DataFrame(rows)


# -------------------------------------------------------------- Phase 12 ---
# Confirmation-quality control (MANDATORY, SPEC section 4 Phase 12). Direct
# structural reuse of
# p90_5m_regime_context/implementation/analysis.py::phase11_matched_control's
# exposure-weighted-stratified-delta + trade-clustered-bootstrap-CI method,
# adapted to this study's five outcome metrics. Strata are ALL
# confirmation-time-only (gate V-MATCH) -- side, entry_year, three
# confirm-time buckets, `confirm_mfe_bucket` is a DISTINCT name from Phase
# 11's retrospective `mfe_bucket` (SPEC section 4 Phase 11/12 disambiguation).

#: Frozen edges, not tuned to outcome. MFE reuses the panel's own <1/1-2/2-3/>=3
#: scheme (SPEC's explicit instruction); MAE/return edges approximate this
#: population's own p50/p90-ish quantiles from the M2 study's MAE references,
#: frozen once, never re-derived per run.
CONFIRM_MFE_EDGES = (1.0, 2.0, 3.0)
CONFIRM_MFE_LABELS = ("<1", "1-2", "2-3", ">=3")
CONFIRM_MAE_EDGES = (0.33, 0.60, 0.90)
CONFIRM_MAE_LABELS = ("Q1", "Q2", "Q3", "Q4")
CONFIRM_RETURN_EDGES = (0.5, 1.0, 1.5)
CONFIRM_RETURN_LABELS = ("<0.5", "0.5-1.0", "1.0-1.5", ">=1.5")
CONFIRM_SPEED_EDGES = (60, 120, 300)
CONFIRM_SPEED_LABELS = ("<=60s", "61-120s", "121-300s", ">300s")


def phase12_strata(confirmation_state: pl.DataFrame) -> pl.DataFrame:
    """Stratification keys only -- no outcome field. All confirmation-time
    variables (gate V-MATCH, stop condition 5)."""
    edges = [float(confirmation_state["arm_score"].quantile(q)) for q in (0.25, 0.50, 0.75)]
    tod = time_of_day_bucket(confirmation_state["walk_a_confirm_ns"].to_numpy())
    return confirmation_state.select("regime_id", "side", "entry_year").with_columns(
        confirm_mfe_bucket=pl.Series(_bucket(
            confirmation_state["walk_a_mfe_to_confirm_atr"].to_numpy(),
            CONFIRM_MFE_EDGES, CONFIRM_MFE_LABELS)),
        confirm_mae_bucket=pl.Series(_bucket(
            confirmation_state["walk_a_mae_to_confirm_atr"].to_numpy(),
            CONFIRM_MAE_EDGES, CONFIRM_MAE_LABELS)),
        confirm_return_bucket=pl.Series(_bucket(
            confirmation_state["walk_a_return_at_confirm_atr"].to_numpy(),
            CONFIRM_RETURN_EDGES, CONFIRM_RETURN_LABELS)),
        confirm_seconds_bucket=pl.Series(_bucket(
            confirmation_state["walk_a_seconds_to_confirm"].to_numpy(),
            CONFIRM_SPEED_EDGES, CONFIRM_SPEED_LABELS)),
        arm_score_quartile=pl.Series(_bucket(
            confirmation_state["arm_score"].to_numpy(), tuple(edges), ("Q1", "Q2", "Q3", "Q4"))),
        time_of_day=pl.Series(tod),
    )


STRATA_COLS = ("side", "entry_year", "confirm_mfe_bucket", "confirm_mae_bucket",
              "confirm_return_bucket", "confirm_seconds_bucket", "arm_score_quartile",
              "time_of_day")


def _weighted_delta(valid: pl.DataFrame, a_col: str, b_col: str) -> tuple[float, float]:
    """Exposure-weighted delta of two group columns across strata cells,
    dropping cells where either side is null/NaN for THIS metric (mirrors
    p90_5m_regime_context's fix for confirm-conditioned metrics with
    zero-observation cells on one side)."""
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


def _matched_control_one_metric(frame: pl.DataFrame, outcome_col: str,
                                metric_name: str, rng: np.random.Generator) -> dict:
    cells = frame.group_by(*STRATA_COLS, "group").agg(
        n=pl.len(), value=pl.col(outcome_col).mean(),
    )
    wide = cells.pivot(on="group", index=list(STRATA_COLS), values=["n", "value"])
    n_cells = wide.height
    with_n = pl.col("n_WITH_5M").fill_null(0)
    against_n = pl.col("n_AGAINST_5M").fill_null(0)
    valid = wide.filter((with_n > 0) & (against_n > 0))

    raw_delta, strat_delta = _weighted_delta(valid, "value_WITH_5M", "value_AGAINST_5M")

    a_vals = valid["value_WITH_5M"].to_numpy().astype(float)
    b_vals = valid["value_AGAINST_5M"].to_numpy().astype(float)
    n_a = valid["n_WITH_5M"].to_numpy().astype(float)
    n_b = valid["n_AGAINST_5M"].to_numpy().astype(float)
    finite = np.isfinite(a_vals) & np.isfinite(b_vals)
    if finite.sum():
        a_vals, b_vals, n_a, n_b = a_vals[finite], b_vals[finite], n_a[finite], n_b[finite]
        weight = n_a + n_b
        delta = a_vals - b_vals
        idx = rng.integers(0, delta.size, size=(2000, delta.size))
        boots = np.array([np.average(delta[i], weights=weight[i]) if weight[i].sum() else np.nan
                          for i in idx])
        ci_low, ci_high = np.nanpercentile(boots, [2.5, 97.5])
    else:
        ci_low, ci_high = float("nan"), float("nan")

    return {
        "outcome_metric": metric_name, "n_cells": n_cells,
        "n_cells_both_present": valid.height,
        "raw_delta": raw_delta, "stratified_delta": strat_delta,
        "delta_ci_low": float(ci_low), "delta_ci_high": float(ci_high),
        "ci_excludes_zero": bool(ci_low > 0 or ci_high < 0) if np.isfinite(ci_low) else False,
    }


def phase12_matched_confirmation_control(joined: pl.DataFrame, confirmation_state: pl.DataFrame,
                                         strata: pl.DataFrame, rng: np.random.Generator
                                         ) -> pl.DataFrame:
    base = joined.with_columns(
        remaining_mfe=(pl.col("eventual_max_mfe_atr") - pl.col("running_mfe_from_entry_atr")),
        new_extreme_since=(pl.col("n_new_favorable_extremes_since_confirm") > 0),
    ).join(strata, on="regime_id", how="inner")

    all_rows = []
    for pop_def in POP_DEFS:
        j = _pop_groups(base, pop_def)
        term = j.unique(subset=["regime_id"]).select(*STRATA_COLS, "group", "trade_nat_net_atr")

        rows = []
        for offset in (300, 600):
            osub = j.filter(pl.col("offset_s") == offset)
            rows.append(_matched_control_one_metric(
                osub, "running_mfe_since_confirm_atr", f"incremental_mfe_{offset}s", rng))
            rows.append(_matched_control_one_metric(
                osub, "remaining_mfe", f"remaining_mfe_{offset}s", rng))
            rows.append(_matched_control_one_metric(
                osub, "cv_stop_live_atr", f"continuation_value_{offset}s", rng))
        osub300 = j.filter(pl.col("offset_s") == 300)
        rows.append(_matched_control_one_metric(
            osub300, "new_extreme_since", "new_extreme_probability_300s", rng))
        rows.append(_matched_control_one_metric(
            term, "trade_nat_net_atr", "terminal_return", rng))

        all_rows.extend({"population_definition": pop_def, **r} for r in rows)

    return pl.DataFrame(all_rows)
