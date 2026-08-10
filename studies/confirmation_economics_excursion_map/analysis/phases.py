"""Phases 1-8 as queries over the excursion panel.

Which path mode each phase reads is not a detail -- it is the study's central
methodological choice (SPEC 2):

    Phases 1, 2, 8  ->  constrained    (canonical terminal labels; the real strategy)
    Phases 3-7      ->  unconstrained  (excursion geometry, uncensored)

Reading Phases 3-7 off the constrained path would cap every post-confirmation
adverse excursion at 1 ATR from entry and answer "how much room does a runner
need" with its own premise. Every table states its mode.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from ..implementation.panel import (
    DETERIORATION, FLOORS, LANDMARKS, TRANSITION_LANDMARKS, _tag,
)

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "studies/confirmation_economics_excursion_map/results"
PANEL = OUT / "excursion_panel.parquet"

FULL = ("top_2_5", "armed")
ANNEX = ("top_10", "top_5", "top_1")
ALL_POPS = ("top_10", "top_5", "top_2_5", "top_1", "armed")

CTS = "CONFIRMED_THEN_STOPPED"
FLIP_W = "FINAL_FLIP_EXIT_WINNER"
FLIP_L = "FINAL_FLIP_EXIT_LOSER"
SESS = "SESSION_EXIT"
OUTCOMES = (CTS, FLIP_L, FLIP_W, SESS)

MFE_BUCKETS = ((0.0, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 2.5), (2.5, 3.0), (3.0, np.inf))
PROFIT_BUCKETS = ((-np.inf, 0.0), (0.0, 0.25), (0.25, 0.50),
                  (0.50, 0.75), (0.75, 1.00), (1.00, np.inf))


def dist(s) -> dict:
    a = np.asarray([v for v in s if v is not None and np.isfinite(v)], dtype=float)
    if a.size == 0:
        return {"n": 0}
    q = lambda p: round(float(np.percentile(a, p)), 4)  # noqa: E731
    return {"n": int(a.size), "mean": round(float(a.mean()), 4), "median": q(50),
            "p10": q(10), "p25": q(25), "p50": q(50), "p75": q(75),
            "p90": q(90), "p95": q(95), "max": round(float(a.max()), 4)}


def _bucket_label(lo, hi):
    return f"{lo:g}-{'inf' if np.isinf(hi) else format(hi, 'g')}"


def _in_bucket(col: str, lo, hi) -> pl.Expr:
    e = pl.col(col) < (hi if np.isfinite(hi) else 1e18)
    if np.isfinite(lo):
        e = e & (pl.col(col) >= lo)
    return e


def slice_pop(panel: pl.DataFrame, pop: str, mode: str) -> pl.DataFrame:
    return panel.filter((pl.col("population") == pop) & (pl.col("path_mode") == mode))


def confirmed(df: pl.DataFrame) -> pl.DataFrame:
    return df.filter(pl.col("confirmed") & pl.col("measurable_post_confirm"))


# ------------------------------------------------------- Phase 1 and 2

def phase1(panel: pl.DataFrame) -> dict:
    out = {"path_mode": "constrained",
           "note": "Trades reaching the confirming flip before the 1 ATR entry "
                   "stop. All figures at the confirming flip BAR CLOSE, in "
                   "ATR frozen at entry.",
           "populations": {}}
    for pop in ALL_POPS:
        c = confirmed(slice_pop(panel, pop, "constrained"))
        entries = slice_pop(panel, pop, "constrained").height
        if c.height == 0:
            out["populations"][pop] = {"entries": entries, "confirmed": 0}
            continue
        r = c["return_at_confirm_atr"]
        out["populations"][pop] = {
            "entries": entries,
            "confirmed": c.height,
            "confirmation_rate": round(c.height / entries, 4) if entries else None,
            "return_at_confirm_atr": dist(r),
            "mfe_to_confirm_atr": dist(c["mfe_to_confirm_atr"]),
            "mae_to_confirm_atr": dist(c["mae_to_confirm_atr"]),
            "giveback_at_confirm_atr": dist(c["giveback_at_confirm_atr"]),
            "seconds_entry_to_confirm": dist(c["seconds_entry_to_confirm"]),
            "pct_positive": round(100 * float((r > 0).mean()), 2),
            "pct_ge_0_25": round(100 * float((r >= 0.25).mean()), 2),
            "pct_ge_0_50": round(100 * float((r >= 0.50).mean()), 2),
            "pct_ge_0_75": round(100 * float((r >= 0.75).mean()), 2),
            "pct_ge_1_00": round(100 * float((r >= 1.00).mean()), 2),
            "pct_below_zero": round(100 * float((r < 0).mean()), 2),
        }
    return out


def phase2(panel: pl.DataFrame) -> dict:
    out = {"path_mode": "constrained", "populations": {}}
    for pop in ALL_POPS:
        c = confirmed(slice_pop(panel, pop, "constrained"))
        if c.height == 0:
            continue
        by_outcome = {}
        for lab in OUTCOMES:
            s = c.filter(pl.col("terminal_label_constrained") == lab)
            if s.height == 0:
                by_outcome[lab] = {"n": 0}
                continue
            by_outcome[lab] = {
                "n": s.height,
                "pct_of_confirmed": round(100 * s.height / c.height, 2),
                "return_at_confirm_atr": dist(s["return_at_confirm_atr"]),
                "mfe_to_confirm_atr": dist(s["mfe_to_confirm_atr"]),
                "mae_to_confirm_atr": dist(s["mae_to_confirm_atr"]),
                "giveback_at_confirm_atr": dist(s["giveback_at_confirm_atr"]),
                "seconds_entry_to_confirm": dist(s["seconds_entry_to_confirm"]),
                "eventual_mfe_atr": dist(s["eventual_mfe_atr"]),
            }
        by_mfe = {}
        for lo, hi in MFE_BUCKETS:
            s = c.filter(_in_bucket("eventual_mfe_atr", lo, hi))
            by_mfe[_bucket_label(lo, hi)] = {
                "n": s.height,
                "pct_of_confirmed": round(100 * s.height / c.height, 2),
                "return_at_confirm_atr": dist(s["return_at_confirm_atr"]) if s.height else {"n": 0},
                "outcome_mix": {
                    lab: int((s["terminal_label_constrained"] == lab).sum())
                    for lab in OUTCOMES
                } if s.height else {},
            }
        out["populations"][pop] = {"confirmed": c.height,
                                   "by_outcome": by_outcome,
                                   "by_eventual_mfe_bucket": by_mfe}
    return out


# ------------------------------------------------------- Phase 3 and 4

def phase3(panel: pl.DataFrame) -> dict:
    out = {"path_mode": "unconstrained",
           "note": "t=0 at the confirming flip bar close. Landmarks are "
                   "ENTRY-relative ATR levels, counted only on first achievement "
                   "STRICTLY AFTER confirmation; landmarks already held at the "
                   "flip are excluded and counted separately. Methods A and B "
                   "answer different questions and are never conflated.",
           "populations": {}}
    for pop in FULL:
        c = confirmed(slice_pop(panel, pop, "unconstrained"))
        if c.height == 0:
            continue
        rows = []
        for L in LANDMARKS:
            t = _tag(L)
            reached = c.filter(pl.col(f"lm{t}_reached_after_confirm"))
            rows.append({
                "landmark_atr": L,
                "n_reached_after_confirm": reached.height,
                "n_already_held_at_confirm": int(c[f"lm{t}_already_at_confirm"].sum()),
                "n_ambiguous_with_stop": int(
                    c[f"lm{t}_ambiguous_with_stop"].fill_null(False).sum()),
                "pct_of_confirmed_reaching": round(100 * reached.height / c.height, 2),
                "A_adverse_from_confirm_atr": dist(
                    reached[f"lm{t}_adverse_from_confirm_atr"]) if reached.height else {"n": 0},
                "B_giveback_from_extreme_atr": dist(
                    reached[f"lm{t}_giveback_from_extreme_atr"]) if reached.height else {"n": 0},
                "seconds_from_confirm": dist(
                    reached[f"lm{t}_seconds_from_confirm"]) if reached.height else {"n": 0},
            })
        out["populations"][pop] = {"confirmed": c.height, "landmarks": rows}
    return out


def _pre_landmark_adverse(c: pl.DataFrame, X: float) -> pl.Series:
    """Adverse-from-confirm standing when the trade FIRST reached +X ATR.

    This is the quantity the brief actually asks for: deterioration suffered
    *before* the favorable development, i.e. how much room the runner needed to
    get there. A whole-path maximum is the wrong measure for a runner -- it also
    counts the giveback that happens AFTER the runner has already developed,
    which no entry-time risk boundary could have been damaged by.

    A landmark already held at confirmation required no post-confirmation room at
    all, so it contributes 0.
    """
    t = _tag(X)
    return (
        pl.when(pl.col(f"lm{t}_already_at_confirm")).then(pl.lit(0.0))
        .otherwise(pl.col(f"lm{t}_adverse_from_confirm_atr"))
    )


def phase4(panel: pl.DataFrame) -> dict:
    """Inverted: who touches each deterioration level, by eventual outcome.

    Losers and runners are measured with deliberately different clocks, because
    the question differs. A loser never develops, so its whole post-confirmation
    path is fair game. A runner must be judged on what it suffered *before*
    reaching its MFE threshold -- that is the only deterioration a risk boundary
    placed at confirmation could have cut it off at.
    """
    out = {"path_mode": "unconstrained",
           "note": "Separability map, NOT a stop backtest. Losers: touched at any "
                   "point post-confirmation. Runners: touched BEFORE first "
                   "reaching their MFE threshold (0 if already held at the flip). "
                   "Method A is measured from the confirmation close; Method B "
                   "from the running favorable extreme.",
           "populations": {}}
    for pop in FULL:
        c = confirmed(slice_pop(panel, pop, "unconstrained"))
        if c.height == 0:
            continue
        losers = c.filter(pl.col("terminal_label_constrained").is_in([CTS, FLIP_L]))
        winners = c.filter(pl.col("terminal_label_constrained") == FLIP_W)
        runners = {X: c.filter(pl.col("eventual_mfe_atr") >= X) for X in (2.0, 2.5, 3.0)}

        rows = []
        for D in DETERIORATION:
            row = {"deterioration_atr": D}
            for gname, g in (("all_confirmed", c), ("eventual_losers", losers),
                             ("flip_exit_winners", winners)):
                if g.height == 0:
                    row[gname] = {"n": 0}
                    continue
                row[gname] = {
                    "n": g.height,
                    "pct_touched_A_whole_path": round(
                        100 * float((g["max_adverse_from_confirm_atr"] >= D).mean()), 2),
                    "pct_touched_B_whole_path": round(
                        100 * float((g["max_giveback_from_extreme_atr"] >= D).mean()), 2),
                }
            for X, g in runners.items():
                key = f"runners_ge_{format(X, 'g').replace('.', '_')}atr"
                if g.height == 0:
                    row[key] = {"n": 0}
                    continue
                pre = g.with_columns(pre=_pre_landmark_adverse(g, X))
                # A runner with no recorded pre-landmark figure never reached the
                # landmark after confirmation and was not already holding it --
                # excluded rather than assumed.
                valid = pre.filter(pl.col("pre").is_not_null())
                row[key] = {
                    "n": g.height,
                    "n_with_pre_landmark_measure": valid.height,
                    "pct_touched_before_developing": round(
                        100 * float((valid["pre"] >= D).mean()), 2) if valid.height else None,
                    "pct_touched_A_whole_path": round(
                        100 * float((g["max_adverse_from_confirm_atr"] >= D).mean()), 2),
                }
            rows.append(row)
        out["populations"][pop] = {
            "confirmed": c.height,
            "group_sizes": {"eventual_losers": losers.height,
                            "flip_exit_winners": winners.height,
                            **{f"runners_ge_{format(X, 'g').replace('.', '_')}atr": g.height
                               for X, g in runners.items()}},
            "levels": rows,
        }
    return out


# ----------------------------------------------------- Phase 5, 6 and 7

def phase5(panel: pl.DataFrame) -> dict:
    out = {"path_mode": "unconstrained (excursions); constrained labels for outcomes",
           "populations": {}}
    for pop in FULL:
        c = confirmed(slice_pop(panel, pop, "unconstrained"))
        if c.height == 0:
            continue
        buckets = {}
        for lo, hi in PROFIT_BUCKETS:
            s = c.filter(_in_bucket("return_at_confirm_atr", lo, hi))
            if s.height == 0:
                buckets[_bucket_label(lo, hi)] = {"n": 0}
                continue
            lab = s["terminal_label_constrained"]
            e = s["eventual_mfe_atr"]
            buckets[_bucket_label(lo, hi)] = {
                "n": s.height,
                "pct_of_confirmed": round(100 * s.height / c.height, 2),
                "p_stopped": round(float((lab == CTS).mean()), 4),
                "p_flip_exit_loser": round(float((lab == FLIP_L).mean()), 4),
                "p_flip_exit_winner": round(float((lab == FLIP_W).mean()), 4),
                "p_session_exit": round(float((lab == SESS).mean()), 4),
                "p_mfe_ge_1_5": round(float((e >= 1.5).mean()), 4),
                "p_mfe_ge_2_0": round(float((e >= 2.0).mean()), 4),
                "p_mfe_ge_2_5": round(float((e >= 2.5).mean()), 4),
                "p_mfe_ge_3_0": round(float((e >= 3.0).mean()), 4),
                "A_max_adverse_from_confirm_atr": dist(s["max_adverse_from_confirm_atr"]),
                "B_max_giveback_from_extreme_atr": dist(s["max_giveback_from_extreme_atr"]),
            }
        out["populations"][pop] = {"confirmed": c.height, "profit_buckets": buckets}
    return out


def phase6(panel: pl.DataFrame) -> dict:
    out = {"path_mode": "unconstrained",
           "note": "Feasibility map, NOT a policy. A floor is evaluated only "
                   "where it sits BELOW the open profit at confirmation and "
                   "could therefore actually be placed. Floors trigger on the "
                   "bar's intrabar extreme, matching the 1 ATR stop.",
           "populations": {}}
    for pop in FULL:
        c = confirmed(slice_pop(panel, pop, "unconstrained"))
        if c.height == 0:
            continue
        groups = {
            "confirmed_failures": c.filter(
                pl.col("terminal_label_constrained").is_in([CTS, FLIP_L])),
            "flip_exit_losers": c.filter(pl.col("terminal_label_constrained") == FLIP_L),
            "flip_exit_winners": c.filter(pl.col("terminal_label_constrained") == FLIP_W),
            "runners_ge_2atr": c.filter(pl.col("eventual_mfe_atr") >= 2.0),
            "runners_ge_2_5atr": c.filter(pl.col("eventual_mfe_atr") >= 2.5),
            "runners_ge_3atr": c.filter(pl.col("eventual_mfe_atr") >= 3.0),
        }
        rows = []
        for F in FLOORS:
            t = _tag(F)
            row = {"floor_entry_relative_atr": F,
                   "n_placeable_of_confirmed": int(c[f"floor{t}_placeable"].sum()),
                   "pct_placeable": round(
                       100 * float(c[f"floor{t}_placeable"].mean()), 2),
                   "n_ambiguous_with_landmark": int(
                       c[f"floor{t}_ambiguous_with_landmark"].fill_null(False).sum())}
            for gname, g in groups.items():
                p = g.filter(pl.col(f"floor{t}_placeable"))
                if p.height == 0:
                    row[gname] = {"n_placeable": 0}
                    continue
                touched = int(p[f"floor{t}_touched"].fill_null(False).sum())
                row[gname] = {
                    "n_placeable": p.height,
                    "n_touched": touched,
                    "pct_touched": round(100 * touched / p.height, 2),
                }
            rows.append(row)
        out["populations"][pop] = {"confirmed": c.height, "floors": rows}
    return out


def phase7(panel: pl.DataFrame) -> dict:
    out = {"path_mode": "unconstrained",
           "note": "The clock resets at the FIRST causal achievement of each "
                   "landmark, including landmarks already held at the flip.",
           "populations": {}}
    for pop in FULL:
        c = confirmed(slice_pop(panel, pop, "unconstrained"))
        if c.height == 0:
            continue
        rows = []
        for a, b in zip(TRANSITION_LANDMARKS, TRANSITION_LANDMARKS[1:]):
            key = f"trans_{_tag(a)}_to_{_tag(b)}"
            elig = c.filter(pl.col(f"{key}_eligible").fill_null(False))
            if elig.height == 0:
                rows.append({"from_atr": a, "to_atr": b, "n_eligible": 0})
                continue
            ok = elig.filter(pl.col(f"{key}_reached").fill_null(False))
            no = elig.filter(~pl.col(f"{key}_reached").fill_null(False))
            rows.append({
                "from_atr": a, "to_atr": b,
                "n_eligible": elig.height,
                "n_reached_next": ok.height,
                "p_transition": round(ok.height / elig.height, 4),
                "giveback_atr_successful": dist(ok[f"{key}_giveback_atr"]) if ok.height else {"n": 0},
                "giveback_atr_failed": dist(no[f"{key}_giveback_atr"]) if no.height else {"n": 0},
                "seconds_to_next": dist(ok[f"{key}_seconds"]) if ok.height else {"n": 0},
                "additional_mfe_atr": dist(elig[f"{key}_additional_mfe_atr"]),
            })
        out["populations"][pop] = {"confirmed": c.height, "transitions": rows}
    return out


# ----------------------------------------------------------- Phase 8

def phase8(panel: pl.DataFrame) -> dict:
    """Exit efficiency, and the expectancy arithmetic over ALL entries."""
    out = {"path_mode": "constrained",
           "note": "Capture is realized flip-exit return / max MFE. Trades whose "
                   "max MFE is below 0.10 ATR are reported separately rather "
                   "than divided through -- the ratio is meaningless there.",
           "populations": {}}
    for pop in ALL_POPS:
        d = slice_pop(panel, pop, "constrained")
        entries = d.height
        f = d.filter(pl.col("reached_opposing_flip").fill_null(False)
                     & pl.col("max_mfe_atr").is_not_null())
        if f.height == 0:
            continue
        tiny = f.filter(pl.col("max_mfe_atr") < 0.10)
        ok = f.filter(pl.col("max_mfe_atr") >= 0.10).with_columns(
            capture=(pl.col("flip_exit_return_atr") / pl.col("max_mfe_atr")))

        def block(s):
            if s.height == 0:
                return {"n": 0}
            return {"n": s.height,
                    "capture_ratio": dist(s["capture"]),
                    "giveback_atr": dist(s["flip_exit_giveback_atr"]),
                    "max_mfe_atr": dist(s["max_mfe_atr"]),
                    "flip_exit_return_atr": dist(s["flip_exit_return_atr"])}

        by_outcome = {lab: block(ok.filter(pl.col("terminal_label_constrained") == lab))
                      for lab in (FLIP_W, FLIP_L)}
        by_mfe = {_bucket_label(lo, hi): block(ok.filter(_in_bucket("max_mfe_atr", lo, hi)))
                  for lo, hi in MFE_BUCKETS}

        # --- expectancy arithmetic, denominator = ALL entries (SPEC 4 Phase 8)
        total_gross = float(d["constrained_gross_atr"].fill_null(0.0).sum())
        total_net = float(d["constrained_net_atr"].fill_null(0.0).sum())
        recoverable = float(ok["flip_exit_giveback_atr"].sum())
        targets = {}
        for lift in (0.05, 0.10, 0.15, 0.25):
            need = lift * entries
            targets[f"+{lift:.2f}_atr_per_trade"] = {
                "total_atr_needed": round(need, 2),
                "pct_of_recoverable_giveback": (
                    round(100 * need / recoverable, 2) if recoverable > 0 else None),
                "achievable": bool(recoverable > 0 and need <= recoverable),
            }
        out["populations"][pop] = {
            "entries_all": entries,
            "confirmed": int(d["confirmed"].fill_null(False).sum()),
            "flip_exit_trades": f.height,
            "flip_exit_share_of_entries": round(f.height / entries, 4),
            "excluded_tiny_mfe": tiny.height,
            "pooled": block(ok),
            "by_outcome": by_outcome,
            "by_max_mfe_bucket": by_mfe,
            "expectancy": {
                "gross_atr_per_entry": round(total_gross / entries, 4),
                "net_atr_per_entry": round(total_net / entries, 4),
                "gross_atr_per_confirmed": round(
                    total_gross / max(int(d["confirmed"].fill_null(False).sum()), 1), 4),
                "gross_atr_per_flip_exit": round(total_gross / max(f.height, 1), 4),
                "total_recoverable_giveback_atr": round(recoverable, 2),
                "recoverable_giveback_per_entry_atr": round(recoverable / entries, 4),
                "targets": targets,
                "note": "Denominator for the headline is ALL entries, including "
                        "those stopped before confirmation -- the only figure "
                        "comparable to the strategy's real expectancy. A better "
                        "runner exit can only reach the flip_exit_share_of_entries "
                        "fraction of the book.",
            },
        }
    return out


def main() -> None:
    panel = pl.read_parquet(PANEL)
    print(f"panel {panel.height:,} rows", flush=True)
    for name, fn in (("confirmation_economics", phase1),
                     ("confirmation_outcome_breakdown", phase2),
                     ("post_confirmation_excursion_map", phase3),
                     ("runner_survival_curve", phase4),
                     ("confirmation_profit_conditioning", phase5),
                     ("profit_floor_feasibility", phase6),
                     ("runner_landmark_transitions", phase7),
                     ("regime_flip_exit_capture_efficiency", phase8)):
        (OUT / f"{name}.json").write_text(json.dumps(fn(panel), indent=2, default=str))
        print(f"  wrote results/{name}.json", flush=True)


if __name__ == "__main__":
    main()
