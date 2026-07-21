"""Root-cause attribution: where does the $90K 2025 ±10d roll-excl gap come from?

Total gap (NT 1s vs NT tick, 1-contract clean, NQ.v.0 catalog vs NQ.c.0
ticks, 2025 with ±10d expiry exclusion):
  1s PnL: +$85,660 on 8,907 trades
  tick PnL: -$4,855 on 9,011 trades
  Δ: -$90,515 (the number we have to reconcile to)

Decomposition:

  total_gap = matched_gap + unmatched_gap

  matched_gap = sum over matched trades of (pnl_tk - pnl_1s)
    Further decomposed into:
      - same_outcome_pnl_diff: matched, both win or both lose, different prices
      - flip_outcome_pnl_diff: matched, win in one and loss in other

  unmatched_gap = (sum tick-only PnL) - (sum 1s-only PnL)

The unmatched trades break further into:
  - chain-eligibility-blocked: other engine was in a prior trade
  - same-state-but-trigger-differs: other engine was flat but didn't fire

Each per-trade pnl difference for matched trades:
  pnl_1s - pnl_tk = (entry_px_1s - entry_px_tk) * direction
                  - (exit_px_1s - exit_px_tk) * direction
                  + commission_diff
  But commission is per-trade $5, same in both → cancels out.
  So PnL diff is decomposable into entry + exit price differences.

Goal: produce a reconciliation table that adds up to -$90,515.
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import date

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

OUT = Path("studies/level_momentum_continuation/results_breakout")
NQ_MULT = 20.0
COMMISSION = 5.0   # per contract round trip in dollars

NQ_EXPIRIES_2025 = [
    date(2025, 3, 21), date(2025, 6, 20),
    date(2025, 9, 19), date(2025, 12, 19),
]


def in_roll_window(d, window_days=10):
    return any(abs((d - e).days) <= window_days for e in NQ_EXPIRIES_2025)


def main():
    df_1s = pd.read_parquet(OUT / "nt_v0_2025_clean_1s_trades.parquet")
    df_tk = pd.read_parquet(OUT / "nt_v0_2025_clean_tick_trades.parquet")
    df_1s["entry_dt"] = pd.to_datetime(df_1s["c1_fill_ts"], unit="ns",
                                          utc=True)
    df_1s["exit_dt"] = pd.to_datetime(df_1s["exit_ts"], unit="ns",
                                          utc=True)
    df_1s["entry_date"] = df_1s["entry_dt"].dt.date
    df_1s["signal_ts"] = df_1s["entry_dt"] - pd.Timedelta(seconds=1)
    df_tk["entry_dt"] = pd.to_datetime(df_tk["c1_fill_ts"], unit="ns",
                                          utc=True)
    df_tk["exit_dt"] = pd.to_datetime(df_tk["exit_ts"], unit="ns",
                                          utc=True)
    df_tk["entry_date"] = df_tk["entry_dt"].dt.date
    df_tk["signal_ts"] = df_tk["entry_dt"] - pd.Timedelta(seconds=1)

    # ±10d roll exclusion
    df_1s_f = df_1s[~df_1s["entry_date"].apply(in_roll_window)].copy()
    df_tk_f = df_tk[~df_tk["entry_date"].apply(in_roll_window)].copy()
    n_1s = len(df_1s_f); n_tk = len(df_tk_f)

    # Per-trade $ PnL (with commission already netted)
    df_1s_f["pnl_$"] = df_1s_f["c1_pnl_pts"] * NQ_MULT - COMMISSION
    df_tk_f["pnl_$"] = df_tk_f["c1_pnl_pts"] * NQ_MULT - COMMISSION

    pnl_1s_total = df_1s_f["pnl_$"].sum()
    pnl_tk_total = df_tk_f["pnl_$"].sum()
    full_gap = pnl_tk_total - pnl_1s_total   # negative if tick worse

    print(f"=" * 78)
    print(f"BASELINE GAP (must reconcile to this)")
    print(f"=" * 78)
    print(f"  1s NT (clean 1-ctr, ±10d roll-excl): n={n_1s:,}  total ${pnl_1s_total:+,.0f}")
    print(f"  tick NT (clean 1-ctr, ±10d roll-excl): n={n_tk:,}  total ${pnl_tk_total:+,.0f}")
    print(f"  TOTAL GAP (tick - 1s): ${full_gap:+,.0f}")

    # ---- Match trades ----
    df_1s_f = df_1s_f.sort_values("signal_ts").reset_index(drop=True)
    df_tk_f = df_tk_f.sort_values("signal_ts").reset_index(drop=True)

    merged = pd.merge_asof(
        df_1s_f[["signal_ts", "entry_dt", "exit_dt", "c1_pnl_pts",
                  "exit_reason", "direction", "breach_level",
                  "c1_fill_px", "exit_px", "pnl_$", "group"]]
            .rename(columns={"signal_ts": "sig_1s",
                              "entry_dt": "ent_1s", "exit_dt": "exit_1s",
                              "c1_pnl_pts": "pp_1s",
                              "exit_reason": "outc_1s",
                              "c1_fill_px": "px_1s",
                              "exit_px": "expx_1s",
                              "pnl_$": "pnl_$_1s",
                              "group": "group_1s"}),
        df_tk_f[["signal_ts", "entry_dt", "exit_dt", "c1_pnl_pts",
                  "exit_reason", "direction", "breach_level",
                  "c1_fill_px", "exit_px", "pnl_$"]]
            .rename(columns={"signal_ts": "sig_tk",
                              "entry_dt": "ent_tk", "exit_dt": "exit_tk",
                              "c1_pnl_pts": "pp_tk",
                              "exit_reason": "outc_tk",
                              "c1_fill_px": "px_tk",
                              "exit_px": "expx_tk",
                              "pnl_$": "pnl_$_tk"}),
        left_on="sig_1s", right_on="sig_tk",
        by=["direction", "breach_level"],
        tolerance=pd.Timedelta(seconds=60),
        direction="nearest",
    )

    matched = merged[merged["sig_tk"].notna()].copy()
    only_1s = merged[merged["sig_tk"].isna()].copy()
    matched_tk_sigs_ns = matched["sig_tk"].astype("int64").values
    df_tk_sigs_ns = df_tk_f["signal_ts"].astype("int64").values
    in_matched = np.isin(df_tk_sigs_ns, matched_tk_sigs_ns)
    only_tk = df_tk_f[~in_matched].copy()

    print(f"\n  Matched trades: {len(matched):,}")
    print(f"  Only-in-1s: {len(only_1s):,}")
    print(f"  Only-in-tick: {len(only_tk):,}")

    # ---- 1. UNMATCHED CONTRIBUTION ----
    print(f"\n{'='*78}")
    print(f"1. DIFFERENT-TRIGGER CONTRIBUTION (unmatched trades)")
    print(f"{'='*78}")
    only_1s_pnl = float(only_1s["pnl_$_1s"].sum())
    only_tk_pnl = float(only_tk["pnl_$"].sum())
    unmatched_contrib = only_tk_pnl - only_1s_pnl
    # The 1s-only trades INCREASED 1s total → reducing them = -(only_1s_pnl)
    # The tick-only trades INCREASED tick total → contribute +only_tk_pnl
    # So tick - 1s gap from unmatched = only_tk_pnl - only_1s_pnl
    print(f"  1s-only trades: n={len(only_1s):,}, PnL ${only_1s_pnl:+,.0f}  (${only_1s_pnl/max(1,len(only_1s)):+.2f}/tr)")
    print(f"  Tick-only trades: n={len(only_tk):,}, PnL ${only_tk_pnl:+,.0f}  (${only_tk_pnl/max(1,len(only_tk)):+.2f}/tr)")
    print(f"  Unmatched contribution to gap: ${unmatched_contrib:+,.0f}")

    # ---- 2. CHAIN ELIGIBILITY BREAKDOWN ----
    # For 1s-only: was tick engine in a prior trade at sig_t?
    # For tick-only: was 1s engine in a prior trade at sig_t?
    print(f"\n{'='*78}")
    print(f"  Chain-eligibility breakdown of unmatched trades")
    print(f"{'='*78}")
    tk_entries = df_tk_f["entry_dt"].astype("int64").values
    tk_exits = df_tk_f["exit_dt"].astype("int64").values
    s_entries = df_1s_f["entry_dt"].astype("int64").values
    s_exits = df_1s_f["exit_dt"].astype("int64").values

    def was_busy(sig_ns, entries_ns, exits_ns, lookback=10):
        idx = np.searchsorted(entries_ns, sig_ns, side="right") - 1
        for j in range(idx, max(idx-lookback, -1), -1):
            if j < 0: break
            if exits_ns[j] > sig_ns:
                return True
        return False

    # 1s-only — blocked by tick
    only_1s_blocked_pnl = 0.0; only_1s_blocked_n = 0
    only_1s_freetrigger_pnl = 0.0; only_1s_freetrigger_n = 0
    for _, row in only_1s.iterrows():
        sig = pd.Timestamp(row["sig_1s"]).value
        if was_busy(sig, tk_entries, tk_exits):
            only_1s_blocked_pnl += row["pnl_$_1s"]
            only_1s_blocked_n += 1
        else:
            only_1s_freetrigger_pnl += row["pnl_$_1s"]
            only_1s_freetrigger_n += 1
    # tick-only — blocked by 1s
    only_tk_blocked_pnl = 0.0; only_tk_blocked_n = 0
    only_tk_freetrigger_pnl = 0.0; only_tk_freetrigger_n = 0
    for _, row in only_tk.iterrows():
        sig = pd.Timestamp(row["signal_ts"]).value
        if was_busy(sig, s_entries, s_exits):
            only_tk_blocked_pnl += row["pnl_$"]
            only_tk_blocked_n += 1
        else:
            only_tk_freetrigger_pnl += row["pnl_$"]
            only_tk_freetrigger_n += 1

    print(f"  1s-only:")
    print(f"    blocked by tick chain busy: n={only_1s_blocked_n:,}  PnL ${only_1s_blocked_pnl:+,.0f}")
    print(f"    tick chain free but trigger differs: n={only_1s_freetrigger_n:,}  PnL ${only_1s_freetrigger_pnl:+,.0f}")
    print(f"  Tick-only:")
    print(f"    blocked by 1s chain busy: n={only_tk_blocked_n:,}  PnL ${only_tk_blocked_pnl:+,.0f}")
    print(f"    1s chain free but trigger differs: n={only_tk_freetrigger_n:,}  PnL ${only_tk_freetrigger_pnl:+,.0f}")

    # Sub-attribution within unmatched
    sub_chain_block = (only_tk_blocked_pnl - only_1s_blocked_pnl)
    sub_trigger_diff = (only_tk_freetrigger_pnl - only_1s_freetrigger_pnl)
    print(f"\n  Unmatched gap split:")
    print(f"    From CHAIN BLOCKING (other engine busy): ${sub_chain_block:+,.0f}")
    print(f"    From TRIGGER DETECTION DIFFERS (both free): ${sub_trigger_diff:+,.0f}")
    print(f"    Sum: ${sub_chain_block + sub_trigger_diff:+,.0f}  (should equal ${unmatched_contrib:+,.0f})")

    # ---- 3. MATCHED CONTRIBUTION ----
    print(f"\n{'='*78}")
    print(f"3. MATCHED-TRIGGER CONTRIBUTION (different fills/exits)")
    print(f"{'='*78}")
    matched_1s_pnl = float(matched["pnl_$_1s"].sum())
    # tick PnL of matched: pnl_$_tk = pp_tk * NQ_MULT - COMMISSION
    matched["pnl_$_tk_calc"] = matched["pp_tk"] * NQ_MULT - COMMISSION
    matched_tk_pnl = float(matched["pnl_$_tk_calc"].sum())
    matched_contrib = matched_tk_pnl - matched_1s_pnl
    print(f"  Matched 1s PnL: ${matched_1s_pnl:+,.0f}")
    print(f"  Matched tick PnL: ${matched_tk_pnl:+,.0f}")
    print(f"  Matched contribution to gap: ${matched_contrib:+,.0f}")

    # Decompose into outcome-flip vs same-outcome
    matched["same_outcome"] = matched["outc_1s"] == matched["outc_tk"]
    same_o = matched[matched["same_outcome"]]
    flip_o = matched[~matched["same_outcome"]]

    same_1s = float(same_o["pnl_$_1s"].sum())
    same_tk = float(same_o["pnl_$_tk_calc"].sum())
    flip_1s = float(flip_o["pnl_$_1s"].sum())
    flip_tk = float(flip_o["pnl_$_tk_calc"].sum())

    print(f"\n  Same-outcome matched: n={len(same_o):,}")
    print(f"    1s PnL: ${same_1s:+,.0f}  tick PnL: ${same_tk:+,.0f}  Δ: ${same_tk-same_1s:+,.0f}")
    print(f"    Of {len(same_o):,}, outcome distribution:")
    print(f"      both win: {((same_o['outc_1s']=='win')).sum():,}")
    print(f"      both loss: {((same_o['outc_1s']=='loss')).sum():,}")
    print(f"      both eod_flat: {((same_o['outc_1s']=='eod_flat')).sum():,}")
    print(f"\n  Flipped-outcome matched: n={len(flip_o):,}")
    print(f"    1s PnL: ${flip_1s:+,.0f}  tick PnL: ${flip_tk:+,.0f}  Δ: ${flip_tk-flip_1s:+,.0f}")
    if len(flip_o) > 0:
        print(f"    Distribution:")
        for k, v in flip_o.groupby(["outc_1s", "outc_tk"]).size().items():
            print(f"      1s={k[0]} → tick={k[1]}: {v:,}")

    # For same-outcome: decompose entry diff vs exit diff
    if len(same_o) > 0:
        same_o = same_o.copy()
        # For each trade: pnl_diff = pnl_tk - pnl_1s
        # = (exit_px_tk - entry_px_tk - (exit_px_1s - entry_px_1s)) * direction * NQ_MULT
        # = (exit_diff - entry_diff) * direction * NQ_MULT
        # entry_diff = px_1s - px_tk; signed by direction (long: tick higher = worse)
        same_o["entry_diff_pts"] = (same_o["px_tk"] - same_o["px_1s"]) * same_o["direction"]
        same_o["exit_diff_pts"] = (same_o["expx_tk"] - same_o["expx_1s"]) * same_o["direction"]
        # PnL_tk - PnL_1s = exit_diff - entry_diff (both signed)
        same_o["pnl_diff_$"] = (same_o["exit_diff_pts"] - same_o["entry_diff_pts"]) * NQ_MULT
        # Cross-check
        same_o["pnl_diff_$_calc"] = same_o["pnl_$_tk_calc"] - same_o["pnl_$_1s"]
        # By component
        entry_contrib_per = -same_o["entry_diff_pts"] * NQ_MULT  # higher entry for tick = lower tick PnL
        exit_contrib_per = same_o["exit_diff_pts"] * NQ_MULT
        entry_total = entry_contrib_per.sum()
        exit_total = exit_contrib_per.sum()
        print(f"\n  Same-outcome decomposition (entry vs exit price differences):")
        print(f"    Entry-price contribution: ${entry_total:+,.0f}  "
              f"(mean ${entry_contrib_per.mean():+.2f}/tr; "
              f"median ${entry_contrib_per.median():+.2f}/tr)")
        print(f"    Exit-price contribution: ${exit_total:+,.0f}  "
              f"(mean ${exit_contrib_per.mean():+.2f}/tr; "
              f"median ${exit_contrib_per.median():+.2f}/tr)")
        print(f"    Sum: ${entry_total + exit_total:+,.0f}  "
              f"(should equal same-outcome Δ ${same_tk - same_1s:+,.0f})")

        # Distribution of entry diffs
        ed = same_o["entry_diff_pts"].values
        print(f"\n  Entry diff distribution (signed; positive=tick worse):")
        for q in [10, 25, 50, 75, 90]:
            print(f"    p{q}: {np.percentile(ed, q):+.4f} pts")
        print(f"    mean: {ed.mean():+.4f}  abs mean: {np.abs(ed).mean():.4f}")
        print(f"    %|diff| > 0.25: {100*(np.abs(ed) > 0.25).mean():.2f}%")
        print(f"    %|diff| > 0.5: {100*(np.abs(ed) > 0.5).mean():.2f}%")
        print(f"    %|diff| > 1.0: {100*(np.abs(ed) > 1.0).mean():.2f}%")

        # Distribution of exit diffs
        xd = same_o["exit_diff_pts"].values
        print(f"\n  Exit diff distribution (signed; positive=tick better):")
        for q in [10, 25, 50, 75, 90]:
            print(f"    p{q}: {np.percentile(xd, q):+.4f} pts")
        print(f"    mean: {xd.mean():+.4f}  abs mean: {np.abs(xd).mean():.4f}")

    # ---- RECONCILIATION TABLE ----
    print(f"\n{'='*78}")
    print(f"RECONCILIATION TABLE")
    print(f"{'='*78}")
    print(f"  Component                                   | $ contribution")
    print(f"  -------------------------------------------+--------------")
    print(f"  Unmatched: chain blocked (other busy)       | ${sub_chain_block:>+9,.0f}")
    print(f"  Unmatched: trigger detection differs        | ${sub_trigger_diff:>+9,.0f}")
    if len(same_o) > 0:
        print(f"  Matched same-outcome: entry-price diff      | ${entry_total:>+9,.0f}")
        print(f"  Matched same-outcome: exit-price diff       | ${exit_total:>+9,.0f}")
    flip_contrib = flip_tk - flip_1s
    print(f"  Matched flipped outcome (win↔loss)          | ${flip_contrib:>+9,.0f}")
    print(f"  -------------------------------------------+--------------")
    summed = (sub_chain_block + sub_trigger_diff
              + (entry_total if len(same_o) > 0 else 0)
              + (exit_total if len(same_o) > 0 else 0)
              + flip_contrib)
    print(f"  RECONCILED TOTAL                            | ${summed:>+9,.0f}")
    print(f"  ACTUAL GAP                                  | ${full_gap:>+9,.0f}")
    print(f"  Difference (residual)                       | ${full_gap - summed:>+9,.0f}")
    if abs(full_gap - summed) < 50:
        print(f"  ✓ Reconciles within $50 tolerance")
    else:
        print(f"  ✗ Residual exceeds tolerance — diagnosis incomplete")


if __name__ == "__main__":
    main()
