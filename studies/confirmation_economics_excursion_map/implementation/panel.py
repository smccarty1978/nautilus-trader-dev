"""Per-(trade, path_mode) excursion panel. The only expensive step in the study.

One row per trade per path mode. Every later phase is a query over the parquet.

Two conventions carry the whole study and both are frozen in SPEC 1-2:

* **ATR is frozen at ENTRY** and normalises every excursion, including the
  post-confirmation ones. A post-confirm retracement of "0.50 ATR" therefore
  means half the ATR that was standing when the fade was put on, not half of
  some later ATR -- which is what makes Phase 3 and Phase 6 commensurable.

* **Two path modes.** `constrained` keeps the 1.0 ATR entry stop live and
  produces the canonical terminal labels. `unconstrained` removes it after
  confirmation, because with the stop live the post-confirmation adverse
  excursion is mechanically capped at 1 ATR from entry -- so asking "how much
  room does a >=3 ATR runner need" of the constrained path answers the question
  with its own premise. `terminal_label_constrained` rides on both rows so any
  table can group by canonical outcome in either mode.

Landmarks are **entry-relative** and counted only on FIRST achievement strictly
after the confirming flip. Landmarks already held at confirmation are recorded
as `already_at_confirm` and excluded from that landmark's retrace distribution;
median return at confirmation is around +0.85 ATR, so folding them in as a zero
retrace would fabricate the top rows of the Phase 3 table.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.candidates import (
    THRESHOLDS, load_scored,
)
from studies.model_driven_entry_exit_discovery.implementation.engine import (
    COST_POINTS, FLAT_POINTS, NS, MarketData, RegimeIndex, load_market, load_regimes,
)

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "studies/confirmation_economics_excursion_map/results"
ARMED = ROOT / "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet"

MIN_AGE_S = 600.0
STOP_ATR = 1.0
BASE_LEVELS = ("top_10", "top_5", "top_2_5", "top_1")
FULL_DEPTH = ("top_2_5", "armed")

LANDMARKS = (0.50, 0.75, 1.00, 1.25, 1.50, 2.00, 2.50, 3.00)
TRANSITION_LANDMARKS = (1.00, 1.50, 2.00, 2.50, 3.00)
FLOORS = (-0.25, 0.00, 0.25, 0.50, 0.75)
DETERIORATION = (0.25, 0.375, 0.50, 0.625, 0.75, 1.00)

STOPPED_BEFORE = "STOPPED_BEFORE_CONFIRM"
CONFIRMED_THEN_STOPPED = "CONFIRMED_THEN_STOPPED"
FLIP_WINNER = "FINAL_FLIP_EXIT_WINNER"
FLIP_LOSER = "FINAL_FLIP_EXIT_LOSER"
SESSION_EXIT = "SESSION_EXIT"


def _tag(x: float) -> str:
    return f"{x:+.2f}".replace(".", "_").replace("+", "p").replace("-", "m")


# ------------------------------------------------------------- populations

def base_population(scored: pl.DataFrame, label: str) -> pl.DataFrame:
    """The accepted first_qualifying-after-600s rule. Reproduces the frozen counts."""
    bull, bear = THRESHOLDS[label]
    thr = pl.when(pl.col("bullish_in_domain")).then(pl.lit(bull)).otherwise(pl.lit(bear))
    return (
        scored.filter((pl.col("probability") >= thr)
                      & (pl.col("seconds_from_regime_start") > MIN_AGE_S))
        .sort("checkpoint_decision_ns").group_by("regime_id").first()
        .sort("checkpoint_decision_ns")
        .with_columns(population=pl.lit(label))
    )


def armed_population(scored: pl.DataFrame) -> pl.DataFrame:
    """The accepted armed population, joined back for its entry state."""
    ids = pl.read_parquet(ARMED).filter(pl.col("valid")).select(
        "regime_id", arm_ns="arm_top10_ns")
    return (
        scored.join(ids, on="regime_id", how="inner")
        .filter(pl.col("checkpoint_decision_ns") == pl.col("arm_ns"))
        .sort("checkpoint_decision_ns")
        .with_columns(population=pl.lit("armed"))
    )


# ------------------------------------------------------------------- walk

def walk(market: MarketData, regimes: RegimeIndex, row: dict, mode: str) -> dict | None:
    """One trade, one path mode. Returns None only if the trade is unmeasurable."""
    entry_ns = int(row["checkpoint_decision_ns"])
    direction = int(row["direction"])
    entry_price = row["checkpoint_reference_price"]
    atr = row["atr_at_checkpoint"]
    if atr is None or not np.isfinite(atr) or atr <= 0 or entry_price is None:
        return None

    start = market.index_strictly_after(entry_ns)
    if start >= market.n:
        return None
    session_close_ns = int(market.day_close_ns[start])
    session_end = int(np.searchsorted(market.day_close_ns,
                                      market.day_close_ns[start], side="right"))

    confirm_ns = regimes.next_start_after(entry_ns, direction, inclusive=True)
    opposing_ns = regimes.next_start_after(entry_ns, -direction, inclusive=True)

    horizon = session_close_ns
    if opposing_ns is not None:
        horizon = min(horizon, opposing_ns)
    end = min(max(market.index_at_or_after(horizon) + 1, start + 1),
              session_end, market.n)
    if end <= start:
        return None

    hi, lo = market.high[start:end], market.low[start:end]
    cl, ts = market.close[start:end], market.ts[start:end]
    fav = (hi - entry_price) if direction > 0 else (entry_price - lo)
    adv = (entry_price - lo) if direction > 0 else (hi - entry_price)
    run_mfe = np.maximum.accumulate(np.maximum(fav, 0.0)) / atr
    run_mae = np.maximum.accumulate(np.maximum(adv, 0.0)) / atr
    # Signed, entry-relative, bar-close mark. Used for floors and for the mark
    # at confirmation.
    mark = (cl - entry_price) * direction / atr
    fav_atr, adv_atr = fav / atr, adv / atr

    stop_hits = np.flatnonzero(run_mae >= STOP_ATR)
    stop_idx = int(stop_hits[0]) if stop_hits.size else -1
    confirm_idx = -1
    if confirm_ns is not None and confirm_ns <= int(ts[-1]):
        f = np.flatnonzero(ts >= confirm_ns)
        confirm_idx = int(f[0]) if f.size else -1
    reached_opposing = opposing_ns is not None and int(ts[-1]) >= opposing_ns - NS

    # ---- canonical (constrained) terminal label, always computed
    ambiguous = stop_idx >= 0 and confirm_idx >= 0 and stop_idx == confirm_idx
    if stop_idx >= 0 and (confirm_idx < 0 or stop_idx <= confirm_idx):
        label_c, term_c = STOPPED_BEFORE, stop_idx
    elif stop_idx >= 0:
        label_c, term_c = CONFIRMED_THEN_STOPPED, stop_idx
    elif reached_opposing:
        label_c, term_c = FLIP_WINNER, ts.size - 1
    else:
        label_c, term_c = SESSION_EXIT, ts.size - 1

    def exit_px(idx: int, fills_next: bool) -> float:
        if fills_next:
            fill = start + idx + 1
            if fill < session_end and fill < market.n:
                return float(market.open_[fill])
            return float(market.close[end - 1])
        return float(market.close[start + idx])

    px_c = exit_px(term_c, label_c in (STOPPED_BEFORE, CONFIRMED_THEN_STOPPED))
    pts_c = (px_c - entry_price) * direction
    gross_c = 0.0 if abs(pts_c) < FLAT_POINTS else pts_c / atr
    if label_c == FLIP_WINNER and gross_c <= 0:
        label_c = FLIP_LOSER

    out = {
        "regime_id": row["regime_id"], "population": row["population"],
        "path_mode": mode, "direction": direction,
        "side": "LONG" if direction > 0 else "SHORT",
        "entry_year": int(row["entry_year"]), "entry_ns": entry_ns,
        "entry_price": float(entry_price), "atr": float(atr),
        "regime_age_at_entry_s": float(row["seconds_from_regime_start"]),
        "entry_probability": float(row["probability"]),
        "session_close_ns": session_close_ns,
        "confirm_ns": int(confirm_ns) if confirm_ns is not None else None,
        "opposing_ns": int(opposing_ns) if opposing_ns is not None else None,
        "terminal_label_constrained": label_c,
        "constrained_gross_atr": float(gross_c),
        "constrained_net_atr": float(gross_c - COST_POINTS / atr),
        "ambiguous_stop_confirm": bool(ambiguous),
        "confirmed": bool(confirm_idx >= 0 and (stop_idx < 0 or confirm_idx < stop_idx)),
        "confirm_in_window": bool(confirm_idx >= 0),
    }

    # A trade that was stopped before confirmation never reached confirmation and
    # therefore has no confirmation economics, in EITHER mode -- `unconstrained`
    # removes the stop only AFTER confirmation (SPEC 2). Gating here rather than
    # relying on downstream filters closes the lookahead-auditor pass-1 warning
    # that Phase 1/8 fields were written whenever the flip merely fell inside the
    # window, even if the stop had already ended the trade.
    if not out["confirmed"]:
        out["measurable_post_confirm"] = False
        return out

    # ---- Phase 1: entry -> confirmation, at the confirming flip BAR CLOSE
    out.update(
        seconds_entry_to_confirm=float((int(ts[confirm_idx]) - entry_ns) / NS),
        return_at_confirm_atr=float(mark[confirm_idx]),
        mfe_to_confirm_atr=float(run_mfe[confirm_idx]),
        mae_to_confirm_atr=float(run_mae[confirm_idx]),
        giveback_at_confirm_atr=float(run_mfe[confirm_idx] - mark[confirm_idx]),
        confirm_close_price=float(cl[confirm_idx]),
    )

    # ---- post-confirmation window. In constrained mode the stop still ends the
    # trade; in unconstrained mode it does not.
    if mode == "constrained" and stop_idx >= 0 and stop_idx > confirm_idx:
        post_end = stop_idx + 1
    else:
        post_end = ts.size
    if post_end <= confirm_idx + 1:
        out["measurable_post_confirm"] = False
        out["n_post_confirm_bars"] = 0
        return out
    out["measurable_post_confirm"] = True
    out["n_post_confirm_bars"] = int(post_end - confirm_idx - 1)

    sl = slice(confirm_idx + 1, post_end)
    p_ts = ts[sl]
    confirm_mark = float(mark[confirm_idx])

    # Two entry-relative, direction-normalised marks per post-confirm bar.
    # `bar_high_mark` is the bar's BEST level for the position, `bar_low_mark`
    # its WORST. Both are signed and unfloored -- that matters, because a bar
    # whose worst point is still above entry has a POSITIVE bar_low_mark, and
    # flooring it at zero would silently overstate every giveback.
    #   LONG :  high_mark = (high-entry)/atr   low_mark = (low-entry)/atr
    #   SHORT:  high_mark = (entry-low)/atr    low_mark = (entry-high)/atr
    bar_high_mark = fav_atr[sl]
    bar_low_mark = -adv_atr[sl]
    p_mark = mark[sl]

    # METHOD A -- adverse excursion from the CONFIRMATION CLOSE.
    # How far below the confirmation close did the path go? Uses the bar extreme
    # against the position, not the close: an intrabar excursion is what a stop
    # would actually have felt.
    adv_from_confirm = np.maximum.accumulate(
        np.maximum(confirm_mark - bar_low_mark, 0.0))

    # METHOD B -- giveback from the RUNNING FAVORABLE EXTREME.
    # The extreme is seeded with the MFE already standing at confirmation, so a
    # trade that peaked before the flip is not credited with a fresh start. It is
    # an expanding maximum, hence causal at every bar.
    running_extreme = np.maximum.accumulate(
        np.maximum(bar_high_mark, float(run_mfe[confirm_idx])))
    giveback_from_extreme = np.maximum.accumulate(
        np.maximum(running_extreme - bar_low_mark, 0.0))

    # These answer different questions and are never conflated (SPEC 4, Phase 3).
    out["max_adverse_from_confirm_atr"] = float(adv_from_confirm[-1])
    out["max_giveback_from_extreme_atr"] = float(giveback_from_extreme[-1])
    out["eventual_mfe_atr"] = float(running_extreme[-1])
    out["mfe_after_confirm_atr"] = (
        float(np.max(bar_high_mark)) if bar_high_mark.size else 0.0)
    p_fav = bar_high_mark
    run_mfe_post = running_extreme

    # Index, within the post-confirm window, of a stop that fires after the flip.
    # Needed for same-bar collision accounting (SPEC 1.1). In unconstrained mode
    # the stop is not in force, so there is no collision to account for.
    stop_post_idx = (stop_idx - confirm_idx - 1
                     if (mode == "constrained" and stop_idx > confirm_idx) else -1)
    out["stop_post_idx"] = stop_post_idx

    # ---- Phase 3: entry-relative landmarks, first touch strictly after confirm
    landmark_idx: dict[float, int] = {}
    n_amb_stop_landmark = 0
    for L in LANDMARKS:
        t = _tag(L)
        already = float(run_mfe[confirm_idx]) >= L
        out[f"lm{t}_already_at_confirm"] = bool(already)
        hits = np.flatnonzero(p_fav >= L)
        idx = int(hits[0]) if hits.size else -1
        # SPEC 1.1: a landmark first touched on the SAME bar the stop fires is
        # not resolvable from 1s OHLC. Resolve adversely -- the landmark is not
        # credited -- and flag it. The optimistic bound is
        # `reached_after_confirm or ambiguous_with_stop`.
        amb = bool(idx >= 0 and stop_post_idx >= 0 and idx == stop_post_idx)
        out[f"lm{t}_ambiguous_with_stop"] = amb
        n_amb_stop_landmark += int(amb)
        credited = idx >= 0 and not already and not amb
        out[f"lm{t}_reached_after_confirm"] = bool(credited)
        out[f"lm{t}_idx"] = idx if credited else None
        if credited:
            landmark_idx[L] = idx
            out[f"lm{t}_ns"] = int(p_ts[idx])
            out[f"lm{t}_seconds_from_confirm"] = float((int(p_ts[idx]) - int(ts[confirm_idx])) / NS)
            out[f"lm{t}_adverse_from_confirm_atr"] = float(adv_from_confirm[idx])
            out[f"lm{t}_giveback_from_extreme_atr"] = float(giveback_from_extreme[idx])
        else:
            out[f"lm{t}_ns"] = None
            out[f"lm{t}_seconds_from_confirm"] = None
            out[f"lm{t}_adverse_from_confirm_atr"] = None
            out[f"lm{t}_giveback_from_extreme_atr"] = None
    out["n_ambiguous_stop_landmark"] = n_amb_stop_landmark

    # ---- Phase 7 transitions: clock resets at each landmark's first achievement
    for a, b in zip(TRANSITION_LANDMARKS, TRANSITION_LANDMARKS[1:]):
        ta, tb = _tag(a), _tag(b)
        key = f"trans_{ta}_to_{tb}"
        # Clock reset for landmark `a`. Check "already held at confirmation"
        # FIRST. Taking the post-confirm re-touch instead would start the clock
        # after an intervening pullback and silently drop that pullback from the
        # transition's giveback -- which is precisely what Phase 7 exists to
        # measure for runners that were already past `a` when the flip landed.
        # (lookahead-auditor pass 1, CRITICAL 1.)
        if float(run_mfe[confirm_idx]) >= a:
            ia = 0
        else:
            ha = np.flatnonzero(p_fav >= a)
            ia = int(ha[0]) if ha.size else -1
        if ia < 0:
            out[f"{key}_eligible"] = False
            out[f"{key}_reached"] = None
            out[f"{key}_giveback_atr"] = None
            out[f"{key}_additional_mfe_atr"] = None
            continue
        out[f"{key}_eligible"] = True
        seg_fav, seg_ext = p_fav[ia:], run_mfe_post[ia:]
        seg_low = bar_low_mark[ia:]
        hb = np.flatnonzero(seg_fav >= b)
        ib = int(hb[0]) if hb.size else -1
        # Giveback from the running favorable extreme, measured from the moment
        # landmark `a` was first achieved, up to `b` (or to final exit if `b`
        # never comes). Against the bar's WORST level, matching Method B.
        seg_gb = np.maximum.accumulate(np.maximum(seg_ext - seg_low, 0.0))
        stop_at = ib if ib >= 0 else seg_gb.size - 1
        out[f"{key}_reached"] = bool(ib >= 0)
        out[f"{key}_giveback_atr"] = float(seg_gb[stop_at]) if seg_gb.size else None
        out[f"{key}_additional_mfe_atr"] = float(seg_ext[-1] - a)
        out[f"{key}_seconds"] = (
            float((int(p_ts[ia + ib]) - int(p_ts[ia])) / NS) if ib >= 0 else None)

    # ---- deterioration first-touch timestamps.
    # Needed so Phase 4 can time the event and Phase 9 can align a score to the
    # exact moment the price state occurs, rather than to an arbitrary landmark.
    for D in DETERIORATION:
        t = _tag(D)
        for meth, arr in (("A", adv_from_confirm), ("B", giveback_from_extreme)):
            hits = np.flatnonzero(arr >= D)
            i = int(hits[0]) if hits.size else -1
            out[f"det{meth}_{t}_ns"] = int(p_ts[i]) if i >= 0 else None
            out[f"det{meth}_{t}_open_pnl_atr"] = float(p_mark[i]) if i >= 0 else None
            out[f"det{meth}_{t}_seconds_from_confirm"] = (
                float((int(p_ts[i]) - int(ts[confirm_idx])) / NS) if i >= 0 else None)

    # ---- Phase 6 floors: entry-relative, first touch after confirmation
    n_amb_floor_landmark = 0
    for F in FLOORS:
        t = _tag(F)
        # `placeable` uses only the mark standing AT confirmation, so it is
        # decidable at t = 0 with no forward information.
        placeable = confirm_mark > F
        out[f"floor{t}_placeable"] = bool(placeable)
        if not placeable:
            out[f"floor{t}_touched"] = None
            out[f"floor{t}_ns"] = None
            out[f"floor{t}_idx"] = None
            out[f"floor{t}_ambiguous_with_landmark"] = None
            continue
        # A profit floor is a stop order: it triggers on the bar's intrabar
        # extreme against the position, not on the close. Same semantics as the
        # 1 ATR entry stop, so the two are commensurable.
        hits = np.flatnonzero(bar_low_mark <= F)
        idx = int(hits[0]) if hits.size else -1
        out[f"floor{t}_touched"] = bool(idx >= 0)
        out[f"floor{t}_ns"] = int(p_ts[idx]) if idx >= 0 else None
        out[f"floor{t}_idx"] = idx if idx >= 0 else None
        # SPEC 1.1: a floor touched on the same bar a landmark is first reached
        # is not resolvable. Flagged, never silently credited either way; Phase 6
        # reports the affected count alongside its intercept rates.
        amb = bool(idx >= 0 and idx in set(landmark_idx.values()))
        out[f"floor{t}_ambiguous_with_landmark"] = amb
        n_amb_floor_landmark += int(amb)
    out["n_ambiguous_floor_landmark"] = n_amb_floor_landmark
    out["has_same_bar_ambiguity"] = bool(
        out["ambiguous_stop_confirm"] or n_amb_stop_landmark or n_amb_floor_landmark)

    # ---- Phase 8: realized exit at the opposing flip.
    # Only meaningful where the canonical (constrained) lifecycle actually ended
    # at that flip -- a trade the stop closed first never realised a flip exit,
    # even though the flip timestamp falls inside the window.
    reached_opposing = reached_opposing and label_c in (FLIP_WINNER, FLIP_LOSER)
    out["reached_opposing_flip"] = bool(reached_opposing)
    if reached_opposing:
        out["flip_exit_return_atr"] = float(mark[-1])
        out["max_mfe_atr"] = float(run_mfe[-1])
        out["flip_exit_giveback_atr"] = float(run_mfe[-1] - mark[-1])
    return out


# ------------------------------------------------------------------ build

def build() -> pl.DataFrame:
    print("loading substrate ...", flush=True)
    market, regimes = load_market(), load_regimes()
    scored = load_scored()
    print(f"  {market.n:,} RTH 1s bars, {scored.height:,} in-domain checkpoints", flush=True)

    pops = {lab: base_population(scored, lab) for lab in BASE_LEVELS}
    pops["armed"] = armed_population(scored)
    for k, v in pops.items():
        print(f"  {k:8s} {v.height:>6,}", flush=True)

    rows = []
    for name, pop in pops.items():
        modes = ("constrained", "unconstrained") if name in FULL_DEPTH else ("constrained",)
        for mode in modes:
            n = 0
            for r in pop.iter_rows(named=True):
                w = walk(market, regimes, r, mode)
                if w is not None:
                    rows.append(w)
                    n += 1
            print(f"  walked {name}/{mode}: {n:,}", flush=True)

    df = pl.DataFrame(rows, infer_schema_length=None)
    OUT.mkdir(parents=True, exist_ok=True)
    df.write_parquet(OUT / "excursion_panel.parquet")
    print(f"\nwrote results/excursion_panel.parquet ({df.height:,} rows)")
    _manifest(df, pops, market, scored)
    return df


def _manifest(df, pops, market, scored):
    impl = Path(__file__).resolve().parents[1]
    hashes = {f"{p.parent.name}/{p.name}": hashlib.sha256(p.read_bytes()).hexdigest()[:16]
              for p in sorted(list((impl / "implementation").glob("*.py"))
                              + list((impl / "analysis").glob("*.py")))}
    (OUT / "partition_manifest.json").write_text(json.dumps({
        "study": "confirmation_economics_excursion_map",
        "substrate": "data/canonical/regime_complete_v1",
        "populations": {k: v.height for k, v in pops.items()},
        "required_base_counts": {"top_10": 8988, "top_5": 7396,
                                 "top_2_5": 5823, "top_1": 3415},
        "full_depth_populations": list(FULL_DEPTH),
        "path_modes": {
            "constrained": "1.0 ATR entry stop live; canonical terminal labels",
            "unconstrained": "stop removed after confirmation; excursion geometry",
        },
        "atr_anchor": "atr_at_checkpoint at ENTRY, frozen for the whole trade",
        "landmarks_entry_relative_atr": list(LANDMARKS),
        "transition_landmarks_atr": list(TRANSITION_LANDMARKS),
        "floors_entry_relative_atr": list(FLOORS),
        "deterioration_levels_atr": list(DETERIORATION),
        "stop_atr": STOP_ATR, "cost_points_round_turn": COST_POINTS,
        "min_regime_age_s": MIN_AGE_S,
        "rth_bars": int(market.n), "in_domain_checkpoints": int(scored.height),
        "panel_rows": df.height,
        "threshold_overlap_disclosure":
            "both calibration populations are calendar-2025 and overlap the "
            "evaluation window; 2025 is not threshold-OOS. Canonical waiver: "
            "studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json",
        "code_hashes": hashes,
    }, indent=2, default=str))


if __name__ == "__main__":
    build()
