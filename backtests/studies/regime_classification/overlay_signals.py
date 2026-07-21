"""Phase 4 — overlay signal cohorts on regime states.

For each (model, k) in {hmm, gmm, kmeans} × {3,4,5,6}:
  For each cohort in {raw_nt, bar1_confirm, launchpad, pullback_resume}:
    Compute state at decision-time (state of just-closed 1m bar).
    For each state, compute:
      - pooled OOS n, win rate, lift vs cohort baseline
      - per-OOS-year n, win rate, sign of lift
    Filter survivors:
      - pooled OOS n >= 200
      - per-OOS-year n >= 30 in at least 3 of 4 years
      - |pooled OOS lift| >= 3pp
      - lift has same sign in at least 3 of 4 OOS years
    Surface only those.

Headline interpretation models: kmeans_4 and hmm_4 (always reported,
even when filters not passed, for context).
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

PRODUCT = os.environ.get("PRODUCT", "NQ").upper()
NS = 1_000_000_000
OUT = Path("studies/regime_classification/results")
IS_YEARS = (2020, 2021, 2022)
OOS_YEARS = (2023, 2024, 2025, 2026)

# Filter thresholds
MIN_POOLED_OOS_N = 200
MIN_PER_YEAR_N = 30
MIN_YEARS_PASSING_N = 3
MIN_LIFT_PP = 3.0
MIN_YEARS_SAME_SIGN = 3

STATE_COLS = [f"{m}_{k}" for k in (3, 4, 5, 6)
              for m in ("hmm", "gmm", "kmeans")]


def load_cohort_raw_nt():
    parts = []
    for y in range(2020, 2027):
        p = Path(f"backtests/baseline_flip_parity/results/"
                 f"nq_live_{y}/trades.parquet")
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        d["year"] = y
        d["win"] = (d["exit_reason"] == "T").astype(int)
        d["resolved"] = d["exit_reason"].isin(["T", "SL"])
        parts.append(d[["entry_ts", "signal_direction", "year",
                         "win", "resolved"]])
    return pd.concat(parts, ignore_index=True)


def load_cohort_bar1_confirm():
    p = Path("studies/v_a_excursion_regime/results_v0/"
              "nt_regime_exit_nq.parquet")
    d = pd.read_parquet(p)
    d = d[d["bar1_confirm"]].copy()
    # Look up the NT exit_reason via merge with raw_nt
    raw = load_cohort_raw_nt()
    raw["entry_ts"] = raw["entry_ts"].astype(np.int64)
    d["entry_ts"] = d["entry_ts"].astype(np.int64)
    m = d[["entry_ts", "signal_direction", "year"]].merge(
        raw[["entry_ts", "signal_direction", "win", "resolved"]],
        on=["entry_ts", "signal_direction"], how="inner")
    return m


def load_cohort_launchpad():
    parts = []
    for y in range(2020, 2027):
        p = Path(f"backtests/compression_vwap_launchpad/results/"
                 f"live_{y}/trades.parquet")
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        if len(d) == 0:
            continue
        d["year"] = y
        # launchpad is long-only; t1_filled = +1 ATR touched.
        # Treat t1_filled as "win" (closest analog to +1/-1 first-touch)
        d["win"] = d["t1_filled"].astype(int)
        d["resolved"] = ~d["exit_reason"].eq("max_hold")
        d["signal_direction"] = 1  # long-only by construction
        parts.append(d[["entry_ts", "signal_direction", "year",
                         "win", "resolved"]])
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def load_cohort_pullback_resume():
    p = Path("studies/v_a_excursion_regime/results_v0/"
              "nt_5s_pullback_resume_nq.parquet")
    d = pd.read_parquet(p)
    d = d[d["pb_found"]].copy()
    d["win"] = (d["bracket_hit"] == 1).astype(int)
    d["resolved"] = d["bracket_hit"] >= 0
    # Drop the original 1m flip ts; the state-lookup key for pullback-resume
    # is pb_entry_ts (the 5s resume moment).
    if "entry_ts" in d.columns:
        d = d.drop(columns=["entry_ts"])
    d = d.rename(columns={"pb_entry_ts": "entry_ts"})
    return d[["entry_ts", "signal_direction", "year", "win", "resolved"]].copy()


def lookup_state(entry_ts_ns_arr, state_ts_ns_arr, state_arr,
                  exact_decision=True):
    """For each entry_ts, return state of the most-recently-completed 1m bar.

    exact_decision=True: entry_ts is at a 1m boundary (decision = 1m close).
        The just-closed bar opens at entry_ts - 60s. EXACT match expected.
    exact_decision=False: entry_ts is mid-bar (e.g. 5s pullback resume).
        Use last bar whose CLOSE (= open + 60s) is <= entry_ts.
    """
    entry_ts_ns_arr = np.asarray(entry_ts_ns_arr).flatten().astype(np.int64)
    state_ts_ns_arr = np.asarray(state_ts_ns_arr).flatten().astype(np.int64)
    state_arr = np.asarray(state_arr).flatten().astype(np.int64)
    out = np.full(len(entry_ts_ns_arr), -1, dtype=np.int64)
    if exact_decision:
        targets = entry_ts_ns_arr - 60 * NS
        i = np.searchsorted(state_ts_ns_arr, targets, side="left")
        valid = (i < len(state_ts_ns_arr)) & \
                 (state_ts_ns_arr[np.clip(i, 0, len(state_ts_ns_arr)-1)] == targets)
        i_v = i[valid]
        out[valid] = np.take(state_arr, i_v)
    else:
        targets = entry_ts_ns_arr - 60 * NS
        i = np.searchsorted(state_ts_ns_arr, targets, side="right") - 1
        valid = i >= 0
        i_v = i[valid]
        out[valid] = np.take(state_arr, i_v)
    return out


def assess_cohort_states(cohort_df, state_ts_ns, state_col_values, label,
                          exact_decision=True):
    """For one cohort × one state column, return per-state OOS lift summary."""
    cohort_df = cohort_df.copy()
    states = lookup_state(cohort_df["entry_ts"].astype(np.int64).to_numpy(),
                           state_ts_ns, state_col_values,
                           exact_decision=exact_decision)
    cohort_df["state"] = states
    # Only resolved rows count (T or SL)
    res = cohort_df[cohort_df["resolved"] & (cohort_df["state"] >= 0)]
    oos = res[res["year"].isin(OOS_YEARS)]
    base_oos = oos["win"].mean() if len(oos) else float("nan")

    rows = []
    for st in sorted(res["state"].unique()):
        sub_oos = oos[oos["state"] == st]
        if len(sub_oos) == 0:
            continue
        n_pool = len(sub_oos)
        win_pool = sub_oos["win"].mean()
        lift_pool_pp = (win_pool - base_oos) * 100
        # Per-OOS-year
        per_year = []
        for y in OOS_YEARS:
            g = sub_oos[sub_oos["year"] == y]
            base_y = oos[oos["year"] == y]["win"].mean()
            if len(g) >= 1:
                per_year.append((y, len(g), g["win"].mean(),
                                  (g["win"].mean() - base_y) * 100))
        rows.append({
            "label": label,
            "state": st,
            "n_pool_oos": n_pool,
            "win_pool_oos": win_pool,
            "base_pool_oos": base_oos,
            "lift_pool_pp": lift_pool_pp,
            "per_year": per_year,
        })
    return rows, base_oos


def filter_survivors(rows):
    """Apply user-specified filters."""
    survivors = []
    for r in rows:
        if r["n_pool_oos"] < MIN_POOLED_OOS_N:
            continue
        if abs(r["lift_pool_pp"]) < MIN_LIFT_PP:
            continue
        # Per-year n >= 30 in at least 3 of 4 OOS years
        years_with_n = sum(1 for y, n, w, lp in r["per_year"]
                            if n >= MIN_PER_YEAR_N)
        if years_with_n < MIN_YEARS_PASSING_N:
            continue
        # Same sign of lift in at least 3 of 4 OOS years (among those with n)
        signs = [np.sign(lp) for y, n, w, lp in r["per_year"]
                  if n >= MIN_PER_YEAR_N]
        pos = sum(1 for s in signs if s > 0)
        neg = sum(1 for s in signs if s < 0)
        if max(pos, neg) < MIN_YEARS_SAME_SIGN:
            continue
        survivors.append(r)
    return survivors


def main():
    t0 = time.time()
    print(f"PRODUCT={PRODUCT}")
    print("Loading state classifications ...")
    states = pd.read_parquet(OUT / f"states_{PRODUCT.lower()}_1m.parquet")
    print(f"  state rows: {len(states):,}")
    state_ts_ns = states.index.values.astype(np.int64)

    print("\nLoading cohorts ...")
    cohorts = {
        "raw_nt":           (load_cohort_raw_nt(),         True),
        "bar1_confirm":     (load_cohort_bar1_confirm(),   True),
        "launchpad":        (load_cohort_launchpad(),      True),
        "pullback_resume":  (load_cohort_pullback_resume(), False),
    }
    for nm, (df, ex) in cohorts.items():
        n_oos = (df["year"].isin(OOS_YEARS) & df["resolved"]).sum()
        print(f"  {nm:<18}  n_total={len(df):>7,}  "
              f"n_resolved_OOS={n_oos:>6,}")

    # ── HEADLINE: kmeans_4 and hmm_4 (always reported) ──
    print(f"\n{'='*88}\nHEADLINE MODELS — kmeans_4 + hmm_4 (full report)\n{'='*88}")
    for headline in ("kmeans_4", "hmm_4"):
        print(f"\n──── {headline.upper()} ────")
        for nm, (df, ex) in cohorts.items():
            df_ = df.copy()
            df_["entry_ts"] = df_["entry_ts"].astype(np.int64)
            rows, base = assess_cohort_states(
                df_, state_ts_ns,
                states[headline].to_numpy(np.int64),
                label=f"{headline}/{nm}", exact_decision=ex)
            if not rows or np.isnan(base):
                continue
            print(f"\n  {nm} (OOS base win={base:.1%})")
            print(f"    {'state':<6}{'n_pool':>8}{'win%':>8}{'lift':>9}  "
                  f"per-OOS-year (n, win%, lift)")
            for r in sorted(rows, key=lambda x: -x["n_pool_oos"]):
                yr_str = " ".join(
                    f"{y}:{n}/{w:.0%}/{lp:+.1f}"
                    for y, n, w, lp in r["per_year"])
                print(f"    {r['state']:<6}{r['n_pool_oos']:>8,}"
                      f"{r['win_pool_oos']:>7.1%}"
                      f"{r['lift_pool_pp']:>+8.1f}pp  {yr_str}")

    # ── SURVIVORS: filter pass across ALL 12 models ──
    print(f"\n{'='*88}\nFULL SWEEP — cells passing ALL filters\n{'='*88}")
    print(f"  filters: pooled OOS n >= {MIN_POOLED_OOS_N}, "
          f"|lift| >= {MIN_LIFT_PP}pp, "
          f"per-year n >= {MIN_PER_YEAR_N} in {MIN_YEARS_PASSING_N}+ yrs, "
          f"same sign in {MIN_YEARS_SAME_SIGN}+ yrs")

    all_survivors = []
    for sc in STATE_COLS:
        state_arr = states[sc].to_numpy(np.int64)
        for nm, (df, ex) in cohorts.items():
            df_ = df.copy()
            df_["entry_ts"] = df_["entry_ts"].astype(np.int64)
            rows, base = assess_cohort_states(
                df_, state_ts_ns, state_arr,
                label=f"{sc}/{nm}", exact_decision=ex)
            if np.isnan(base):
                continue
            survivors = filter_survivors(rows)
            for s in survivors:
                s["model_k"] = sc
                s["cohort"] = nm
                s["base_oos"] = base
                all_survivors.append(s)

    if not all_survivors:
        print("\n  NO CELLS PASSED ALL FILTERS.\n")
    else:
        all_survivors.sort(key=lambda x: -abs(x["lift_pool_pp"]))
        print(f"\n  {len(all_survivors)} survivor cells across "
              f"{len(set(s['model_k'] for s in all_survivors))} models, "
              f"{len(set(s['cohort'] for s in all_survivors))} cohorts:\n")
        print(f"  {'model_k':<14}{'cohort':<18}{'state':<7}"
              f"{'n_pool':>8}{'win%':>8}{'base%':>8}{'lift':>9}  "
              f"per-OOS-year")
        for s in all_survivors:
            yr_str = " ".join(
                f"{y}:{n}/{w:.0%}/{lp:+.1f}"
                for y, n, w, lp in s["per_year"])
            print(f"  {s['model_k']:<14}{s['cohort']:<18}{s['state']:<7}"
                  f"{s['n_pool_oos']:>8,}{s['win_pool_oos']:>7.1%}"
                  f"{s['base_oos']:>7.1%}{s['lift_pool_pp']:>+8.1f}pp  "
                  f"{yr_str}")

    # Save survivor frame for further analysis
    if all_survivors:
        out_rows = []
        for s in all_survivors:
            out_rows.append({
                "model_k": s["model_k"], "cohort": s["cohort"],
                "state": s["state"],
                "n_pool_oos": s["n_pool_oos"],
                "win_pool_oos": s["win_pool_oos"],
                "base_oos": s["base_oos"],
                "lift_pool_pp": s["lift_pool_pp"],
                "per_year": str(s["per_year"]),
            })
        pd.DataFrame(out_rows).to_csv(
            OUT / f"overlay_survivors_{PRODUCT.lower()}.csv", index=False)

    print(f"\n[done] {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
