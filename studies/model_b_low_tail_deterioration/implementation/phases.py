"""Phases 1-6 and 8-10. Frozen artifacts only; no estimator is ever constructed."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import (ADVERSE_LEVELS, DISJOINT_BANDS, HORIZONS_S, NESTED_CUTS,
                     PRIMARY_TARGET, SEED, UNDERPOWERED_TRADES, auc, band_mask,
                     cut_name, curve, low_rank, metrics, nested_mask, spearman,
                     trade_clustered_ci)

CONTROL_CUTS: tuple[float, ...] = (0.25, 0.20, 0.10, 0.05)
FOLD_CUTS: tuple[float, ...] = (1.00, 0.25, 0.20, 0.10, 0.05)


# --- Phase 1 -----------------------------------------------------------------------

def phase1_curve(d: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Pooled low-tail curve: 11 nested cuts + 10 disjoint bands."""
    rows = curve(d, scope="POOLED")
    t = pd.DataFrame(rows)

    band = t[t["cut_basis"] == "DISJOINT_BAND"].reset_index(drop=True)
    nest = t[(t["cut_basis"] == "WITHIN_SCOPE") & (t["cut"] != "ALL")].reset_index(drop=True)

    mono = {}
    for basis, frame, key in (("DISJOINT_BAND", band, "gate"),
                              ("NESTED_CONSTRUCTION_CORRELATED", nest, "diagnostic")):
        for econ in ("mark", "hwm"):
            rho, inv = spearman(frame[f"continue_minus_exit_{econ}_atr"].to_numpy())
            mono[f"{basis}__cme_{econ}"] = {
                "spearman": rho, "inversions": inv, "role": key,
                # Index 0 is the most severe band, so a DETERIORATION curve rises
                # with index. Positive rho == deterioration.
                "direction": ("DETERIORATION" if rho is not None and rho > 0
                              else "IMPROVEMENT" if rho is not None and rho < 0
                              else "FLAT")}
    return t, mono


# --- Phase 2 -----------------------------------------------------------------------

def phase2_folds(d: pd.DataFrame) -> pd.DataFrame:
    """Fold stability. WITHIN_FOLD re-ranking is primary (it is how the predecessor
    built `fold_sep`); the pooled-threshold variant is emitted as a diagnostic because
    the two folds are separate fits with separate calibrations."""
    rows = []
    pooled_p = d["oos_prob"].to_numpy()
    for fold in ("FOLD_1", "FOLD_2"):
        m = (d["oos_fold"] == fold).to_numpy()
        s = d[m].reset_index(drop=True)
        for f in FOLD_CUTS:
            rows.append(metrics(s, nested_mask(s["oos_prob"].to_numpy(), f),
                                cut=cut_name(f), scope=fold, cut_basis="WITHIN_FOLD"))
            # Same percentile taken on the POOLED score distribution, then intersected
            # with the fold -- so cell sizes differ from the within-fold cut by design.
            pm = nested_mask(pooled_p, f) & m
            rows.append(metrics(d, pm, cut=cut_name(f), scope=fold,
                                cut_basis="POOLED_THRESHOLD",
                                pop_obs=int(m.sum()),
                                pop_trades=int(d[m]["regime_id"].nunique())))
    return pd.DataFrame(rows)


# --- Phase 3 -----------------------------------------------------------------------

def phase3_sides(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for side in ("LONG", "SHORT"):
        s = d[d["side"] == side].reset_index(drop=True)
        p = s["oos_prob"].to_numpy()
        for f in (1.00, *CONTROL_CUTS):
            rows.append(metrics(s, nested_mask(p, f), cut=cut_name(f), scope=side,
                                cut_basis="WITHIN_SIDE"))
    return pd.DataFrame(rows)


# --- Phase 4 -----------------------------------------------------------------------

def phase4_rungs(d: pd.DataFrame) -> pd.DataFrame:
    """Is deterioration present WITHIN rung, or is the model just reading the rung?"""
    rows = []
    for rung in sorted(d["rung_atr"].unique()):
        s = d[d["rung_atr"] == rung].reset_index(drop=True)
        p = s["oos_prob"].to_numpy()
        for f in (1.00, 0.20, 0.10):
            rows.append(metrics(s, nested_mask(p, f), cut=cut_name(f),
                                scope=f"RUNG_{rung}", cut_basis="WITHIN_RUNG"))
    return pd.DataFrame(rows)


# --- Phase 5 -----------------------------------------------------------------------

def phase5_time(d: pd.DataFrame) -> pd.DataFrame:
    """Frozen SINCECONF terciles, inherited from the predecessor and never re-derived."""
    rows = []
    for stratum in ("SINCECONF_T1", "SINCECONF_T2", "SINCECONF_T3"):
        s = d[d["sinceconf_stratum"] == stratum].reset_index(drop=True)
        p = s["oos_prob"].to_numpy()
        for f in (1.00, *CONTROL_CUTS):
            rows.append(metrics(s, nested_mask(p, f), cut=cut_name(f), scope=stratum,
                                cut_basis="WITHIN_STRATUM"))
    return pd.DataFrame(rows)


# --- Phase 6 -----------------------------------------------------------------------

def phase6_barriers(d: pd.DataFrame, full: pd.DataFrame) -> pd.DataFrame:
    """The 12 frozen label families, scored with the FROZEN predictions.

    The AUC here is not "what a model trained on this target could do" -- retraining
    is forbidden. It measures whether the existing ranking happens to order a
    different question better than the one it was fit on.
    """
    rows = []
    p = d["oos_prob"].to_numpy()
    for a in ADVERSE_LEVELS:
        for H in HORIZONS_S:
            tgt = f"lab_f050_a{a:.2f}_{H}".replace(".", "")
            lab = d[tgt].to_numpy()
            resolved = lab != "TIMEOUT"
            y = (lab == "FAVOURABLE").astype(int)
            base = {
                "adverse_atr": a, "horizon_s": H, "target": tgt,
                "is_primary": tgt == PRIMARY_TARGET,
                "unconditional_success_pct_full_frame":
                    100.0 * float((full[tgt] == "FAVOURABLE").mean()),
                "unconditional_success_pct_oos": 100.0 * float(y.mean()),
                "timeout_pct_oos": 100.0 * float((~resolved).mean()),
                "auc_frozen_predictions": auc(p, y),
                "auc_resolved_only": auc(p[resolved], y[resolved]),
            }
            for f in (1.00, *CONTROL_CUTS):
                m = metrics(d, nested_mask(p, f), cut=cut_name(f), scope=tgt,
                            target=tgt, with_ci=True)
                rows.append({**base, **m})
    return pd.DataFrame(rows)


# --- Phase 7 aggregation (timing columns are supplied by `timing.py`) ----------------

def phase7_geometry(d: pd.DataFrame, timing: pd.DataFrame | None) -> pd.DataFrame:
    """Forward geometry of the low tail. Answers: collapse, stagnation, or noise?"""
    s_all = d if timing is None else d.merge(
        timing, on=["regime_id", "rung_ts", "rung_atr"], how="left", validate="1:1")
    rows = []
    p = s_all["oos_prob"].to_numpy()
    for f in (1.00, 0.20, 0.10, 0.05):
        m = nested_mask(p, f)
        s = s_all[m]
        r: dict = {
            "cut": cut_name(f), "n_obs": len(s),
            "n_unique_trades": int(s["regime_id"].nunique()),
            "underpowered": bool(s["regime_id"].nunique() < UNDERPOWERED_TRADES),
            "fwd_mfe_300_median": float(s["fwd_mfe_300"].median()),
            "fwd_mfe_300_mean": float(s["fwd_mfe_300"].mean()),
            "fwd_mae_300_median": float(s["fwd_mae_300"].median()),
            "fwd_mae_300_mean": float(s["fwd_mae_300"].mean()),
            "final_return_median": float(s["nat_terminal_return_atr"].median()),
            # fwd_mfe is measured FROM the HWM, so > 0 is exactly "a new extreme".
            "p_new_favourable_extreme": 100.0 * float((s["fwd_mfe_300"] > 0).mean()),
            "p_mfe_ge_0_50": 100.0 * float((s["fwd_mfe_300"] >= 0.50).mean()),
            "p_mfe_ge_1_00": 100.0 * float((s["fwd_mfe_300"] >= 1.00).mean()),
        }
        for a in ADVERSE_LEVELS:
            r[f"p_adverse_{a:.2f}".replace(".", "_")] = (
                100.0 * float((s["fwd_mae_300"] >= a).mean()))
        if timing is not None:
            r["median_secs_to_new_favourable_extreme"] = _med(s, "secs_to_new_extreme")
            r["median_secs_to_next_favourable_extreme"] = _med(s, "secs_to_fav_050")
            for a in ADVERSE_LEVELS:
                r[f"median_secs_to_adverse_{a:.2f}".replace(".", "_")] = _med(
                    s, f"secs_to_adv_{a:.2f}".replace(".", ""))
            # Censoring exposure. A median "time to X" is comparable across cuts only
            # if the windows are comparably long -- a shorter window reports a shorter
            # median by truncation alone. These columns make any imbalance visible
            # rather than leaving it assumed away.
            r["pct_window_reached_horizon"] = 100.0 * float(
                s["window_reached_horizon"].mean())
            r["window_bars_median"] = float(s["window_bars_available"].median())
            r["window_bars_mean"] = float(s["window_bars_available"].mean())
            r["pct_censored_no_new_extreme"] = 100.0 * float(
                s["secs_to_new_extreme"].isna().mean())
        else:
            r["timing_status"] = "NOT_AVAILABLE"
        rows.append(r)
    return pd.DataFrame(rows)


def _med(s: pd.DataFrame, col: str) -> float | None:
    if col not in s.columns:
        return None
    v = s[col].dropna()
    return float(v.median()) if len(v) else None


# --- Phase 8 -----------------------------------------------------------------------

def _first_trigger(d: pd.DataFrame, mask: np.ndarray) -> pd.DataFrame:
    """First CHRONOLOGICAL qualifying observation per trade.

    Ordering is on integer-nanosecond `rung_ts`, never on float seconds and never on
    rung index -- gate V6 re-asserts the minimum independently.
    """
    s = d[mask].sort_values(["regime_id", "rung_ts"], kind="stable")
    return s.groupby("regime_id", as_index=False, sort=False).head(1).reset_index(drop=True)


def expected_first_ts(d: pd.DataFrame) -> pd.DataFrame:
    """Independent recomputation of the earliest qualifying rung per (cut, trade).

    Deliberately uses `groupby(...).min()` rather than the sort-then-head path in
    `_first_trigger`, so gate V6's minimality clause is checked by different code and
    not merely by the code it is auditing.
    """
    p = d["oos_prob"].to_numpy()
    out = []
    for f in CONTROL_CUTS:
        g = (d[nested_mask(p, f)].groupby("regime_id", as_index=False)["rung_ts"]
             .min().rename(columns={"rung_ts": "rung_ts_expected"}))
        out.append(g.assign(cut=cut_name(f)))
    return pd.concat(out, ignore_index=True)[["cut", "regime_id", "rung_ts_expected"]]


def phase8_first_trigger(d: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    p = d["oos_prob"].to_numpy()
    n_trades_pop = int(d["regime_id"].nunique())
    # Eventual outcome is defined at TRADE level, so a trade is counted once however
    # many rungs it contributed.
    per_trade = d.groupby("regime_id").agg(
        eventual_max_mfe_atr=("eventual_max_mfe_atr", "max"),
        nat_terminal_return_atr=("nat_terminal_return_atr", "first"))
    n_r3 = int((per_trade["eventual_max_mfe_atr"] >= 3.0).sum())
    n_r4 = int((per_trade["eventual_max_mfe_atr"] >= 4.0).sum())
    n_win = int((per_trade["nat_terminal_return_atr"] > 0).sum())
    n_los = int((per_trade["nat_terminal_return_atr"] <= 0).sum())

    detail, econ = [], []
    for f in CONTROL_CUTS:
        t = _first_trigger(d, nested_mask(p, f))
        t = t.assign(cut=cut_name(f))
        detail.append(t[["cut", "regime_id", "side", "rung_atr", "rung_ts",
                         "seconds_since_confirm", "oos_prob", "return_from_entry_atr",
                         "current_mfe_atr", "exit_now_mark_atr", "exit_now_hwm_atr",
                         "continue_atr", "cme_mark", "cme_hwm",
                         "eventual_max_mfe_atr", "nat_terminal_return_atr"]])
        econ.append({
            "cut": cut_name(f),
            "n_triggered_trades": len(t),
            "pct_of_population_trades": 100.0 * len(t) / n_trades_pop,
            "underpowered": bool(len(t) < UNDERPOWERED_TRADES),
            "trigger_rung_mean": float(t["rung_atr"].mean()),
            "trigger_rung_median": float(t["rung_atr"].median()),
            "trigger_rung_1_0_pct": 100.0 * float((t["rung_atr"] == 1.0).mean()),
            "median_seconds_since_confirm": float(t["seconds_since_confirm"].median()),
            "return_at_trigger_mean": float(t["return_from_entry_atr"].mean()),
            "mfe_at_trigger_mean": float(t["current_mfe_atr"].mean()),
            "exit_now_mark_atr": float(t["exit_now_mark_atr"].mean()),
            "exit_now_hwm_atr": float(t["exit_now_hwm_atr"].mean()),
            "accepted_management_atr": float(t["continue_atr"].mean()),
            "difference_mark_atr": float(t["cme_mark"].mean()),
            "difference_hwm_atr": float(t["cme_hwm"].mean()),
            **_ci_pair(t),
            "pct_R3_runners_intercepted":
                100.0 * float((t["eventual_max_mfe_atr"] >= 3.0).sum()) / n_r3 if n_r3 else None,
            "pct_R4_runners_intercepted":
                100.0 * float((t["eventual_max_mfe_atr"] >= 4.0).sum()) / n_r4 if n_r4 else None,
            "pct_eventual_losers_intercepted":
                100.0 * float((t["nat_terminal_return_atr"] <= 0).sum()) / n_los if n_los else None,
            "pct_eventual_winners_intercepted":
                100.0 * float((t["nat_terminal_return_atr"] > 0).sum()) / n_win if n_win else None,
        })
    return pd.concat(detail, ignore_index=True), pd.DataFrame(econ)


def _ci_pair(t: pd.DataFrame) -> dict:
    out = {}
    for base in ("mark", "hwm"):
        lo, hi = trade_clustered_ci(t[f"cme_{base}"].to_numpy(), t["regime_id"].to_numpy())
        out[f"ci95_lo_{base}"], out[f"ci95_hi_{base}"] = lo, hi
    return out


# --- Phase 9 -----------------------------------------------------------------------

def _stratum_cells(d: pd.DataFrame) -> pd.Series:
    return d["rung_atr"].astype(str) + "|" + d["sinceconf_stratum"]


N_PLACEBO_REPS = 200


def _threshold_trigger(d: pd.DataFrame, col: str, ascending: bool,
                       n_trades: int) -> tuple[pd.DataFrame, int]:
    """A CAUSAL single-variable rule: "exit at the first bar where `col` crosses T".

    The obvious construction -- take each trade's most extreme observation on `col`
    -- is hindsight: at rung 2 nobody knows whether rung 4 will later show a deeper
    drawdown, a higher rung, or a later timestamp. Selecting on a within-trade
    extremum is the accepted `running_extremum_mechanically_contains_eventual_extremum`
    defect, and it flattered these controls badly on the first pass (C3_DESC moved
    from -1.03 to a far weaker number once corrected).

    Instead the threshold T is walked out from the extreme of the POOLED observation
    distribution until exactly `n_trades` distinct trades have at least one crossing,
    and each trade then fires at its FIRST crossing. That is the same shape of rule as
    the ML trigger -- a fixed pooled threshold, first chronological crossing per trade
    -- so the comparison is like-for-like.
    """
    v = d[col].to_numpy(dtype=float)
    order = np.argsort(v if ascending else -v, kind="stable")
    rid = d["regime_id"].to_numpy()
    seen: set = set()
    k = order.size
    for pos, i in enumerate(order):
        seen.add(rid[i])
        if len(seen) == n_trades:
            k = pos + 1
            break
    mask = np.zeros(len(d), dtype=bool)
    mask[order[:k]] = True
    return _first_trigger(d, mask), len(seen)


def _random_matched(d: pd.DataFrame, want: dict, cells: np.ndarray,
                    rng: np.random.Generator) -> tuple[np.ndarray, int]:
    """One observation per trade, count-matched cell by cell on rung x SINCECONF.

    A trade is never used twice, so the draw is comparable to the ML trigger, which
    is also one-per-trade. Cells that cannot supply their quota report a deficit
    rather than silently borrowing from a neighbouring cell.
    """
    used: set = set()
    pick: list[int] = []
    rid = d["regime_id"].to_numpy()
    for cell, k in want.items():
        idx = np.flatnonzero(cells == cell)
        rng.shuffle(idx)
        took = 0
        for i in idx:
            if rid[i] in used:
                continue
            used.add(rid[i])
            pick.append(int(i))
            took += 1
            if took == k:
                break
    return np.array(pick, dtype=int), int(sum(want.values()) - len(pick))


def phase9_placebo(d: pd.DataFrame) -> pd.DataFrame:
    """Matched controls. The ML trigger must beat these, not merely beat holding.

    C4 (drawdown-from-HWM) is the decisive control: the study's adverse barrier is
    itself HWM-anchored, so a drawdown rule is not a strawman here -- it is close to
    a restatement of the label.

    Every single-variable control is run in BOTH rank directions and the ML trigger is
    required to beat the BETTER of the two. Choosing the direction that happens to
    lose would be building a strawman, which is the failure mode this phase exists to
    prevent.
    """
    rng = np.random.default_rng(SEED)
    p = d["oos_prob"].to_numpy()
    cells = _stratum_cells(d).to_numpy()
    rid = d["regime_id"].to_numpy()
    rows = []

    for f in CONTROL_CUTS:
        ml = _first_trigger(d, nested_mask(p, f))
        n = len(ml)
        want = pd.Series(_stratum_cells(ml).to_numpy()).value_counts().to_dict()
        rows.append(_control_row(cut_name(f), "ML_LOW_SCORE", ml, n, 0, None))

        # C1 -- random, stratified so composition is matched, not merely count-matched.
        means: dict = {"mark": [], "hwm": []}
        deficit = 0
        for rep in range(N_PLACEBO_REPS):
            idx, dfc = _random_matched(d, want, cells, rng)
            if rep == 0:
                deficit = dfc
            sel = d.iloc[idx]
            for b in ("mark", "hwm"):
                means[b].append(float(sel[f"cme_{b}"].mean()) if len(sel) else np.nan)
        rows.append(_control_row(cut_name(f), "C1_RANDOM_MATCHED", None, n, deficit,
                                 {b: np.array(means[b]) for b in means}))

        # C2/C3/C4 -- single-variable THRESHOLD rules firing on the same number of
        # trades, selected causally (see `_threshold_trigger`).
        for name, col in (("C2_RUNG_ONLY", "rung_atr"),
                          ("C3_TIME_SINCE_CONFIRM_ONLY", "seconds_since_confirm"),
                          ("C4_DRAWDOWN_FROM_HWM_ONLY", "drawdown_from_hwm_atr")):
            for direction, ascending in (("ASC", True), ("DESC", False)):
                sel, fired = _threshold_trigger(d, col, ascending, n)
                rows.append(_control_row(cut_name(f), f"{name}_{direction}", sel, n,
                                         max(0, n - fired), None))
    return pd.DataFrame(rows)


def _control_row(cut: str, control: str, sel: pd.DataFrame | None, n_target: int,
                 deficit: int, reps: dict | None) -> dict:
    r = {"cut": cut, "control": control, "n_target_triggers": n_target,
         "match_deficit": deficit}
    if reps is not None:
        r["n_triggers"] = n_target
        for b in ("mark", "hwm"):
            v = reps[b][~np.isnan(reps[b])]
            r[f"difference_{b}_atr"] = float(v.mean()) if v.size else None
            r[f"ci95_lo_{b}"] = float(np.quantile(v, 0.025)) if v.size else None
            r[f"ci95_hi_{b}"] = float(np.quantile(v, 0.975)) if v.size else None
        r["n_replications"] = 200
        return r
    r["n_triggers"] = len(sel)
    r["mean_rung"] = float(sel["rung_atr"].mean()) if len(sel) else None
    r["median_seconds_since_confirm"] = (float(sel["seconds_since_confirm"].median())
                                         if len(sel) else None)
    r["mean_drawdown_from_hwm_atr"] = (float(sel["drawdown_from_hwm_atr"].mean())
                                       if len(sel) else None)
    for b in ("mark", "hwm"):
        r[f"difference_{b}_atr"] = float(sel[f"cme_{b}"].mean()) if len(sel) else None
        if len(sel):
            lo, hi = trade_clustered_ci(sel[f"cme_{b}"].to_numpy(),
                                        sel["regime_id"].to_numpy())
            r[f"ci95_lo_{b}"], r[f"ci95_hi_{b}"] = lo, hi
    return r


# --- Phase 10 ----------------------------------------------------------------------

FORENSIC_FEATURES: tuple[str, ...] = (
    "current_mfe_atr", "rung_atr", "return_from_entry_atr", "return_since_confirm_atr",
    "drawdown_from_hwm_atr", "rung_overshoot_atr",
    "seconds_since_confirm", "seconds_since_entry",
    "seconds_since_last_favourable_extreme", "n_recent_favourable_extremes",
    "progress_15s_atr", "progress_30s_atr", "progress_60s_atr",
    "adverse_progress_15s_atr", "adverse_progress_30s_atr", "adverse_progress_60s_atr",
    "realized_vol_15s_atr", "realized_vol_30s_atr", "realized_vol_60s_atr",
    "bar_range_60s_atr", "dir_efficiency_60s", "dir_efficiency_300s",
    "exit_score_now", "exit_score_change_15s", "exit_score_change_60s",
    "exit_score_slope_30s", "exit_score_slope_60s", "exit_score_range_60s",
    "oos_prob",
)


def phase10_forensics(d: pd.DataFrame) -> pd.DataFrame:
    """Which features characterise the low tail? Descriptive only -- no retraining,
    no SHAP, and no claim that a difference here is causal."""
    p = d["oos_prob"].to_numpy()
    rows = []
    for feat in FORENSIC_FEATURES:
        if feat not in d.columns:
            rows.append({"feature": feat, "status": "ABSENT_FROM_FROZEN_ARTIFACT"})
            continue
        allv = d[feat].astype(float)
        mu, sd = float(allv.mean()), float(allv.std(ddof=1))
        r = {"feature": feat, "status": "OK", "all_mean": mu,
             "all_median": float(allv.median()), "all_std": sd}
        for f in (0.25, 0.10, 0.05):
            s = d[nested_mask(p, f)][feat].astype(float)
            tag = cut_name(f)
            r[f"{tag}_mean"] = float(s.mean())
            r[f"{tag}_median"] = float(s.median())
            # Standardised mean difference against the full population.
            r[f"{tag}_smd"] = float((s.mean() - mu) / sd) if sd else None
        rows.append(r)
    out = pd.DataFrame(rows)
    if "bottom_5_smd" in out.columns:
        out = out.sort_values("bottom_5_smd", key=lambda c: c.abs(), ascending=False)
    return out.reset_index(drop=True)


def phase10_mechanism(d: pd.DataFrame) -> dict:
    """What is the low tail actually made of?

    Two questions the SMD table alone cannot settle: how strongly the score tracks
    each candidate confounder across the WHOLE population, and how far the ML trigger
    set physically overlaps the single-feature rule it most resembles.
    """
    p = pd.Series(d["oos_prob"].to_numpy())
    rho = {c: float(p.corr(d[c].astype(float), method="spearman"))
           for c in ("drawdown_from_hwm_atr", "rung_overshoot_atr", "rung_atr",
                     "seconds_since_confirm", "current_mfe_atr", "realized_vol_60s_atr")}

    overlap = {}
    pv = d["oos_prob"].to_numpy()
    for f in CONTROL_CUTS:
        ml = set(_first_trigger(d, nested_mask(pv, f))["regime_id"])
        n = len(ml)
        # Same CAUSAL threshold rule the placebo uses -- not a within-trade extremum.
        rival, _ = _threshold_trigger(d, "drawdown_from_hwm_atr", False, n)
        k = len(ml & set(rival["regime_id"]))
        overlap[cut_name(f)] = {"n_triggers": n, "n_shared_with_C4_DESC": k,
                                "pct_shared": 100.0 * k / n if n else None}

    m10 = nested_mask(pv, 0.10)
    age = {"pct_age_zero_bottom_10": 100.0 * float((d[m10]["seconds_since_confirm"] == 0).mean()),
           "pct_age_zero_population": 100.0 * float((d["seconds_since_confirm"] == 0).mean()),
           "median_age_bottom_10": float(d[m10]["seconds_since_confirm"].median()),
           "median_age_population": float(d["seconds_since_confirm"].median())}
    return {"spearman_score_vs_feature": rho,
            "ml_trigger_overlap_with_drawdown_rule": overlap,
            "age_composition": age}
