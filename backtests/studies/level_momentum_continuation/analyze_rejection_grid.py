"""Rejection counter-trade grid sweep — full from-scratch
re-simulation with skip-while-open (Option B style).

Strategy per trigger:
  1. Enter original (long or short) at next bar open.
  2. Track MFE. Arm BE if MFE >= BE_THRESHOLD (default 2.5).
  3. While BE not armed, watch for "rejection" trigger: price
     trades REJECTION_TRIGGER pts past breach level in unfavored
     direction. If hit:
       a. Exit original at rejection price
       b. Enter COUNTER-TRADE in opposite direction at same price
       c. Counter-trade has fixed PT/SL (symmetric BRACKET pts)
       d. Counter-trade exits on PT hit / SL hit / EOD only
  4. If BE armed: BE-stop on entry-price retrace.
  5. Original target hit → win.
  6. Original 'one prior in seq' stop hit → loss (only fires if
     rejection didn't fire AND BE armed). Rejection always fires
     before original stop since rejection is tighter.
  7. EOD (16:00 CT) → force flat at that bar's close.

Skip-while-open: entire chain (original + counter) holds the slot.
A new trigger that fires while the chain is open is SKIPPED.

Grid:
  REJECTION_TRIGGERS = [3, 4, 5, 6, 7]    pts past breach
  BRACKETS           = [3, 4, 5, 6, 7]    counter PT/SL (symmetric)
  → 25 combos × 2 years = 50 simulations
"""
from __future__ import annotations

import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from studies.level_momentum_continuation.level_study import (
    load_v0_1s, resample_1s_to_1m, annotate_sessions_ct,
    detect_triggers,
)
from studies.level_momentum_continuation.run_nq_2025 import (
    filter_roll_window,
)


OUT = Path(
    "studies/level_momentum_continuation/results_rejection_grid")
OUT.mkdir(parents=True, exist_ok=True)

REJECTION_TRIGGERS = [3.0, 4.0, 5.0, 6.0, 7.0]
BRACKETS = [3.0, 4.0, 5.0, 6.0, 7.0]
BE_THRESHOLD = 2.5
COMMISSION_PTS = 0.25
NQ_DOLLAR_PER_PT = 20.0
EOD_HOUR_CT = 16


def precompute_eod_indices(bars: pd.DataFrame) -> np.ndarray:
    """For each bar idx, return the idx of the next 16:00 CT bar
    (or last bar of data) — the EOD-flat target."""
    ts_ct = bars["ts_ct"]
    is_eod = (ts_ct.dt.hour == EOD_HOUR_CT) & (
        ts_ct.dt.minute == 0)
    eod_indices = np.where(is_eod.values)[0]
    n = len(bars)
    next_eod = np.full(n, n - 1, dtype=int)  # default = last bar
    j = 0
    for i in range(n):
        while j < len(eod_indices) and eod_indices[j] < i:
            j += 1
        if j < len(eod_indices):
            next_eod[i] = eod_indices[j]
    return next_eod


def simulate_chain(t, bars_arrays, rejection_trigger,
                       bracket, be_threshold, next_eod):
    """Simulate full strategy chain (original + maybe counter).
    bars_arrays: dict of numpy arrays {opens, highs, lows, closes, n}
    Returns dict with chain outcome and exit_idx.
    """
    n = bars_arrays["n"]
    opens = bars_arrays["opens"]
    highs = bars_arrays["highs"]
    lows = bars_arrays["lows"]
    closes = bars_arrays["closes"]

    ent = t.bar_idx + 1
    if ent >= n:
        return None
    di = t.direction
    ep = opens[ent]
    tgt = t.target
    stop = t.stop
    breach = t.breach_level
    rejection_px = (breach - rejection_trigger) if di == 1 else (
        breach + rejection_trigger)

    # EOD bar for this entry
    eod_idx = next_eod[ent]

    armed = False
    mfe_so_far = 0.0
    outcome = None
    exit_px = ep
    exit_idx = ent

    # Walk original trade
    last_orig = min(eod_idx, n - 1)
    counter_fired = False
    counter_outcome = None
    counter_pnl_gross = 0.0
    counter_entry_idx = -1
    counter_exit_idx = -1
    counter_entry_px = 0.0

    for k in range(ent, last_orig + 1):
        h = highs[k]; l = lows[k]
        # 1. BE check
        if armed:
            if di == 1 and l <= ep:
                outcome = "be_stop"; exit_px = ep; exit_idx = k; break
            if di == -1 and h >= ep:
                outcome = "be_stop"; exit_px = ep; exit_idx = k; break
        # 2. Rejection check (if BE not armed)
        if not armed:
            rejection_hit = (
                di == 1 and l <= rejection_px
            ) or (
                di == -1 and h >= rejection_px
            )
            if rejection_hit:
                outcome = "rejection_exit"
                exit_px = rejection_px
                exit_idx = k
                # Enter counter-trade at rejection_px, opposite dir
                counter_entry_idx = k
                counter_entry_px = rejection_px
                counter_dir = -di
                if counter_dir == 1:
                    counter_pt = rejection_px + bracket
                    counter_sl = rejection_px - bracket
                else:
                    counter_pt = rejection_px - bracket
                    counter_sl = rejection_px + bracket
                # Walk counter-trade from k (same bar — but already
                # processed bar k for original, so start from k+1)
                # Counter EOD = same as original's EOD
                last_counter = min(eod_idx, n - 1)
                for j in range(k + 1, last_counter + 1):
                    hj = highs[j]; lj = lows[j]
                    # Counter ordering: stop-then-target (conservative)
                    if counter_dir == 1:
                        if lj <= counter_sl:
                            counter_outcome = "loss"
                            counter_pnl_gross = (
                                counter_sl - counter_entry_px
                            ) * counter_dir
                            counter_exit_idx = j
                            break
                        if hj >= counter_pt:
                            counter_outcome = "win"
                            counter_pnl_gross = (
                                counter_pt - counter_entry_px
                            ) * counter_dir
                            counter_exit_idx = j
                            break
                    else:
                        if hj >= counter_sl:
                            counter_outcome = "loss"
                            counter_pnl_gross = (
                                counter_sl - counter_entry_px
                            ) * counter_dir
                            counter_exit_idx = j
                            break
                        if lj <= counter_pt:
                            counter_outcome = "win"
                            counter_pnl_gross = (
                                counter_pt - counter_entry_px
                            ) * counter_dir
                            counter_exit_idx = j
                            break
                if counter_outcome is None:
                    # EOD flat
                    counter_outcome = "eod_flat"
                    eod_close = closes[last_counter]
                    counter_pnl_gross = (
                        eod_close - counter_entry_px
                    ) * counter_dir
                    counter_exit_idx = last_counter
                counter_fired = True
                break
        # 3. Original stop check
        if di == 1 and l <= stop:
            outcome = "loss"; exit_px = stop; exit_idx = k; break
        if di == -1 and h >= stop:
            outcome = "loss"; exit_px = stop; exit_idx = k; break
        # 4. Target
        if di == 1 and h >= tgt:
            outcome = "win"; exit_px = tgt; exit_idx = k; break
        if di == -1 and l <= tgt:
            outcome = "win"; exit_px = tgt; exit_idx = k; break
        # 5. Update MFE; arm BE
        bar_mfe = (h - ep) if di == 1 else (ep - l)
        if bar_mfe > mfe_so_far:
            mfe_so_far = bar_mfe
        if not armed and mfe_so_far >= be_threshold:
            armed = True

    if outcome is None:
        # EOD flat for original
        outcome = "eod_flat"
        exit_idx = last_orig
        exit_px = closes[last_orig]

    orig_pnl_gross = (exit_px - ep) * di
    total_pnl_gross = orig_pnl_gross + counter_pnl_gross
    n_commissions = 1 + (1 if counter_fired else 0)
    total_pnl_net = (
        total_pnl_gross - COMMISSION_PTS * n_commissions)
    chain_exit_idx = (counter_exit_idx if counter_fired
                            else exit_idx)

    return {
        "trigger_bar_idx": t.bar_idx,
        "entry_idx": ent,
        "direction": di,
        "breach_level": breach,
        "next_level": t.next_level,
        "entry_price": ep,
        "session": t.bar_session,
        "outcome": outcome,
        "orig_exit_idx": exit_idx,
        "orig_exit_px": exit_px,
        "orig_pnl_gross": orig_pnl_gross,
        "counter_fired": counter_fired,
        "counter_outcome": counter_outcome,
        "counter_pnl_gross": counter_pnl_gross,
        "counter_exit_idx": counter_exit_idx,
        "chain_exit_idx": chain_exit_idx,
        "n_commissions": n_commissions,
        "total_pnl_gross": total_pnl_gross,
        "total_pnl_net": total_pnl_net,
    }


def run_one_combo(triggers, bars_arrays, next_eod,
                       rejection_trigger, bracket):
    """Run full sim with skip-while-open for one combo."""
    chains = []
    last_chain_exit = -1
    for t in triggers:
        ent = t.bar_idx + 1
        if ent <= last_chain_exit:
            continue  # in position
        r = simulate_chain(t, bars_arrays, rejection_trigger,
                                bracket, BE_THRESHOLD, next_eod)
        if r is None:
            continue
        chains.append(r)
        last_chain_exit = r["chain_exit_idx"]
    return pd.DataFrame(chains)


def stats(df):
    n = len(df)
    if n == 0: return {"n": 0}
    pnl = df["total_pnl_net"]
    counter_fired_n = int(df["counter_fired"].sum())
    counter_won = int(((df["counter_outcome"] == "win")
                            ).sum())
    counter_lost = int(((df["counter_outcome"] == "loss")
                              ).sum())
    counter_eod = int(((df["counter_outcome"] == "eod_flat")
                             ).sum())
    return {
        "n": n,
        "n_orig_win": int((df["outcome"] == "win").sum()),
        "n_orig_be_stop": int((df["outcome"] == "be_stop").sum()),
        "n_orig_loss": int((df["outcome"] == "loss").sum()),
        "n_orig_rejection": int(
            (df["outcome"] == "rejection_exit").sum()),
        "n_orig_eod": int((df["outcome"] == "eod_flat").sum()),
        "counter_fire_rate": counter_fired_n / n,
        "counter_n": counter_fired_n,
        "counter_win_rate": (counter_won / counter_fired_n
                                  if counter_fired_n else 0),
        "counter_won": counter_won,
        "counter_lost": counter_lost,
        "counter_eod": counter_eod,
        "mean_pnl_net": float(pnl.mean()),
        "total_pnl_net": float(pnl.sum()),
        "annual_dollars": float(
            pnl.sum() * NQ_DOLLAR_PER_PT),
    }


def fmt_p(v):
    if v is None or pd.isna(v): return "—"
    return f"{100*v:.1f}%"


def fmt_f(v, dp=2):
    if v is None or pd.isna(v): return "—"
    return f"{v:+.{dp}f}"


def fmt_d(v):
    if v is None or pd.isna(v): return "—"
    return f"${v:,.0f}"


def write_report(grid_per_year, best_per_combo):
    L = []
    L.append("# Rejection Counter-Trade Grid Sweep "
              "(Option B — full re-sim w/ skip-while-open)\n")
    L.append("## Method\n")
    L.append(
        "Full from-scratch re-simulation. Each (rejection trigger, "
        "bracket) combo runs the entire strategy: trigger → "
        "original BE=2.5 + level-stop → if BE not armed and price "
        "hits breach ± REJECTION pts, exit original and enter "
        "counter-trade in opposite direction with PT/SL = "
        "±BRACKET. Counter-trade exits on PT/SL or EOD (16:00 "
        "CT), no max-bars timeout. Single-position skip-while-open "
        "applied across the entire chain.\n\n"
        f"BE threshold: {BE_THRESHOLD} pt | Commission: "
        f"{COMMISSION_PTS} pt | Multiplier: ${NQ_DOLLAR_PER_PT}\n\n"
        f"Rejection triggers: {REJECTION_TRIGGERS}\n"
        f"Brackets (PT/SL ±): {BRACKETS}\n")

    for year in sorted(grid_per_year.keys()):
        grid = grid_per_year[year]
        L.append(f"## {year} — Mean PnL net by "
                  "(rejection trigger × bracket)\n")
        p = grid.pivot(index="rejection_trigger",
                              columns="bracket",
                              values="mean_pnl_net")
        L.append("| Rej\\Brk | " + " | ".join(
            f"{c}" for c in p.columns) + " |")
        L.append("|---" * (len(p.columns) + 1) + "|")
        max_val = p.values.max()
        for r, row in p.iterrows():
            cells = []
            for col in p.columns:
                v = row[col]
                cell = fmt_f(v, 3)
                if v == max_val: cell = f"**{cell}**"
                cells.append(cell)
            L.append(f"| {r} | " + " | ".join(cells) + " |")
        L.append("")

        L.append(f"### {year} — Annual $ at each cell\n")
        p = grid.pivot(index="rejection_trigger",
                              columns="bracket",
                              values="annual_dollars")
        L.append("| Rej\\Brk | " + " | ".join(
            f"{c}" for c in p.columns) + " |")
        L.append("|---" * (len(p.columns) + 1) + "|")
        max_val = p.values.max()
        for r, row in p.iterrows():
            cells = []
            for col in p.columns:
                v = row[col]
                cell = fmt_d(v)
                if v == max_val: cell = f"**{cell}**"
                cells.append(cell)
            L.append(f"| {r} | " + " | ".join(cells) + " |")
        L.append("")

        L.append(f"### {year} — Counter-trade fire rate (%)\n")
        p = grid.pivot(index="rejection_trigger",
                              columns="bracket",
                              values="counter_fire_rate")
        L.append("| Rej\\Brk | " + " | ".join(
            f"{c}" for c in p.columns) + " |")
        L.append("|---" * (len(p.columns) + 1) + "|")
        for r, row in p.iterrows():
            cells = [f"{100*row[col]:.1f}%" for col in p.columns]
            L.append(f"| {r} | " + " | ".join(cells) + " |")
        L.append("")

        L.append(f"### {year} — Counter-trade WR (when fired)\n")
        p = grid.pivot(index="rejection_trigger",
                              columns="bracket",
                              values="counter_win_rate")
        L.append("| Rej\\Brk | " + " | ".join(
            f"{c}" for c in p.columns) + " |")
        L.append("|---" * (len(p.columns) + 1) + "|")
        for r, row in p.iterrows():
            cells = [f"{100*row[col]:.1f}%" for col in p.columns]
            L.append(f"| {r} | " + " | ".join(cells) + " |")
        L.append("")

    # Best combo table
    L.append("## Best (rejection × bracket) combo per year\n")
    L.append("| Year | Best Rej | Best Bracket | n trades | "
             "Mean Net | Total | Annual $ | Counter Fire% | "
             "Counter WR |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for year, df in grid_per_year.items():
        best = df.loc[df["mean_pnl_net"].idxmax()]
        L.append(
            f"| {year} | {best['rejection_trigger']} | "
            f"{best['bracket']} | {int(best['n']):,} | "
            f"{fmt_f(best['mean_pnl_net'], 3)} | "
            f"{fmt_f(best['total_pnl_net'], 0)} | "
            f"{fmt_d(best['annual_dollars'])} | "
            f"{fmt_p(best['counter_fire_rate'])} | "
            f"{fmt_p(best['counter_win_rate'])} |")
    L.append("")

    # Cross-year comparison: combo that's best across BOTH years
    L.append("## Cross-year combo ranking (combined annual $)\n")
    combined = best_per_combo
    combined["combined_annual"] = (
        combined["annual_2024"] + combined["annual_2025"])
    L.append("| Rej | Brk | 2024 Annual | 2025 Annual | "
             "Combined |")
    L.append("|--:|--:|--:|--:|--:|")
    for _, r in combined.sort_values(
            "combined_annual", ascending=False).iterrows():
        L.append(
            f"| {r['rejection_trigger']} | {r['bracket']} | "
            f"{fmt_d(r['annual_2024'])} | "
            f"{fmt_d(r['annual_2025'])} | "
            f"{fmt_d(r['combined_annual'])} |")
    L.append("")

    p = OUT / "report_rejection_grid.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def main():
    t0 = time.time()
    grid_per_year = {}

    for year in [2024, 2025]:
        print(f"\n[{year}] loading bars...")
        parquet = Path(f"data/raw/NQ_v0_1s_{year}.parquet")
        bars_1s = load_v0_1s(parquet)
        bars_1m = resample_1s_to_1m(bars_1s)
        bars_1m = annotate_sessions_ct(bars_1m)
        bars_filt, _ = filter_roll_window(bars_1m, 3)
        bars_reset = bars_filt.reset_index(drop=False)

        print(f"[{year}] precomputing EOD indices...")
        next_eod = precompute_eod_indices(bars_reset)
        bars_arrays = {
            "n": len(bars_reset),
            "opens": bars_reset["open"].values,
            "highs": bars_reset["high"].values,
            "lows": bars_reset["low"].values,
            "closes": bars_reset["close"].values,
        }

        print(f"[{year}] detecting triggers...")
        triggers = detect_triggers(bars_reset)
        print(f"  {len(triggers):,} triggers")

        rows = []
        for rt in REJECTION_TRIGGERS:
            for br in BRACKETS:
                t1 = time.time()
                df = run_one_combo(triggers, bars_arrays,
                                          next_eod, rt, br)
                s = stats(df)
                s["year"] = year
                s["rejection_trigger"] = rt
                s["bracket"] = br
                rows.append(s)
                print(f"  rt={rt}, brk={br}: n={s['n']:,}, "
                      f"mean={s['mean_pnl_net']:+.3f}, "
                      f"counter_fire={s['counter_fire_rate']:.1%}, "
                      f"counter_WR="
                      f"{s['counter_win_rate']:.1%}, "
                      f"({time.time()-t1:.1f}s)")

        grid = pd.DataFrame(rows)
        grid.to_csv(OUT / f"grid_{year}.csv", index=False)
        grid_per_year[year] = grid

    # Build cross-year combo table
    combos = []
    for rt in REJECTION_TRIGGERS:
        for br in BRACKETS:
            row = {"rejection_trigger": rt, "bracket": br}
            for year in [2024, 2025]:
                gy = grid_per_year[year]
                cell = gy[(gy["rejection_trigger"] == rt) &
                              (gy["bracket"] == br)]
                if len(cell):
                    row[f"annual_{year}"] = float(
                        cell["annual_dollars"].iloc[0])
                else:
                    row[f"annual_{year}"] = 0.0
            combos.append(row)
    combos_df = pd.DataFrame(combos)
    combos_df["combined_annual"] = (
        combos_df["annual_2024"] + combos_df["annual_2025"])
    combos_df.to_csv(OUT / "combos_combined.csv", index=False)

    print("\nWriting report...")
    rp = write_report(grid_per_year, combos_df)
    print(f"Report: {rp}")
    print(f"Total elapsed: {(time.time() - t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
