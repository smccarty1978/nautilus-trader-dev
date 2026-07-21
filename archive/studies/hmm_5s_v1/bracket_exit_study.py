"""HMM best-slice bracket + exit-rule study.

Population: 2025 RTH raw 1m flips, HH/LL confirmed, NOT in state 3,
no recent transition (~1,086 trades).

For each trade, walk 1s bars forward up to 30 min (or regime exit,
whichever comes first). Track multiple bracket geometries + stall
exits in a single pass.

CAUSAL-AUDIT (2026-04-26): regime-exit logic is causal. Uses
`flip_bar_ts_init` (= 1m bar CLOSE = moment of detection) for next
opposing flip search. Exit price = `bars_c[hi-1]` resolves to the
1m bar's close at regime_exit_ts. Bracket race correctly exposes
trades to PT/SL DURING the flip bar's adverse move before regime
exit triggers. No fix required.
"""

from __future__ import annotations
import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)
sys.path.insert(0, str(project_root))

from nautilus_trader.persistence.catalog import ParquetDataCatalog

OUT = Path("studies/hmm_5s_v1/results")
NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0


def main():
    print("Loading rawflip outcomes + raw flips list...")
    rec = pd.read_parquet(OUT / "rawflip_state_outcomes_2025.parquet")
    raw_flips = pd.read_parquet(OUT / "raw_flips_2025.parquet")
    print(f"  Total raw flips with state: {len(rec):,}")

    # Filter to best HMM slice
    slice_ = rec[
        (rec["hhll_confirmed"] == True)
        & (rec["state"] != 3)
        & (~rec["recent_transition"])
    ].copy()
    print(f"  HMM best slice (HH/LL conf, excl state 3, "
           f"no transition): {len(slice_):,}")

    # For each trade, find regime-exit time = ts_init of next flip
    # in raw_flips_2025 with new_regime != this trade's direction
    print("\nComputing regime-exit times for each trade...")
    raw_flips_sorted = raw_flips.sort_values("flip_bar_ts_init")
    rf_ts = raw_flips_sorted["flip_bar_ts_init"].values
    rf_regime = raw_flips_sorted["new_regime"].values

    regime_exit_ts = []
    for _, row in slice_.iterrows():
        flip_ts_init = int(row["flip_bar_ts_init"])
        d = int(row["direction"])
        # Find first flip after this with regime != d
        # Use searchsorted to find starting position
        start_idx = np.searchsorted(rf_ts, flip_ts_init,
                                       side="right")
        opposing_mask = rf_regime[start_idx:] != d
        if opposing_mask.any():
            first_opp = start_idx + int(opposing_mask.argmax())
            regime_exit_ts.append(int(rf_ts[first_opp]))
        else:
            # No opposing flip after — end of data; use a far-future
            regime_exit_ts.append(int(rf_ts[-1] + 30 * 24 * 3600 * int(1e9)))
    slice_["regime_exit_ts_ns"] = regime_exit_ts
    print(f"  Median time to regime exit: "
           f"{((slice_['regime_exit_ts_ns'] - slice_['flip_bar_ts_init'])/1e9).median():.0f}s")

    # Load 1s bars for forward walks
    print("\nLoading 2025 1s bars...")
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    bars_nt = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=pd.Timestamp("2025-01-01", tz="UTC"),
        end=pd.Timestamp("2025-12-31 23:59:59", tz="UTC"))
    bars_ts = np.array([b.ts_event for b in bars_nt])
    bars_h = np.array([float(b.high) for b in bars_nt])
    bars_l = np.array([float(b.low) for b in bars_nt])
    bars_o = np.array([float(b.open) for b in bars_nt])
    bars_c = np.array([float(b.close) for b in bars_nt])
    print(f"  {len(bars_nt):,} bars")

    # Bracket combos to test
    BRACKETS = [
        (1.00, 1.00),
        (1.25, 1.00),
        (1.50, 1.00),
        (2.00, 1.00),
        (1.00, 0.75),
        (1.25, 0.75),
        (1.50, 0.75),
    ]
    # Stall exits to test (overlay on each bracket)
    STALL_RULES = [
        ("none", lambda mfe_at, t_s: False),
        ("no_progress_60s", lambda mfe_at, t_s: t_s >= 60 and mfe_at <= 0),
        ("no_progress_90s", lambda mfe_at, t_s: t_s >= 90 and mfe_at <= 0),
        ("no_progress_120s", lambda mfe_at, t_s: t_s >= 120 and mfe_at <= 0),
        ("mfe_lt_025_60s", lambda mfe_at, t_s: t_s >= 60 and mfe_at < 0.25),
        ("mfe_lt_050_90s", lambda mfe_at, t_s: t_s >= 90 and mfe_at < 0.50),
        ("mfe_lt_050_120s", lambda mfe_at, t_s: t_s >= 120 and mfe_at < 0.50),
    ]

    # Walk each trade
    print("\nWalking trades...")
    t0 = time.time()
    rows = []
    for _, row in slice_.iterrows():
        fp = float(row["fill_price"])
        atr = float(row["atr"])
        d = int(row["direction"])
        fill_ts = int(row["fill_ts_ns"])
        regime_exit_ts = int(row["regime_exit_ts_ns"])
        max_walk_ts = min(fill_ts + 30 * 60 * int(1e9), regime_exit_ts)
        # Get bars
        lo = np.searchsorted(bars_ts, fill_ts, side="left")
        hi = np.searchsorted(bars_ts, max_walk_ts, side="left")
        if hi <= lo:
            continue
        seg_h = bars_h[lo:hi]
        seg_l = bars_l[lo:hi]
        seg_ts = bars_ts[lo:hi]

        # Compute running MFE/MAE in ATR units
        if d == 1:
            mfe_atr_seq = (seg_h - fp) / atr
            mae_atr_seq = (fp - seg_l) / atr
        else:
            mfe_atr_seq = (fp - seg_l) / atr
            mae_atr_seq = (seg_h - fp) / atr
        # Running peaks
        peak_mfe = np.maximum.accumulate(mfe_atr_seq)
        peak_mae = np.maximum.accumulate(mae_atr_seq)
        # Time elapsed at each bar (seconds)
        elapsed_s = (seg_ts - fill_ts) / 1e9
        # Did regime exit happen during this walk?
        regime_exited = (max_walk_ts == regime_exit_ts)
        regime_exit_elapsed_s = ((regime_exit_ts - fill_ts) / 1e9
                                    if regime_exited else float("inf"))
        # End-of-walk close price (for stall/regime-exit PnL)
        end_close = float(bars_c[lo + hi - lo - 1])

        # For each bracket, find resolution
        for pt_R, sl_R in BRACKETS:
            pt_hit_mask = peak_mfe >= pt_R
            sl_hit_mask = peak_mae >= sl_R
            pt_hit_idx = (pt_hit_mask.argmax()
                            if pt_hit_mask.any() else len(seg_h) + 1)
            sl_hit_idx = (sl_hit_mask.argmax()
                            if sl_hit_mask.any() else len(seg_h) + 1)

            for stall_name, stall_fn in STALL_RULES:
                # Determine first event: PT, SL, stall, regime, or none
                # Stall trigger: scan bars in order
                stall_idx = None
                if stall_name != "none":
                    # Need to evaluate at each bar: did stall trigger?
                    # Stall takes peak_mfe and elapsed
                    for i in range(len(seg_h)):
                        if stall_fn(peak_mfe[i], elapsed_s[i]):
                            stall_idx = i
                            break

                # Find earliest event
                events = []
                if pt_hit_idx < len(seg_h):
                    events.append(("pt", pt_hit_idx,
                                    pt_R * atr * NQ_MULT
                                    - COMMISSION - TICK_COST))
                if sl_hit_idx < len(seg_h):
                    events.append(("sl", sl_hit_idx,
                                    -sl_R * atr * NQ_MULT
                                    - COMMISSION - 2 * TICK_COST))
                if stall_idx is not None:
                    # Stall exit at current bar's close, no PT/SL slip
                    stall_close = float(bars_c[lo + stall_idx])
                    stall_pnl = ((stall_close - fp) * d * NQ_MULT
                                  - COMMISSION - TICK_COST)
                    events.append(("stall", stall_idx, stall_pnl))
                if regime_exited:
                    # regime exit at end_close (the bar at regime_exit_ts)
                    regime_pnl = ((end_close - fp) * d * NQ_MULT
                                   - COMMISSION - TICK_COST)
                    events.append(("regime", len(seg_h) - 1, regime_pnl))

                if not events:
                    # Truly unresolved — exit at last close (timeout)
                    timeout_pnl = ((end_close - fp) * d * NQ_MULT
                                     - COMMISSION - TICK_COST)
                    outcome = "timeout"
                    pnl = timeout_pnl
                    res_s = elapsed_s[-1]
                else:
                    # Earliest event wins
                    events.sort(key=lambda x: x[1])
                    outcome, idx, pnl = events[0]
                    res_s = float(elapsed_s[idx])

                rows.append({
                    "flip_ts": int(row["flip_bar_ts_event"]),
                    "direction": d,
                    "atr": atr,
                    "pt_R": pt_R,
                    "sl_R": sl_R,
                    "stall_rule": stall_name,
                    "outcome": outcome,
                    "pnl_dollars": pnl,
                    "resolution_s": res_s,
                    "regime_exited_window": regime_exited,
                    "regime_exit_s": regime_exit_elapsed_s,
                    "peak_mfe_atr_at_resolution":
                        float(peak_mfe[min(int(res_s), len(peak_mfe) - 1)
                                          if int(res_s) < len(peak_mfe)
                                          else -1]),
                })
    elapsed = time.time() - t0
    print(f"  Walked {len(slice_):,} trades, "
           f"{len(rows):,} outcome rows ({elapsed:.0f}s)")

    df = pd.DataFrame(rows)
    df.to_parquet(OUT / "bracket_exit_outcomes.parquet", index=False)
    print(f"  Saved: {OUT / 'bracket_exit_outcomes.parquet'}")

    # Also save a summary of regime-exit actual PnLs (for §4)
    print("\nComputing regime-exit reality stats...")
    # Use first bracket combo with stall=none to get one row per trade
    base_df = df[(df["pt_R"] == 1.0) & (df["sl_R"] == 1.0)
                  & (df["stall_rule"] == "none")]
    # For trades that DIDN'T resolve via PT/SL, their outcome reflects
    # regime-exit or timeout
    re_mask = base_df["outcome"].isin(["regime", "timeout"])
    if re_mask.any():
        re = base_df[re_mask].copy()
        re["actual_atr_pnl"] = re["pnl_dollars"] / (re["atr"] * NQ_MULT)
        print(f"  Regime/timeout exits: {len(re):,}")
        print(f"    Median ATR PnL: {re['actual_atr_pnl'].median():.4f}")
        print(f"    Mean ATR PnL:   {re['actual_atr_pnl'].mean():.4f}")
        print(f"    % positive:     "
               f"{100*(re['pnl_dollars'] > 0).mean():.1f}%")
        print(f"    % worse than -0.5 ATR: "
               f"{100*(re['actual_atr_pnl'] < -0.5).mean():.1f}%")
        print(f"    % worse than -1.0 ATR: "
               f"{100*(re['actual_atr_pnl'] < -1.0).mean():.1f}%")
        re.to_parquet(OUT / "regime_exit_reality.parquet", index=False)


if __name__ == "__main__":
    main()
