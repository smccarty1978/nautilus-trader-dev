"""Broad post-confirmation MFE conservation and opposing fade-model exit study.

Engine. Produces one row per (trade_id, initial_stop_atr, policy_id), plus
model-warning event and diagnostic-anchor tables.

Read-only with respect to every canonical artifact. No NautilusTrader run.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import polars as pl

STUDY_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = STUDY_DIR.parents[1]
BUILDER = REPO_ROOT / "studies" / "full_trade_path_builder"
CONS = BUILDER / "consolidated"
sys.path.insert(0, str(BUILDER / "implementation"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from canonical_research_loader import scan_canonical_research_population  # noqa: E402
from policy_defs import (  # noqa: E402
    BEARISH_THRESHOLDS,
    BULLISH_THRESHOLDS,
    FLAT_TOLERANCE_POINTS,
    INITIAL_STOPS,
    PERSISTENCE_K,
    REPRESENTATIVE_PRICE_RULES,
    THRESHOLD_NAMES,
    THRESHOLD_SCOPE,
    price_policies,
)

SUMMARIES = CONS / "canonical_trade_summaries_all.parquet"
PATHS = CONS / "canonical_trade_paths_all.parquet"
RESULTS = STUDY_DIR / "results"

NONE = -1  # "no such index" sentinel

I64, F64, STR, BOOL = pl.Int64, pl.Float64, pl.String, pl.Boolean

POLICY_SCHEMA = {
    "trade_id": STR, "model_id": STR, "trade_direction": I64,
    "trade_direction_name": STR, "entry_year": I64, "entry_timestamp": I64,
    "entry_price": F64, "entry_atr": F64, "confirmation_timestamp": I64,
    "opposing_flip_timestamp": I64, "path_bars": I64, "regime_start_ns": I64,
    "initial_stop_atr": F64, "policy_id": STR, "policy_family": STR,
    "policy_scope": STR, "outcome_class": STR, "exit_reason": STR,
    "exit_bar_index": I64, "exit_timestamp": I64,
    "realized_return_points": F64, "mfe_at_exit_atr": F64, "censor_reason": STR,
    "realized_return_atr": F64, "peak_mfe_full_path_atr": F64,
    "giveback_atr": F64, "capture_ratio": F64, "seconds_entry_to_exit": F64,
    "seconds_confirmation_to_exit": F64, "activation_mfe_atr": F64,
    "policy_param": F64, "threshold_name": STR, "persistence_k": I64,
    "same_bar_activation_and_violation": BOOL, "price_model_tie": BOOL,
    "warning_timestamp": I64,
}

WARN_SCHEMA = {
    "trade_id": STR, "model_id": STR, "trade_direction_name": STR,
    "entry_year": I64, "threshold_name": STR, "threshold_value": F64,
    "threshold_state": STR, "post_confirmation_eligible_obs": I64,
    "pre_confirmation_eligible_obs": I64, "already_active_at_confirmation": BOOL,
    "warning_bar_index": I64, "warning_timestamp": I64,
    "seconds_confirmation_to_warning": F64, "mfe_at_warning_atr": F64,
    "unrealized_return_at_warning_atr": F64,
    "remaining_mfe_after_warning_atr": F64, "peak_mfe_atr": F64,
    "seconds_warning_to_fallback_exit": F64,
    "opposing_probability_at_confirmation": F64,
    "max_opposing_probability_post_confirmation": F64,
    "k2_warning_timestamp": I64, "k3_warning_timestamp": I64,
    "seconds_k1_to_k2": F64, "seconds_k1_to_k3": F64,
}

ANCHOR_SCHEMA = {
    "trade_id": STR, "model_id": STR, "trade_direction_name": STR,
    "entry_year": I64, "anchor": STR, "anchor_bar_index": I64,
    "anchor_timestamp": I64, "seconds_from_confirmation": F64,
    "running_mfe_atr": F64, "close_excursion_atr": F64,
    "opposing_probability": F64, "opposing_in_domain": BOOL,
    "opposing_change_from_prior_obs": F64, "opposing_change_30s": F64,
    "opposing_change_60s": F64, "seconds_since_opposing_entered_domain": F64,
    "entry_model_probability": F64, "entry_model_in_domain": BOOL,
}


def log(**kw) -> None:
    print(json.dumps({"t": round(time.time() % 100000, 1), **kw}), flush=True)


# --------------------------------------------------------------------- load
def load_bundle() -> tuple[pl.DataFrame, dict[str, np.ndarray], np.ndarray]:
    """Return (summaries, path column arrays, per-trade path offsets)."""
    log(stage="load_summaries")
    s = (
        scan_canonical_research_population(str(SUMMARIES))
        .select(
            "trade_id", "model_id", "entry_model_id", "trade_direction",
            "trade_direction_name", "entry_year", "entry_month", "instrument_id",
            "regime_start_ns", "selection_regime_key",
            "checkpoint_decision_ns", "checkpoint_reference_price", "atr_at_entry",
            "confirm_flip_ns", "fallback_exit_flip_ns", "path_is_complete",
            "censor_reason", "fallback_exit_mark_return_points",
            "full_trade_mfe_atr", "full_trade_mae_atr",
            "seconds_entry_to_confirm", "seconds_entry_to_fallback_exit",
            "entry_probability", "entry_top_2_5_threshold",
            "opposite_exit_model_id",
        )
        .collect(engine="streaming")
        .sort("trade_id")
    )
    if s.height != 5836 or s["trade_id"].n_unique() != s.height:
        raise AssertionError(f"unexpected summary population: {s.height}")

    log(stage="load_paths")
    is_short = pl.col("trade_direction") == -1
    p = (
        scan_canonical_research_population(str(PATHS))
        .select(
            "trade_id", "path_sequence", "timestamp_open_ns", "timestamp_close_ns",
            "open", "trade_direction",
            "adverse_intrabar_extreme_atr", "favorable_intrabar_extreme_atr",
            "running_mfe_atr",
            "bullish_probability", "bullish_in_domain", "bullish_is_carried_forward",
            "bullish_score_source_ns",
            "bearish_probability", "bearish_in_domain", "bearish_is_carried_forward",
            "bearish_score_source_ns",
        )
        .with_columns(
            # SHORT (entry BULLISH_STRICT) opposes the bearish channel; LONG opposes bullish
            pl.when(is_short).then(pl.col("bearish_probability"))
              .otherwise(pl.col("bullish_probability")).alias("opp_prob"),
            pl.when(is_short).then(pl.col("bearish_in_domain"))
              .otherwise(pl.col("bullish_in_domain")).fill_null(False).alias("opp_dom"),
            pl.when(is_short).then(pl.col("bearish_is_carried_forward"))
              .otherwise(pl.col("bullish_is_carried_forward")).fill_null(True)
              .alias("opp_carried"),
            pl.when(is_short).then(pl.col("bearish_score_source_ns"))
              .otherwise(pl.col("bullish_score_source_ns")).alias("opp_src_ns"),
            pl.when(is_short).then(pl.col("bullish_probability"))
              .otherwise(pl.col("bearish_probability")).alias("ent_prob"),
            pl.when(is_short).then(pl.col("bullish_in_domain"))
              .otherwise(pl.col("bearish_in_domain")).fill_null(False).alias("ent_dom"),
            pl.when(is_short).then(pl.col("bullish_is_carried_forward"))
              .otherwise(pl.col("bearish_is_carried_forward")).fill_null(True)
              .alias("ent_carried"),
        )
        .select(
            "trade_id", "path_sequence", "timestamp_open_ns", "timestamp_close_ns",
            "open", "adverse_intrabar_extreme_atr", "favorable_intrabar_extreme_atr",
            "running_mfe_atr", "opp_prob", "opp_dom", "opp_carried", "opp_src_ns",
            "ent_prob", "ent_dom", "ent_carried",
        )
        .sort(["trade_id", "path_sequence"])
        .collect(engine="streaming")
    )
    log(stage="paths_loaded", rows=p.height)

    sizes = p.group_by("trade_id", maintain_order=True).len()
    if sizes["trade_id"].to_list() != s["trade_id"].to_list():
        raise AssertionError("path trade_id order does not match summaries")
    offsets = np.concatenate([[0], np.cumsum(sizes["len"].to_numpy())]).astype(np.int64)

    cols = {
        "to_ns": p["timestamp_open_ns"].to_numpy(),
        "tc_ns": p["timestamp_close_ns"].to_numpy(),
        "open": p["open"].to_numpy(),
        "adv": p["adverse_intrabar_extreme_atr"].to_numpy(),
        "fav": p["favorable_intrabar_extreme_atr"].to_numpy(),
        "mfe": p["running_mfe_atr"].to_numpy(),
        "opp_prob": p["opp_prob"].to_numpy(),
        "opp_dom": p["opp_dom"].to_numpy(),
        "opp_carried": p["opp_carried"].to_numpy(),
        "opp_src": p["opp_src_ns"].to_numpy(),
        "ent_prob": p["ent_prob"].to_numpy(),
        "ent_dom": p["ent_dom"].to_numpy(),
        "ent_carried": p["ent_carried"].to_numpy(),
        "seq": p["path_sequence"].to_numpy(),
    }
    del p
    return s, cols, offsets


# ---------------------------------------------------------------- primitives
def _first_true(mask: np.ndarray) -> int:
    idx = np.flatnonzero(mask)
    return int(idx[0]) if idx.size else NONE


def _price_exit_index(adv, lag_mfe, base_ok, activation, kind, param,
                      extra_ok=None) -> int:
    """First index at which the armed protective floor is violated."""
    armed = lag_mfe >= activation
    if kind == "fixed":
        floor = param
        viol = adv <= floor
    elif kind == "giveback":
        viol = adv <= np.maximum(0.0, lag_mfe - param)
    elif kind == "retention":
        viol = adv <= lag_mfe * param
    else:
        raise ValueError(kind)
    mask = base_ok & armed & viol
    if extra_ok is not None:
        mask = mask & extra_ok
    return _first_true(mask)


def _same_bar_activation_and_violation(mfe, adv, base_ok, activation, kind, param,
                                       exit_idx) -> bool:
    """True when the exit bar is also the bar that first armed the rule.

    Reported as ambiguity sensitivity only; the lagged floor already resolves it.
    """
    if exit_idx == NONE:
        return False
    prev = mfe[exit_idx - 1] if exit_idx > 0 else 0.0
    return bool(prev < activation <= mfe[exit_idx])


# ------------------------------------------------------------ model warnings
def _eligible_obs(opp_dom, opp_carried, opp_prob, n) -> np.ndarray:
    """Indices of genuinely new, in-domain opposing-model observations."""
    ok = opp_dom & (~opp_carried) & np.isfinite(opp_prob)
    return np.flatnonzero(ok)


def _warning_index(elig, opp_prob, exec_start, threshold, k) -> tuple[int, int]:
    """First post-confirmation crossing sustained for k eligible observations.

    Returns (exit_bar_index, crossing_bar_index) or (NONE, NONE).
    """
    post = elig[elig >= exec_start]
    if post.size == 0:
        return NONE, NONE
    pre = elig[elig < exec_start]
    prev_above = bool(opp_prob[pre[-1]] >= threshold) if pre.size else False
    above = opp_prob[post] >= threshold
    n = post.size
    for j in range(n):
        crossing = above[j] and not (above[j - 1] if j > 0 else prev_above)
        if crossing and j + k <= n and above[j:j + k].all():
            return int(post[j + k - 1]), int(post[j])
    return NONE, NONE


# ------------------------------------------------------------------- resolve
def _classify(exit_idx, exit_kind, n, tc_ns, to_ns, confirm_ns, fallback_ns,
              path_complete, open_px, entry_px, direction, atr, mfe,
              fallback_points):
    """Return the terminal record for one policy on one trade."""
    if exit_idx != NONE:
        # Ambiguity is evaluated before censoring, matching the frozen baseline:
        # an exit bar that coincides with the confirmation or opposing-flip mark
        # has an unresolvable event order whether or not a fill bar follows.
        touch_ns = int(tc_ns[exit_idx])
        if touch_ns in (confirm_ns, fallback_ns):
            return {
                "outcome_class": "AMBIGUOUS EVENT ORDER",
                "exit_reason": exit_kind, "exit_bar_index": exit_idx,
                "exit_timestamp": touch_ns, "realized_return_points": None,
                "mfe_at_exit_atr": float(mfe[exit_idx]), "censor_reason": None,
            }
        if exit_idx + 1 >= n:
            return {
                "outcome_class": "CENSORED / UNRESOLVED",
                "exit_reason": exit_kind, "exit_bar_index": exit_idx,
                "exit_timestamp": None, "realized_return_points": None,
                "mfe_at_exit_atr": float(mfe[exit_idx]),
                "censor_reason": "exit_bar_has_no_following_open",
            }
        fill_ns = int(to_ns[exit_idx + 1])
        if fill_ns in (confirm_ns, fallback_ns):
            return {
                "outcome_class": "AMBIGUOUS EVENT ORDER",
                "exit_reason": exit_kind, "exit_bar_index": exit_idx,
                "exit_timestamp": int(tc_ns[exit_idx]),
                "realized_return_points": None,
                "mfe_at_exit_atr": float(mfe[exit_idx]),
                "censor_reason": None,
            }
        pts = float((open_px[exit_idx + 1] - entry_px) * direction)
        if exit_kind == "INITIAL_STOP":
            cls = ("STOPPED BEFORE CONFIRMATION"
                   if int(tc_ns[exit_idx]) < confirm_ns
                   else "STOPPED AFTER CONFIRMATION")
        elif exit_kind == "PRICE_MANAGEMENT":
            cls = "PRICE MANAGEMENT EXIT"
        else:
            cls = "MODEL WARNING EXIT"
        return {
            "outcome_class": cls, "exit_reason": exit_kind,
            "exit_bar_index": exit_idx, "exit_timestamp": fill_ns,
            "realized_return_points": pts,
            "mfe_at_exit_atr": float(mfe[exit_idx]),
            "censor_reason": None,
        }
    if not path_complete or fallback_points is None:
        return {
            "outcome_class": "CENSORED / UNRESOLVED", "exit_reason": "NO_EXIT",
            "exit_bar_index": NONE, "exit_timestamp": None,
            "realized_return_points": None,
            "mfe_at_exit_atr": float(mfe[n - 1]),
            "censor_reason": "incomplete_path",
        }
    if abs(fallback_points) <= FLAT_TOLERANCE_POINTS:
        cls = "REGIME-FLIP EXIT FLAT"
    elif fallback_points > 0:
        cls = "REGIME-FLIP EXIT FOR PROFIT"
    else:
        cls = "REGIME-FLIP EXIT FOR LOSS"
    return {
        "outcome_class": cls, "exit_reason": "OPPOSING_REGIME_FLIP",
        "exit_bar_index": n - 1, "exit_timestamp": fallback_ns,
        "realized_return_points": float(fallback_points),
        "mfe_at_exit_atr": float(mfe[n - 1]),
        "censor_reason": None,
    }


# ---------------------------------------------------------------------- main
def run(limit: int | None = None) -> None:
    s, C, off = load_bundle()
    n_trades = s.height

    meta = {c: s[c].to_numpy() if s[c].dtype != pl.String else s[c].to_list()
            for c in ["trade_id", "model_id", "trade_direction", "trade_direction_name",
                      "entry_year", "checkpoint_decision_ns", "checkpoint_reference_price",
                      "atr_at_entry", "confirm_flip_ns", "fallback_exit_flip_ns",
                      "path_is_complete", "fallback_exit_mark_return_points",
                      "regime_start_ns"]}
    fb_pts_null = s["fallback_exit_mark_return_points"].is_null().to_numpy()

    PP = price_policies()
    price_by_id = {p["policy_id"]: p for p in PP}

    rows: list[dict] = []
    warn_rows: list[dict] = []
    anchor_rows: list[dict] = []

    parts_dir = RESULTS / "_parts"
    if parts_dir.exists():
        for f in parts_dir.glob("*.parquet"):
            f.unlink()
    parts_dir.mkdir(parents=True, exist_ok=True)
    part_no = [0]
    written = [0]

    def flush(force: bool = False) -> None:
        if not rows or (not force and len(rows) < 150_000):
            return
        pl.DataFrame(rows, schema=POLICY_SCHEMA).write_parquet(
            parts_dir / f"part_{part_no[0]:04d}.parquet", compression="zstd")
        written[0] += len(rows)
        part_no[0] += 1
        rows.clear()

    total = n_trades if limit is None else min(limit, n_trades)
    log(stage="simulate", trades=total)
    for ti in range(total):
        a, b = int(off[ti]), int(off[ti + 1])
        n = b - a
        adv = C["adv"][a:b]
        mfe = C["mfe"][a:b]
        tc = C["tc_ns"][a:b]
        to = C["to_ns"][a:b]
        opx = C["open"][a:b]
        opp_prob = C["opp_prob"][a:b]
        opp_dom = C["opp_dom"][a:b]
        opp_carr = C["opp_carried"][a:b]
        ent_prob = C["ent_prob"][a:b]
        ent_dom = C["ent_dom"][a:b]
        ent_carr = C["ent_carried"][a:b]

        trade_id = meta["trade_id"][ti]
        direction = int(meta["trade_direction"][ti])
        dname = meta["trade_direction_name"][ti]
        entry_px = float(meta["checkpoint_reference_price"][ti])
        atr = float(meta["atr_at_entry"][ti])
        confirm_ns = int(meta["confirm_flip_ns"][ti])
        fallback_ns = int(meta["fallback_exit_flip_ns"][ti])
        path_complete = bool(meta["path_is_complete"][ti])
        fb_pts = None if fb_pts_null[ti] else float(meta["fallback_exit_mark_return_points"][ti])
        year = int(meta["entry_year"][ti])
        entry_ns = int(meta["checkpoint_decision_ns"][ti])
        model_id = meta["model_id"][ti]

        # causal execution window: first bar entirely at/after confirmation
        exec_start = int(np.searchsorted(to, confirm_ns, side="left"))
        idxs = np.arange(n)
        base_ok = idxs >= exec_start
        lag_mfe = np.empty(n)
        lag_mfe[0] = 0.0
        lag_mfe[1:] = mfe[:-1]

        # initial stop touch index per stop width
        run_min = np.minimum.accumulate(adv)
        stop_idx = {S: (int(np.searchsorted(-run_min, S, side="left"))
                        if (-run_min[-1]) >= S else NONE) for S in INITIAL_STOPS}
        for S, v in list(stop_idx.items()):
            if v != NONE and v >= n:
                stop_idx[S] = NONE

        # ---- price-management exit indices (stop independent)
        price_exit = {}
        price_samebar = {}
        for p in PP:
            e = _price_exit_index(adv, lag_mfe, base_ok, p["activation_mfe_atr"],
                                  p["kind"], p["param"])
            price_exit[p["policy_id"]] = e
            price_samebar[p["policy_id"]] = _same_bar_activation_and_violation(
                mfe, adv, base_ok, p["activation_mfe_atr"], p["kind"], p["param"], e)

        # ---- opposing model warnings
        elig = _eligible_obs(opp_dom, opp_carr, opp_prob, n)
        thr_vals = {}
        for t in THRESHOLD_NAMES:
            v = (BEARISH_THRESHOLDS if direction == -1 else BULLISH_THRESHOLDS)[t]
            thr_vals[t] = v
        warn_exit = {}
        warn_cross = {}
        for t in THRESHOLD_NAMES:
            if thr_vals[t] is None:
                for k in PERSISTENCE_K:
                    warn_exit[(t, k)] = NONE
                    warn_cross[(t, k)] = NONE
                continue
            for k in PERSISTENCE_K:
                e, c = _warning_index(elig, opp_prob, exec_start, thr_vals[t], k)
                warn_exit[(t, k)] = e
                warn_cross[(t, k)] = c

        # ---- warning-event diagnostics table (one row per trade x threshold)
        pre = elig[elig < exec_start]
        post = elig[elig >= exec_start]
        for t in THRESHOLD_NAMES:
            thr = thr_vals[t]
            if thr is None:
                warn_rows.append({
                    "trade_id": trade_id, "model_id": model_id,
                    "trade_direction_name": dname, "entry_year": year,
                    "threshold_name": t, "threshold_value": None,
                    "threshold_state": "THRESHOLD NOT FROZEN",
                    "post_confirmation_eligible_obs": int(post.size),
                    "pre_confirmation_eligible_obs": int(pre.size),
                    "already_active_at_confirmation": None,
                    "warning_bar_index": None, "warning_timestamp": None,
                    "seconds_confirmation_to_warning": None,
                    "mfe_at_warning_atr": None,
                    "unrealized_return_at_warning_atr": None,
                    "remaining_mfe_after_warning_atr": None,
                    "peak_mfe_atr": float(mfe[n - 1]),
                    "seconds_warning_to_fallback_exit": None,
                    "opposing_probability_at_confirmation": None,
                    "max_opposing_probability_post_confirmation": None,
                    "k2_warning_timestamp": None, "k3_warning_timestamp": None,
                    "seconds_k1_to_k2": None, "seconds_k1_to_k3": None,
                })
                continue
            already = bool(opp_prob[pre[-1]] >= thr) if pre.size else False
            e1 = warn_exit[(t, 1)]
            if post.size == 0:
                state = "NO VALID OBSERVATIONS"
            elif e1 != NONE:
                state = "CROSSES AFTER CONFIRMATION"
            elif already and (opp_prob[post] >= thr).all():
                state = "ALREADY ABOVE AT CONFIRMATION, NEVER RE-CROSSES"
            elif (opp_prob[post] >= thr).any():
                state = "ABOVE WITHOUT A QUALIFYING CROSSING"
            else:
                state = "NEVER REACHES THRESHOLD"
            e2, e3 = warn_exit[(t, 2)], warn_exit[(t, 3)]
            wr = {
                "trade_id": trade_id, "model_id": model_id,
                "trade_direction_name": dname, "entry_year": year,
                "threshold_name": t, "threshold_value": float(thr),
                "threshold_state": state,
                "post_confirmation_eligible_obs": int(post.size),
                "pre_confirmation_eligible_obs": int(pre.size),
                "already_active_at_confirmation": already,
                "warning_bar_index": None, "warning_timestamp": None,
                "seconds_confirmation_to_warning": None,
                "mfe_at_warning_atr": None,
                "unrealized_return_at_warning_atr": None,
                "remaining_mfe_after_warning_atr": None,
                "peak_mfe_atr": float(mfe[n - 1]),
                "seconds_warning_to_fallback_exit": None,
                "opposing_probability_at_confirmation": (
                    float(opp_prob[pre[-1]]) if pre.size else None),
                "max_opposing_probability_post_confirmation": (
                    float(np.nanmax(opp_prob[post])) if post.size else None),
                "k2_warning_timestamp": (int(tc[e2]) if e2 != NONE else None),
                "k3_warning_timestamp": (int(tc[e3]) if e3 != NONE else None),
                "seconds_k1_to_k2": None, "seconds_k1_to_k3": None,
            }
            if e1 != NONE:
                wr["warning_bar_index"] = int(e1)
                wr["warning_timestamp"] = int(tc[e1])
                wr["seconds_confirmation_to_warning"] = (int(tc[e1]) - confirm_ns) / 1e9
                wr["mfe_at_warning_atr"] = float(mfe[e1])
                wr["unrealized_return_at_warning_atr"] = float(
                    (opx[e1 + 1] - entry_px) * direction / atr) if e1 + 1 < n else None
                wr["remaining_mfe_after_warning_atr"] = float(mfe[n - 1] - mfe[e1])
                wr["seconds_warning_to_fallback_exit"] = (
                    (fallback_ns - int(tc[e1])) / 1e9 if path_complete else None)
                if e2 != NONE:
                    wr["seconds_k1_to_k2"] = (int(tc[e2]) - int(tc[e1])) / 1e9
                if e3 != NONE:
                    wr["seconds_k1_to_k3"] = (int(tc[e3]) - int(tc[e1])) / 1e9
            warn_rows.append(wr)

        # ---- B4/B5 diagnostic anchors
        peak_idx = int(np.argmax(mfe >= mfe[n - 1])) if mfe[n - 1] > 0 else n - 1
        anchors: list[tuple[str, int]] = [("CONFIRMATION", min(exec_start, n - 1))]
        for lvl in (1.00, 1.50, 2.00):
            hit = _first_true(base_ok & (mfe >= lvl))
            anchors.append((f"MFE_{lvl:.2f}_FIRST_REACHED", hit))
        anchors.append(("PEAK_MFE", peak_idx))
        for g in (0.25, 0.50, 0.75, 1.00):
            hit = _first_true(base_ok & (adv <= lag_mfe - g) & (lag_mfe > 0))
            anchors.append((f"GIVEBACK_{g:.2f}_FROM_PEAK", hit))
        anchors.append(("BASELINE_FINAL_EXIT", n - 1))
        for name, i in anchors:
            if i == NONE or i >= n:
                continue
            prev_e = elig[elig < i]
            cur = float(opp_prob[prev_e[-1]]) if prev_e.size else None
            cur_dom = bool(opp_dom[i])
            prior = float(opp_prob[prev_e[-2]]) if prev_e.size >= 2 else None
            t_i = int(tc[i])

            def _as_of(delta_s: float):
                j = np.searchsorted(tc, t_i - int(delta_s * 1e9), side="right") - 1
                if j < 0:
                    return None
                pe = elig[elig <= j]
                return float(opp_prob[pe[-1]]) if pe.size else None

            first_dom = _first_true(opp_dom & (~opp_carr))
            anchor_rows.append({
                "trade_id": trade_id, "model_id": model_id,
                "trade_direction_name": dname, "entry_year": year,
                "anchor": name, "anchor_bar_index": int(i),
                "anchor_timestamp": t_i,
                "seconds_from_confirmation": (t_i - confirm_ns) / 1e9,
                "running_mfe_atr": float(mfe[i]),
                "close_excursion_atr": float(adv[i]),
                "opposing_probability": cur,
                "opposing_in_domain": cur_dom,
                "opposing_change_from_prior_obs": (
                    None if cur is None or prior is None else cur - prior),
                "opposing_change_30s": (
                    None if cur is None or _as_of(30) is None else cur - _as_of(30)),
                "opposing_change_60s": (
                    None if cur is None or _as_of(60) is None else cur - _as_of(60)),
                "seconds_since_opposing_entered_domain": (
                    None if first_dom == NONE or first_dom > i
                    else (t_i - int(tc[first_dom])) / 1e9),
                "entry_model_probability": (
                    float(ent_prob[i]) if np.isfinite(ent_prob[i]) else None),
                "entry_model_in_domain": bool(ent_dom[i]),
            })

        # ---- resolve every policy at every stop
        common = dict(
            trade_id=trade_id, model_id=model_id, trade_direction=direction,
            trade_direction_name=dname, entry_year=year, entry_timestamp=entry_ns,
            entry_price=entry_px, entry_atr=atr, confirmation_timestamp=confirm_ns,
            opposing_flip_timestamp=fallback_ns, path_bars=n,
            regime_start_ns=int(meta["regime_start_ns"][ti]),
        )
        peak_mfe_full = float(mfe[n - 1])

        for S in INITIAL_STOPS:
            i_s = stop_idx[S]

            def emit(pid, family, scope, exit_idx, exit_kind, extra):
                rec = _classify(exit_idx, exit_kind, n, tc, to, confirm_ns,
                                fallback_ns, path_complete, opx, entry_px,
                                direction, atr, mfe, fb_pts)
                pts = rec["realized_return_points"]
                ret_atr = None if pts is None else pts / atr
                m = rec["mfe_at_exit_atr"]
                rows.append({
                    **common, "initial_stop_atr": S, "policy_id": pid,
                    "policy_family": family, "policy_scope": scope,
                    **rec,
                    "realized_return_atr": ret_atr,
                    "peak_mfe_full_path_atr": peak_mfe_full,
                    "giveback_atr": None if ret_atr is None else m - ret_atr,
                    "capture_ratio": (None if ret_atr is None or m <= 0
                                      else ret_atr / m),
                    "seconds_entry_to_exit": (
                        None if rec["exit_timestamp"] is None
                        else (rec["exit_timestamp"] - entry_ns) / 1e9),
                    "seconds_confirmation_to_exit": (
                        None if rec["exit_timestamp"] is None
                        else (rec["exit_timestamp"] - confirm_ns) / 1e9),
                    **extra,
                })

            # BASE
            emit("BASE", "BASELINE", "ALL", i_s, "INITIAL_STOP",
                 {"activation_mfe_atr": None, "policy_param": None,
                  "threshold_name": None, "persistence_k": None,
                  "same_bar_activation_and_violation": False,
                  "price_model_tie": False,
                  "warning_timestamp": None})

            # A families
            for p in PP:
                e_m = price_exit[p["policy_id"]]
                if i_s != NONE and (e_m == NONE or i_s < e_m):
                    emit(p["policy_id"], p["policy_family"], "ALL", i_s,
                         "INITIAL_STOP",
                         {"activation_mfe_atr": p["activation_mfe_atr"],
                          "policy_param": p["param"], "threshold_name": None,
                          "persistence_k": None,
                          "same_bar_activation_and_violation": False,
                          "price_model_tie": False, "warning_timestamp": None})
                else:
                    emit(p["policy_id"], p["policy_family"], "ALL", e_m,
                         "PRICE_MANAGEMENT",
                         {"activation_mfe_atr": p["activation_mfe_atr"],
                          "policy_param": p["param"], "threshold_name": None,
                          "persistence_k": None,
                          "same_bar_activation_and_violation":
                              price_samebar[p["policy_id"]],
                          "price_model_tie": False, "warning_timestamp": None})

            # B family
            for t in THRESHOLD_NAMES:
                scope = THRESHOLD_SCOPE[t]
                if scope == "LONG_ONLY" and direction != 1:
                    continue
                for k in PERSISTENCE_K:
                    e_w = warn_exit[(t, k)]
                    tie = (i_s != NONE and e_w != NONE and i_s == e_w)
                    if i_s != NONE and (e_w == NONE or i_s <= e_w):
                        emit(f"B_{t}_k{k}", "B_MODEL_EXIT", scope, i_s,
                             "INITIAL_STOP",
                             {"activation_mfe_atr": None, "policy_param": None,
                              "threshold_name": t, "persistence_k": k,
                              "same_bar_activation_and_violation": False,
                              "price_model_tie": tie,
                              "warning_timestamp": (int(tc[e_w]) if e_w != NONE
                                                    else None)})
                    else:
                        emit(f"B_{t}_k{k}", "B_MODEL_EXIT", scope, e_w,
                             "MODEL_WARNING",
                             {"activation_mfe_atr": None, "policy_param": None,
                              "threshold_name": t, "persistence_k": k,
                              "same_bar_activation_and_violation": False,
                              "price_model_tie": tie,
                              "warning_timestamp": (int(tc[e_w]) if e_w != NONE
                                                    else None)})

            # C1 first-event-wins
            for pname, prule in REPRESENTATIVE_PRICE_RULES.items():
                pid_price = next(
                    q["policy_id"] for q in PP
                    if q["kind"] == prule["kind"]
                    and q["activation_mfe_atr"] == prule["activation_mfe_atr"]
                    and q["param"] == prule["param"])
                e_p = price_exit[pid_price]
                for t in THRESHOLD_NAMES:
                    scope = THRESHOLD_SCOPE[t]
                    if scope == "LONG_ONLY" and direction != 1:
                        continue
                    e_w = warn_exit[(t, 1)]
                    cands = [(e_s, kind) for e_s, kind in
                             ((i_s, "INITIAL_STOP"), (e_p, "PRICE_MANAGEMENT"),
                              (e_w, "MODEL_WARNING")) if e_s != NONE]
                    tie = (e_w != NONE and ((e_p != NONE and e_p == e_w)
                                            or (i_s != NONE and i_s == e_w)))
                    if cands:
                        order = {"PRICE_MANAGEMENT": 0, "INITIAL_STOP": 1,
                                 "MODEL_WARNING": 2}
                        e_sel, kind = min(cands, key=lambda z: (z[0], order[z[1]]))
                    else:
                        e_sel, kind = NONE, "NO_EXIT"
                    emit(f"C1_{pname}_{t}", "C1_FIRST_EVENT_WINS", scope,
                         e_sel, kind,
                         {"activation_mfe_atr": prule["activation_mfe_atr"],
                          "policy_param": prule["param"], "threshold_name": t,
                          "persistence_k": 1,
                          "same_bar_activation_and_violation":
                              price_samebar[pid_price] if kind == "PRICE_MANAGEMENT"
                              else False,
                          "price_model_tie": tie,
                          "warning_timestamp": (int(tc[e_w]) if e_w != NONE
                                                else None)})

            # C2 warning arms the price rule
            for pname, prule in REPRESENTATIVE_PRICE_RULES.items():
                for t in THRESHOLD_NAMES:
                    scope = THRESHOLD_SCOPE[t]
                    if scope == "LONG_ONLY" and direction != 1:
                        continue
                    i_w = warn_cross[(t, 1)]
                    if i_w == NONE:
                        e_m = NONE
                        samebar = False
                    else:
                        e_m = _price_exit_index(
                            adv, lag_mfe, base_ok, prule["activation_mfe_atr"],
                            prule["kind"], prule["param"], extra_ok=idxs > i_w)
                        samebar = _same_bar_activation_and_violation(
                            mfe, adv, base_ok, prule["activation_mfe_atr"],
                            prule["kind"], prule["param"], e_m)
                    if i_s != NONE and (e_m == NONE or i_s < e_m):
                        emit(f"C2_{pname}_{t}", "C2_WARNING_ARMS_TRAIL", scope,
                             i_s, "INITIAL_STOP",
                             {"activation_mfe_atr": prule["activation_mfe_atr"],
                              "policy_param": prule["param"],
                              "threshold_name": t, "persistence_k": 1,
                              "same_bar_activation_and_violation": False,
                              "price_model_tie": False,
                              "warning_timestamp": (int(tc[i_w]) if i_w != NONE
                                                    else None)})
                    else:
                        emit(f"C2_{pname}_{t}", "C2_WARNING_ARMS_TRAIL", scope,
                             e_m, "PRICE_MANAGEMENT",
                             {"activation_mfe_atr": prule["activation_mfe_atr"],
                              "policy_param": prule["param"],
                              "threshold_name": t, "persistence_k": 1,
                              "same_bar_activation_and_violation": samebar,
                              "price_model_tie": False,
                              "warning_timestamp": (int(tc[i_w]) if i_w != NONE
                                                    else None)})

        if (ti + 1) % 500 == 0:
            log(stage="progress", trades_done=ti + 1, rows_buffered=len(rows),
                rows_written=written[0])
        flush()

    flush(force=True)
    log(stage="frame", rows=written[0])
    RESULTS.mkdir(parents=True, exist_ok=True)
    df = (
        pl.scan_parquet(parts_dir / "*.parquet")
        .with_columns(
            pl.col("exit_bar_index").cast(pl.Int64),
            pl.col("realized_return_points").cast(pl.Float64),
            pl.col("realized_return_atr").cast(pl.Float64),
        )
        .sort(["initial_stop_atr", "policy_id", "trade_id"])
        .collect(engine="streaming")
    )
    df.write_parquet(RESULTS / "post_confirmation_mfe_model_exit_trade_policy_results.parquet",
                     compression="zstd", statistics=True)
    for f in parts_dir.glob("*.parquet"):
        f.unlink()
    parts_dir.rmdir()
    pl.DataFrame(warn_rows, schema=WARN_SCHEMA).write_parquet(
        RESULTS / "post_confirmation_model_warning_events.parquet",
        compression="zstd", statistics=True)
    pl.DataFrame(anchor_rows, schema=ANCHOR_SCHEMA).write_parquet(
        RESULTS / "post_confirmation_model_diagnostic_anchors.parquet",
        compression="zstd", statistics=True)
    log(stage="complete", trade_policy_rows=df.height,
        warning_rows=len(warn_rows), anchor_rows=len(anchor_rows))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    run(a.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
