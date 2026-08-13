"""Phase 12: the conditional policy screen.

Runs ONLY because the SPEC 8 separation gate opened on the `undetermined`
population. Four policies, no grid, no threshold search.

Every threshold is read off a broad descriptive plateau documented in REPORT.md:

* the Phase 9 matrix shows PROGRESS dominates and DRAWDOWN is nearly irrelevant
  -- at +120 s the low-progress cell (n=792) has median additional MFE of exactly
  0.000 and mean natural return -0.194 ATR, while every high-progress cell earns
  ~+1.6 ATR at ANY drawdown. So the leading family is "cut the non-starters",
  and the threshold is the natural zero (`ret_from_entry <= 0`), not a tuned
  quantile.
* policies 3 and 4 are the brief's own two worked examples, included precisely
  because they represent the giveback/stall family the descriptive tables argue
  AGAINST. They are the control on the study's own conclusion.

Two invariants, both inherited and non-negotiable:

* the 1.00 ATR initial stop is LIVE in every policy; a policy may only exit
  EARLIER than the natural terminal, never later, never past the stop;
* every policy is matched against a COUNT-MATCHED RANDOM-EXIT PLACEBO. This
  research line has twice mistaken "exiting earlier than a bad exit" for an edge
  (see memory: early_exit_rules_need_a_matched_placebo). A policy that does not
  beat its own placebo is not a finding.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    COST_POINTS, NS, load_market, load_regimes,
)
from ..implementation.build import confirmed_population
from ..implementation.engine import RUNNER_TIERS, Window, prepare

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "studies/top10_fast_confirm_runner_path/results"
ARMED = ROOT / "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet"
SEED = 20260810
N_PLACEBO = 20                      # placebo repetitions, averaged

POLICIES = ("P1_PROG120_LE0", "P2_PROG60_LE0", "P3_STALL60_DD050",
            "P4_MFE15_DD050_STALL45")


def _tag(x: float) -> str:
    return str(x).replace(".", "_")


def _first(mask: np.ndarray) -> int:
    hit = np.flatnonzero(mask)
    return int(hit[0]) if hit.size else -1


# --------------------------------------------------------------- triggers

def trig_progress(w: Window, seconds: int) -> int:
    """At +`seconds` after confirmation, exit if the trade is not in profit."""
    j = w.index_at_offset(seconds)
    if j < 0 or j > w.unc_i:
        return -1
    return j if w.mark[j] <= 0.0 else -1


def trig_stall_dd(w: Window, stall_s: int, dd_atr: float,
                  mfe_floor: float | None = None) -> int:
    """First bar where the trade has stalled `stall_s` AND given back `dd_atr`.

    The stall clock runs from a genuine post-confirmation new favorable extreme
    (never from the confirmation bar itself -- that credits a trade with a stall
    it never earned), and the giveback is measured from the running MaxMFE.
    """
    seg = slice(w.ci, w.unc_i + 1)
    last = w.last_ext[seg]
    armed = last >= w.ci
    since = (w.ts[seg] - w.ts[np.maximum(last, 0)]) / NS
    ext = np.maximum.accumulate(w.run_mfe[seg])
    dd = ext - w.mark[seg]
    cond = armed & (since >= stall_s) & (dd >= dd_atr)
    if mfe_floor is not None:
        cond &= ext >= mfe_floor
    h = _first(cond)
    return w.ci + h if h >= 0 else -1


def evaluate(w: Window, rng: np.random.Generator) -> dict:
    """Baseline, four policies, and a count-matched placebo for each."""
    base = w.realise(w.nat_i, w.nat_fill_next)
    max_mfe_unc = float(w.run_mfe[w.unc_i])
    max_mfe_nat = float(w.run_mfe[w.nat_i])
    out = {
        "baseline_return_atr": base,
        "baseline_net_atr": base - COST_POINTS / w.atr,
        "eventual_max_mfe_atr": max_mfe_unc,
        "natural_max_mfe_atr": max_mfe_nat,
        "baseline_giveback_atr": max_mfe_nat - base,
        "natural_kind": w.nat_kind,
    }
    # first causal index at which each runner tier is touched
    tier_idx = {T: _first(w.bar_hi >= T) for T in RUNNER_TIERS}

    trigs = {
        "P1_PROG120_LE0": trig_progress(w, 120),
        "P2_PROG60_LE0": trig_progress(w, 60),
        "P3_STALL60_DD050": trig_stall_dd(w, 60, 0.50),
        "P4_MFE15_DD050_STALL45": trig_stall_dd(w, 45, 0.50, mfe_floor=1.5),
    }
    for name, ti in trigs.items():
        acted = ti >= 0 and ti < w.nat_i
        i = ti if acted else w.nat_i
        fn = True if acted else w.nat_fill_next
        r = w.realise(i, fn)
        out[f"{name}_return_atr"] = r
        out[f"{name}_net_atr"] = r - COST_POINTS / w.atr
        out[f"{name}_acted"] = bool(acted)
        out[f"{name}_delta_atr"] = r - base
        out[f"{name}_exit_idx"] = i
        for T in RUNNER_TIERS:
            if max_mfe_nat >= T:
                li = tier_idx[T]
                out[f"{name}_cut_before_{_tag(T)}"] = bool(li >= 0 and i < li)

        # count-matched placebo: same act/no-act decision, exit bar drawn
        # uniformly from the post-confirmation window of THIS trade.
        if acted:
            draws = rng.integers(w.ci, w.nat_i, size=N_PLACEBO) if w.nat_i > w.ci \
                else np.full(N_PLACEBO, w.ci)
            vals = [w.realise(int(k), True) for k in draws]
            out[f"{name}_placebo_return_atr"] = float(np.mean(vals))
            cuts = {T: 0 for T in RUNNER_TIERS}
            for k in draws:
                for T in RUNNER_TIERS:
                    if max_mfe_nat >= T and tier_idx[T] >= 0 and int(k) < tier_idx[T]:
                        cuts[T] += 1
            for T in RUNNER_TIERS:
                if max_mfe_nat >= T:
                    out[f"{name}_placebo_cut_before_{_tag(T)}"] = cuts[T] / N_PLACEBO
        else:
            out[f"{name}_placebo_return_atr"] = base
            for T in RUNNER_TIERS:
                if max_mfe_nat >= T:
                    out[f"{name}_placebo_cut_before_{_tag(T)}"] = 0.0
    return out


# ---------------------------------------------------------------- reporting

def summarise(d: pl.DataFrame, n_entries: int, pool_per_entry: float) -> pl.DataFrame:
    n_fast = d.height
    losers = d.filter(pl.col("baseline_net_atr") < 0)
    rows = []
    for name in POLICIES:
        delta = d[f"{name}_delta_atr"]
        pl_delta = d[f"{name}_placebo_return_atr"] - d["baseline_return_atr"]
        imp = losers.filter(pl.col(f"{name}_net_atr") > pl.col("baseline_net_atr"))
        r = {
            "policy": name,
            "n_fast": n_fast,
            "coverage_pct": 100.0 * float(d[f"{name}_acted"].mean()),
            "delta_atr_per_fast_trade": float(delta.mean()),
            "delta_atr_per_original_entry": float(delta.sum()) / n_entries,
            "placebo_delta_atr_per_fast_trade": float(pl_delta.mean()),
            "beats_placebo": bool(delta.mean() > pl_delta.mean()),
            "edge_over_placebo_per_fast_trade": float(delta.mean() - pl_delta.mean()),
            "giveback_recovered_pct": 100.0 * float(delta.sum()) / (
                pool_per_entry * n_entries),
            "confirmed_losers_n": losers.height,
            "confirmed_losers_improved_pct": 100.0 * imp.height / max(losers.height, 1),
            "mean_net_atr": float(d[f"{name}_net_atr"].mean()),
            "baseline_mean_net_atr": float(d["baseline_net_atr"].mean()),
        }
        for T in RUNNER_TIERS:
            col = f"{name}_cut_before_{_tag(T)}"
            s = d.filter(pl.col(col).is_not_null())
            r[f"n_runners_ge_{_tag(T)}"] = s.height
            r[f"preserved_ge_{_tag(T)}_pct"] = (
                100.0 * (1.0 - float(s[col].mean())) if s.height else None)
        rows.append(r)
    # baseline row
    rows.append({"policy": "BASELINE", "n_fast": n_fast, "coverage_pct": 0.0,
                 "delta_atr_per_fast_trade": 0.0,
                 "delta_atr_per_original_entry": 0.0,
                 "mean_net_atr": float(d["baseline_net_atr"].mean()),
                 "baseline_mean_net_atr": float(d["baseline_net_atr"].mean()),
                 "giveback_recovered_pct": 0.0,
                 **{f"preserved_ge_{_tag(T)}_pct": 100.0 for T in RUNNER_TIERS}})
    return pl.DataFrame(rows, infer_schema_length=None)


def runner_destruction(d: pl.DataFrame) -> pl.DataFrame:
    """MANDATORY. A rule that improves losers by destroying the tail does not advance."""
    rows = []
    for name in POLICIES:
        for T in RUNNER_TIERS:
            col = f"{name}_cut_before_{_tag(T)}"
            if col not in d.columns:
                continue
            s = d.filter(pl.col(col).is_not_null())
            cut = s.filter(pl.col(col))
            rows.append({
                "policy": name, "tier_atr": T, "n_runners": s.height,
                "n_cut": cut.height,
                "pct_cut": 100.0 * cut.height / max(s.height, 1),
                "placebo_pct_cut": 100.0 * float(
                    s[f"{name}_placebo_cut_before_{_tag(T)}"].mean()),
                "median_policy_exit_atr": (float(cut[f"{name}_return_atr"].median())
                                           if cut.height else None),
                "median_eventual_max_mfe_atr": (
                    float(cut["eventual_max_mfe_atr"].median()) if cut.height else None),
                "opportunity_cost_atr": (
                    float((cut["baseline_return_atr"] - cut[f"{name}_return_atr"]).sum())
                    if cut.height else 0.0),
            })
    return pl.DataFrame(rows, infer_schema_length=None)


def stability(d: pl.DataFrame, n_entries: int) -> pl.DataFrame:
    rows = []
    for name in POLICIES:
        for key, vals in (("year", range(2021, 2026)), ("side", ("LONG", "SHORT"))):
            for v in vals:
                s = d.filter(pl.col("entry_year" if key == "year" else "side") == v)
                if s.height == 0:
                    continue
                rows.append({
                    "policy": name, "slice_kind": key, "slice": str(v), "n": s.height,
                    "delta_atr_per_fast_trade": float(s[f"{name}_delta_atr"].mean()),
                    "delta_atr_total": float(s[f"{name}_delta_atr"].sum()),
                    "positive": bool(s[f"{name}_delta_atr"].mean() > 0),
                })
    return pl.DataFrame(rows)


def main() -> None:
    summary = json.loads((OUT / "summary.json").read_text())
    if not summary["separation_gate"]["open"]:
        print("separation gate CLOSED -- Phase 12 does not run")
        return

    market, regimes = load_market(), load_regimes()
    conf = confirmed_population()
    panel = pl.read_parquet(OUT / "trade_panel.parquet")
    fast_ids = set(panel.filter(pl.col("is_fast_confirm"))["regime_id"].to_list())
    rng = np.random.default_rng(SEED)

    rows = []
    for r in conf.iter_rows(named=True):
        if r["regime_id"] not in fast_ids:
            continue
        w = prepare(market, regimes, r)
        if w is None:
            continue
        rows.append({"regime_id": r["regime_id"], "entry_year": r["entry_year"],
                     "side": r["side"], **evaluate(w, rng)})
    d = pl.DataFrame(rows, infer_schema_length=None)
    d.write_parquet(OUT / "policy_panel.parquet")

    n_entries = pl.read_parquet(ARMED).filter(pl.col("valid")).height
    pool = float(pl.read_parquet(OUT / "population_reconciliation.parquet")
                 .filter(pl.col("quantity") == "giveback_pool_per_entry")["observed"][0])

    res = summarise(d, n_entries, pool)
    rd = runner_destruction(d)
    st = stability(d, n_entries)
    for name, df in (("policy_results", res), ("runner_destruction", rd),
                     ("policy_stability", st)):
        df.write_parquet(OUT / f"{name}.parquet")
        df.write_csv(OUT / f"{name}.csv")
        print(f"  {name}: {df.height} rows")

    best = res.filter(pl.col("policy") != "BASELINE").sort(
        "delta_atr_per_original_entry", descending=True)
    summary["phase12_ran"] = True
    summary["phase12"] = {
        "policies": list(POLICIES),
        "n_fast": d.height,
        "placebo_repetitions": N_PLACEBO,
        "seed": SEED,
        "results": best.select(
            "policy", "coverage_pct", "delta_atr_per_fast_trade",
            "delta_atr_per_original_entry", "placebo_delta_atr_per_fast_trade",
            "beats_placebo", "edge_over_placebo_per_fast_trade",
            "giveback_recovered_pct", "confirmed_losers_improved_pct",
            *[f"preserved_ge_{_tag(T)}_pct" for T in RUNNER_TIERS]).to_dicts(),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary["phase12"]["results"], indent=2, default=str))


if __name__ == "__main__":
    main()
