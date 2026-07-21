"""Rejection counter-trade grid sweep — V2: arm-BE-first ordering.

Difference vs v1:
  V1 ordering per bar: rejection-check → ... → arm-BE at end-of-bar
    This caused rejection to fire on bars where BE would have armed
    intra-bar, hijacking ~3-4× more trades than the true never-armed
    population.

  V2 ordering per bar: update-MFE-from-H/L → arm-BE → check exits
    A bar's high (long) or low (short) reaching +2.5 favorable arms
    BE intra-bar. Rejection only fires on bars where MFE did NOT
    reach +2.5 — closer to the true "never armed" population (~12%).

This is the more favorable interpretation for the BE rule and the
more realistic interpretation of "did momentum develop?".

Same grid: REJECTION_TRIGGERS × BRACKETS, EOD flat, skip-while-open.
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
from studies.level_momentum_continuation.analyze_rejection_grid import (
    precompute_eod_indices, stats, REJECTION_TRIGGERS,
    BRACKETS, BE_THRESHOLD, COMMISSION_PTS, NQ_DOLLAR_PER_PT,
    fmt_p, fmt_f, fmt_d,
)


OUT = Path(
    "studies/level_momentum_continuation/results_rejection_grid_v2")
OUT.mkdir(parents=True, exist_ok=True)


def simulate_chain_v2(t, bars_arrays, rejection_trigger,
                            bracket, be_threshold, next_eod):
    """Arm-BE-first ordering. See module docstring."""
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

    eod_idx = next_eod[ent]
    armed = False
    mfe_so_far = 0.0
    outcome = None
    exit_px = ep
    exit_idx = ent

    last_orig = min(eod_idx, n - 1)
    counter_fired = False
    counter_outcome = None
    counter_pnl_gross = 0.0
    counter_entry_idx = -1
    counter_exit_idx = -1
    counter_entry_px = 0.0

    for k in range(ent, last_orig + 1):
        h = highs[k]; l = lows[k]

        # 1. Update MFE; arm BE FIRST (intra-bar)
        bar_mfe = (h - ep) if di == 1 else (ep - l)
        if bar_mfe > mfe_so_far:
            mfe_so_far = bar_mfe
        if not armed and mfe_so_far >= be_threshold:
            armed = True

        # 2. BE-stop (if armed) — beats target on tie
        if armed:
            if di == 1 and l <= ep:
                outcome = "be_stop"; exit_px = ep; exit_idx = k
                break
            if di == -1 and h >= ep:
                outcome = "be_stop"; exit_px = ep; exit_idx = k
                break

        # 3. Rejection (only fires if NEVER armed)
        if not armed:
            rejection_hit = (
                di == 1 and l <= rejection_px) or (
                di == -1 and h >= rejection_px)
            if rejection_hit:
                outcome = "rejection_exit"
                exit_px = rejection_px
                exit_idx = k
                # Counter-trade
                counter_entry_idx = k
                counter_entry_px = rejection_px
                counter_dir = -di
                if counter_dir == 1:
                    counter_pt = rejection_px + bracket
                    counter_sl = rejection_px - bracket
                else:
                    counter_pt = rejection_px - bracket
                    counter_sl = rejection_px + bracket
                last_counter = min(eod_idx, n - 1)
                for j in range(k + 1, last_counter + 1):
                    hj = highs[j]; lj = lows[j]
                    if counter_dir == 1:
                        if lj <= counter_sl:
                            counter_outcome = "loss"
                            counter_pnl_gross = (
                                counter_sl
                                - counter_entry_px) * counter_dir
                            counter_exit_idx = j; break
                        if hj >= counter_pt:
                            counter_outcome = "win"
                            counter_pnl_gross = (
                                counter_pt
                                - counter_entry_px) * counter_dir
                            counter_exit_idx = j; break
                    else:
                        if hj >= counter_sl:
                            counter_outcome = "loss"
                            counter_pnl_gross = (
                                counter_sl
                                - counter_entry_px) * counter_dir
                            counter_exit_idx = j; break
                        if lj <= counter_pt:
                            counter_outcome = "win"
                            counter_pnl_gross = (
                                counter_pt
                                - counter_entry_px) * counter_dir
                            counter_exit_idx = j; break
                if counter_outcome is None:
                    counter_outcome = "eod_flat"
                    eod_close = closes[last_counter]
                    counter_pnl_gross = (
                        eod_close
                        - counter_entry_px) * counter_dir
                    counter_exit_idx = last_counter
                counter_fired = True
                break

        # 4. Original stop (only fires if not armed — armed uses BE)
        if not armed:
            if di == 1 and l <= stop:
                outcome = "loss"; exit_px = stop; exit_idx = k
                break
            if di == -1 and h >= stop:
                outcome = "loss"; exit_px = stop; exit_idx = k
                break

        # 5. Target
        if di == 1 and h >= tgt:
            outcome = "win"; exit_px = tgt; exit_idx = k; break
        if di == -1 and l <= tgt:
            outcome = "win"; exit_px = tgt; exit_idx = k; break

    if outcome is None:
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
    chains = []
    last_chain_exit = -1
    for t in triggers:
        ent = t.bar_idx + 1
        if ent <= last_chain_exit:
            continue
        r = simulate_chain_v2(t, bars_arrays, rejection_trigger,
                                       bracket, BE_THRESHOLD, next_eod)
        if r is None: continue
        chains.append(r)
        last_chain_exit = r["chain_exit_idx"]
    return pd.DataFrame(chains)


def write_report(grid_per_year, combos):
    L = []
    L.append("# Rejection Grid V2 — arm-BE-first ordering\n")
    L.append("## Method change vs V1\n")
    L.append(
        "V1 had per-bar order: rejection check → ... → arm BE at "
        "end of bar. This caused rejection to fire on bars where "
        "BE would have armed intra-bar (~33-48% counter fire vs "
        "true ~12% never-armed rate).\n\n"
        "**V2** updates MFE and arms BE FIRST in each bar (the "
        "high/low values intra-bar are used to detect MFE >= "
        "threshold). Once armed, only BE-stop or target can fire — "
        "rejection is suppressed. Rejection only fires on bars "
        "where MFE genuinely never reached +2.5.\n\n"
        f"Grid: rejection {REJECTION_TRIGGERS} × bracket "
        f"{BRACKETS}. BE={BE_THRESHOLD}. "
        f"EOD=16:00 CT. Comm={COMMISSION_PTS}.\n")

    for year in sorted(grid_per_year.keys()):
        grid = grid_per_year[year]
        L.append(f"## {year} — Mean PnL net by "
                  "(rejection × bracket)\n")
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

        L.append(f"### {year} — Annual $\n")
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

        L.append(f"### {year} — Counter-trade fire rate\n")
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

    L.append("## Cross-year combo ranking\n")
    L.append("| Rej | Brk | 2024 Annual | 2025 Annual | "
             "Combined |")
    L.append("|--:|--:|--:|--:|--:|")
    for _, r in combos.sort_values(
            "combined_annual", ascending=False).iterrows():
        L.append(
            f"| {r['rejection_trigger']} | {r['bracket']} | "
            f"{fmt_d(r['annual_2024'])} | "
            f"{fmt_d(r['annual_2025'])} | "
            f"{fmt_d(r['combined_annual'])} |")
    L.append("")

    p = OUT / "report_rejection_grid_v2.md"
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
        next_eod = precompute_eod_indices(bars_reset)
        bars_arrays = {
            "n": len(bars_reset),
            "opens": bars_reset["open"].values,
            "highs": bars_reset["high"].values,
            "lows": bars_reset["low"].values,
            "closes": bars_reset["close"].values,
        }
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
                      f"fire={s['counter_fire_rate']:.1%}, "
                      f"WR={s['counter_win_rate']:.1%}, "
                      f"({time.time()-t1:.1f}s)")
        grid = pd.DataFrame(rows)
        grid.to_csv(OUT / f"grid_{year}.csv", index=False)
        grid_per_year[year] = grid

    combos = []
    for rt in REJECTION_TRIGGERS:
        for br in BRACKETS:
            row = {"rejection_trigger": rt, "bracket": br}
            for year in [2024, 2025]:
                gy = grid_per_year[year]
                cell = gy[(gy["rejection_trigger"] == rt) &
                              (gy["bracket"] == br)]
                row[f"annual_{year}"] = (
                    float(cell["annual_dollars"].iloc[0])
                    if len(cell) else 0.0)
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
