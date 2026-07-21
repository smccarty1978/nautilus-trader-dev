"""V-recovery: add C2 at the breach-level re-cross.

Trigger: trade that DIPPED below breach level then RE-CROSSED
breach + 1 tick going back up (long, mirrored for short).
At re-cross, fill C2 at breach_level + 1 tick (long).

Stop management:
  - Pre-arm (C1 MFE < 2.5): NO stop — both contracts hold.
  - Arm trigger: C1 MFE >= 2.5 from original entry.
  - At arm: shared stop = avg(C1_entry, C2_entry) + 1 tick.
  - Post-arm: trail = max(avg + 1tick, peak - 2.5) (long).
  - Exit on shared stop / target / EOD.

Trades with NO V-recovery use BASE behavior (C1 only with
BE-stop at entry +1 tick after MFE >= 2.5). This makes the
strategy comparable on the same population.
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from studies.level_momentum_continuation.level_study import (
    load_v0_1s, detect_triggers, annotate_sessions_ct,
)
from studies.level_momentum_continuation.analyze_1s_precision import (
    annotate_sessions_1s, filter_roll_window_1s,
    map_1m_trigger_to_1s_entry, precompute_eod_1s,
)
from studies.level_momentum_continuation.analyze_sl_be_grid_1s import (
    simulate_trade_1s, NO_CAT_SENTINEL,
    BE_STOP_OFFSET_TICKS, TICK_SIZE,
)

OUT = Path(
    "studies/level_momentum_continuation/results_vshape_recross")
OUT.mkdir(parents=True, exist_ok=True)
NQ_DOLLAR_PER_PT = 20.0
COMMISSION_PTS = 0.25
TRAIL_DIST = 2.5
ARM_MFE = 2.5  # C1 MFE that arms shared BE


def find_recross(opens, highs, lows, entry_idx, last_idx,
                          breach_level, di):
    """Return 1s idx where re-cross fires, or -1.

    Long:  low <= breach_level seen, THEN high >= breach + tick
    Short: high >= breach_level seen, THEN low <= breach - tick
    """
    if di == 1:
        thresh_recross = breach_level + TICK_SIZE
        dipped = False
        for k in range(entry_idx, last_idx + 1):
            if not dipped and lows[k] <= breach_level:
                dipped = True
                continue  # cant fire same bar as dip
            if dipped and highs[k] >= thresh_recross:
                return k
        return -1
    else:
        thresh_recross = breach_level - TICK_SIZE
        rallied = False
        for k in range(entry_idx, last_idx + 1):
            if not rallied and highs[k] >= breach_level:
                rallied = True
                continue
            if rallied and lows[k] <= thresh_recross:
                return k
        return -1


def simulate_recross_strategy(entry_idx, di, entry_px,
                                          breach_level, target,
                                          eod_idx, opens, highs,
                                          lows, closes):
    """Returns dict with c1/c2 outcome + pnl, plus chain_exit."""
    n = len(opens)
    last = min(eod_idx, n - 1)
    if entry_idx >= n or last < entry_idx: return None

    # Detect re-cross
    c2_idx = find_recross(opens, highs, lows, entry_idx, last,
                                    breach_level, di)
    has_v = c2_idx >= 0

    sli_h = highs[entry_idx : last + 1]
    sli_l = lows[entry_idx : last + 1]
    sli_c = closes[entry_idx : last + 1]
    nbars = len(sli_h)

    c2_local = c2_idx - entry_idx if has_v else -1
    c2_entry = (breach_level + TICK_SIZE if di == 1
                       else breach_level - TICK_SIZE) if has_v else None

    if di == 1:
        peak = np.maximum.accumulate(sli_h)
        c1_arm_mask = (peak - entry_px) >= ARM_MFE
        c1_armed_at = (int(np.argmax(c1_arm_mask)) if
                              c1_arm_mask.any() else -1)
    else:
        peak = np.minimum.accumulate(sli_l)
        c1_arm_mask = (entry_px - peak) >= ARM_MFE
        c1_armed_at = (int(np.argmax(c1_arm_mask)) if
                              c1_arm_mask.any() else -1)

    # Determine stop trajectory
    # If has_v AND c1_armed_at >= 0:
    #   shared_floor = avg + 1 tick (long); avg - 1 tick (short)
    #   shared_stop = max(floor, peak - 2.5) (long); min for short
    #   active_from = c1_armed_at + 1 (BE delay)
    # If has_v but C1 never arms: NO stop (ride to target/EOD)
    # If no V-recovery: BASE single-contract behavior (BE-stop
    #   at entry +1 tick after C1 armed).

    BE_DELAY = 1
    floor_c1_only = (entry_px + TICK_SIZE if di == 1
                              else entry_px - TICK_SIZE)

    if has_v:
        avg_entry = (entry_px + c2_entry) / 2
        shared_floor = (avg_entry + TICK_SIZE if di == 1
                                else avg_entry - TICK_SIZE)
        if di == 1:
            shared_stop = np.maximum(shared_floor,
                                                  peak - TRAIL_DIST)
        else:
            shared_stop = np.minimum(shared_floor,
                                                  peak + TRAIL_DIST)

        if c1_armed_at >= 0:
            af = c1_armed_at + BE_DELAY
            if af < nbars:
                if di == 1:
                    hit = sli_l[af:] <= shared_stop[af:]
                else:
                    hit = sli_h[af:] >= shared_stop[af:]
                stop_idx = (af + int(np.argmax(hit))
                                if hit.any() else -1)
            else:
                stop_idx = -1
        else:
            # No stop ever
            stop_idx = -1
    else:
        # BASE C1-only behavior: BE-stop at entry + 1 tick
        # active after C1 armed + 1 bar delay.
        if c1_armed_at >= 0:
            af = c1_armed_at + BE_DELAY
            if af < nbars:
                if di == 1:
                    hit = sli_l[af:] <= floor_c1_only
                else:
                    hit = sli_h[af:] >= floor_c1_only
                stop_idx = (af + int(np.argmax(hit))
                                if hit.any() else -1)
            else:
                stop_idx = -1
        else:
            stop_idx = -1

    # Target check
    if di == 1:
        tgt_hit = sli_h >= target
    else:
        tgt_hit = sli_l <= target
    tgt_idx = int(np.argmax(tgt_hit)) if tgt_hit.any() else -1

    # Resolve common exit
    cs = []
    if stop_idx >= 0:
        if has_v:
            sp = float(shared_stop[stop_idx])
        else:
            sp = floor_c1_only
        cs.append((stop_idx, "stop", sp))
    if tgt_idx >= 0:
        cs.append((tgt_idx, "win", target))
    if not cs:
        outcome = "eod_flat"
        exit_idx = nbars - 1
        exit_px = float(sli_c[-1])
    else:
        cs.sort(key=lambda x: (x[0],
            0 if x[1] == "stop" else 1))
        exit_idx, outcome, exit_px = cs[0]

    c1_net = (exit_px - entry_px) * di - COMMISSION_PTS

    # C2: only if V-recovery happened AND c2 fired before exit
    if has_v and c2_local <= exit_idx:
        c2_net = (exit_px - c2_entry) * di - COMMISSION_PTS
        c2_outcome = outcome
    else:
        c2_net = None
        c2_outcome = "no_fill"

    return {
        "has_v": has_v,
        "c1_outcome": outcome,
        "c1_pnl_net": c1_net,
        "c2_outcome": c2_outcome,
        "c2_pnl_net": c2_net,
        "exit_idx_global": entry_idx + exit_idx,
    }


def main():
    summary = {}
    for year in (2024, 2025):
        print(f"\n{'='*70}\n[{year}] loading + triggers...")
        bars_1s = load_v0_1s(
            Path(f"data/raw/NQ_v0_1s_{year}.parquet"))
        bars_1s = annotate_sessions_1s(bars_1s)
        bars_1s = filter_roll_window_1s(bars_1s, 3)
        bars_1m = bars_1s[
            ["open", "high", "low", "close", "volume"]
        ].resample("1min", label="right",
                          closed="right").agg({
            "open": "first", "high": "max",
            "low": "min", "close": "last",
            "volume": "sum"}).dropna(
            subset=["open", "high", "low", "close"])
        bars_1m = annotate_sessions_ct(bars_1m)
        triggers = detect_triggers(
            bars_1m.reset_index(drop=False))

        bars_1s_reset = bars_1s.reset_index(drop=False)
        opens_1s = bars_1s_reset["open"].values
        highs_1s = bars_1s_reset["high"].values
        lows_1s = bars_1s_reset["low"].values
        closes_1s = bars_1s_reset["close"].values
        ts_close_1s_pd = pd.DatetimeIndex(
            bars_1s_reset["ts_close"])
        if ts_close_1s_pd.tz is None:
            ts_close_1s_pd = ts_close_1s_pd.tz_localize("UTC")
        else:
            ts_close_1s_pd = ts_close_1s_pd.tz_convert("UTC")
        next_eod = precompute_eod_1s(bars_1s_reset)
        be_off = BE_STOP_OFFSET_TICKS * TICK_SIZE

        rows = []
        last_chain_exit = -1
        for tr in triggers:
            ts = (pd.Timestamp(tr.bar_ts_close).tz_convert("UTC")
                  if pd.Timestamp(tr.bar_ts_close).tz is not None
                  else pd.Timestamp(tr.bar_ts_close, tz="UTC"))
            e1s = map_1m_trigger_to_1s_entry(ts, ts_close_1s_pd)
            if e1s < 0: continue
            if e1s <= last_chain_exit: continue
            di = tr.direction
            entry_px = float(opens_1s[e1s])
            sl_px = entry_px - NO_CAT_SENTINEL if di == 1 else (
                entry_px + NO_CAT_SENTINEL)
            be_px = (entry_px + be_off) if di == 1 else (
                entry_px - be_off)
            target = float(tr.target)
            eod_idx = int(next_eod[e1s])
            breach = float(tr.breach_level)

            # BASE simulation
            r_base = simulate_trade_1s(
                e1s, di, entry_px, target,
                sl_px, be_px, 2.5, eod_idx,
                opens_1s, highs_1s, lows_1s, closes_1s)
            if r_base is None: continue

            # New strategy
            r_new = simulate_recross_strategy(
                e1s, di, entry_px, breach, target, eod_idx,
                opens_1s, highs_1s, lows_1s, closes_1s)
            if r_new is None: continue

            new_pnl = r_new["c1_pnl_net"]
            if r_new["c2_pnl_net"] is not None:
                new_pnl += r_new["c2_pnl_net"]

            rows.append({
                "entry_idx": e1s, "di": di,
                "entry_px": entry_px,
                "breach": breach,
                "base_pnl_net": r_base["pnl_net"],
                "base_outcome": r_base["outcome"],
                "has_v": r_new["has_v"],
                "new_pnl_net": new_pnl,
                "new_c1_outcome": r_new["c1_outcome"],
                "new_c2_outcome": r_new["c2_outcome"],
                "new_c2_filled":
                    r_new["c2_pnl_net"] is not None,
            })
            last_chain_exit = max(
                int(r_base["exit_idx_global"]),
                int(r_new["exit_idx_global"]))

        df = pd.DataFrame(rows)
        n_total = len(df)
        n_v = int(df["has_v"].sum())
        n_c2 = int(df["new_c2_filled"].sum())
        print(f"  Total trades: {n_total:,}")
        print(f"  V-recovery (re-cross detected): {n_v:,} "
              f"({100*n_v/n_total:.1f}%)")
        print(f"  C2 actually filled: {n_c2:,} "
              f"({100*n_c2/n_total:.1f}%)")

        # Aggregate
        base_total = float(df["base_pnl_net"].sum())
        new_total = float(df["new_pnl_net"].sum())
        delta = new_total - base_total

        # Slice by has_v
        v = df[df["has_v"]]
        nv = df[~df["has_v"]]
        v_base = float(v["base_pnl_net"].sum())
        v_new = float(v["new_pnl_net"].sum())
        nv_base = float(nv["base_pnl_net"].sum())
        nv_new = float(nv["new_pnl_net"].sum())

        print(f"\n[{year}] V-recovery population (n={len(v):,}):")
        print(f"  BASE PnL: ${v_base*NQ_DOLLAR_PER_PT:>+12,.0f} "
              f"(mean {v_base/len(v):+.3f})")
        print(f"  NEW  PnL: ${v_new*NQ_DOLLAR_PER_PT:>+12,.0f} "
              f"(mean {v_new/len(v):+.3f})")
        print(f"  Δ (V):    ${(v_new-v_base)*NQ_DOLLAR_PER_PT:>+12,.0f}")

        print(f"\n[{year}] Non-V population (n={len(nv):,}):")
        print(f"  BASE PnL: ${nv_base*NQ_DOLLAR_PER_PT:>+12,.0f}")
        print(f"  NEW  PnL: ${nv_new*NQ_DOLLAR_PER_PT:>+12,.0f}")
        print(f"  Δ (non-V): ${(nv_new-nv_base)*NQ_DOLLAR_PER_PT:>+12,.0f}")

        print(f"\n[{year}] OVERALL:")
        print(f"  BASE: ${base_total*NQ_DOLLAR_PER_PT:>+12,.0f}")
        print(f"  NEW:  ${new_total*NQ_DOLLAR_PER_PT:>+12,.0f}")
        print(f"  Δ:    ${delta*NQ_DOLLAR_PER_PT:>+12,.0f}")

        # Outcome breakdown for V trades
        print(f"\n[{year}] V-trade NEW C1 outcomes:")
        for k, vc in v["new_c1_outcome"].value_counts().items():
            print(f"  {k:12s} {vc:>5,} ({100*vc/len(v):4.1f}%)")
        print(f"\n[{year}] V-trade NEW C2 outcomes:")
        for k, vc in v["new_c2_outcome"].value_counts().items():
            print(f"  {k:12s} {vc:>5,} ({100*vc/len(v):4.1f}%)")

        summary[year] = {
            "n_total": n_total, "n_v": n_v, "n_c2": n_c2,
            "base": base_total * NQ_DOLLAR_PER_PT,
            "new": new_total * NQ_DOLLAR_PER_PT,
            "v_base": v_base * NQ_DOLLAR_PER_PT,
            "v_new": v_new * NQ_DOLLAR_PER_PT,
            "nv_base": nv_base * NQ_DOLLAR_PER_PT,
            "nv_new": nv_new * NQ_DOLLAR_PER_PT,
        }
        df.to_csv(OUT / f"trades_{year}.csv", index=False)

    print(f"\n{'='*70}\nSUMMARY:")
    print(f"{'Year':<6} {'n_total':<8} {'n_v':<8} {'n_c2':<8} "
          f"{'BASE':>13} {'NEW':>13} {'Δ overall':>13}")
    for yr, s in summary.items():
        print(f"{yr:<6} {s['n_total']:<8,} {s['n_v']:<8,} "
              f"{s['n_c2']:<8,} "
              f"${s['base']:>+11,.0f} ${s['new']:>+11,.0f} "
              f"${s['new']-s['base']:>+11,.0f}")


if __name__ == "__main__":
    main()
