"""On RtB trades only, test trailing-stop exits.

Population: no-cat + BE=2.5 baseline. We slice to RtB trades
(armed cleanly with no MAE before +2.5), then re-simulate exits
with three strategies:

  BASE: BE stop at entry +1 tick (existing behavior)
  A:    1 contract with trailing stop = max(entry+1tick,
        MFE_peak - 2.5)
  B:    2 contracts (C1 original + C2 added at +2.5).
        Single SHARED trailing stop = max(entry+1tick,
        MFE_peak - 2.5). Both contracts exit together when
        the shared stop or shared target hits.
        C2 net PnL is computed off its own entry price
        (entry + 2.5) at the common exit price, so C2 takes
        a loss when stop fires near BE.

Trail distance = 2.5 pts behind absolute MFE peak.
Same target (next-level - 10 ticks).

For non-RtB trades, baseline behavior is unchanged. Reported
totals add the unchanged non-RtB pnl to whichever RtB strategy
we're measuring, so the year totals are comparable.
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
    "studies/level_momentum_continuation/results_rtb_trail")
OUT.mkdir(parents=True, exist_ok=True)
NQ_DOLLAR_PER_PT = 20.0
COMMISSION_PTS = 0.25
TRAIL_DIST = 2.5  # pts behind absolute peak
ADD_AT_MFE = 2.5  # pts above entry where C2 enters


def simulate_rtb_trail(entry_idx, di, entry_px, target,
                              eod_idx, opens, highs, lows, closes,
                              two_contracts):
    """Simulate one RtB trade with trailing stop(s).

    For long (di=1):
      - Track running MFE peak.
      - C1 trail = max(entry + 1tick, peak - TRAIL_DIST)
      - If two_contracts: C2 entered at price entry + 2.5
        when MFE first reaches 2.5. C2 trail = max(c2_entry +
        1tick, peak - TRAIL_DIST).
      - Exit C1: low <= c1_stop OR high >= target
      - Exit C2: low <= c2_stop OR high >= target (same target)
      - EOD flat at eod_idx for any unfilled contract.

    Returns dict with c1_pnl_net, c2_pnl_net (None if not used).
    """
    n = len(opens)
    last = min(eod_idx, n - 1)
    if entry_idx >= n or last < entry_idx: return None

    sli_h = highs[entry_idx : last + 1]
    sli_l = lows[entry_idx : last + 1]
    sli_c = closes[entry_idx : last + 1]
    nbars = len(sli_h)
    if nbars == 0: return None

    floor_c1 = (entry_px + TICK_SIZE if di == 1 else
                       entry_px - TICK_SIZE)
    c2_entry = (entry_px + ADD_AT_MFE if di == 1 else
                       entry_px - ADD_AT_MFE)
    floor_c2 = (c2_entry + TICK_SIZE if di == 1 else
                       c2_entry - TICK_SIZE)

    # Single SHARED stop tied to C1's level. Both contracts
    # exit together at the common stop / target / EOD.
    # Stop active starting (c1_armed_at + delay).
    BE_DELAY = 1
    if di == 1:
        peak = np.maximum.accumulate(sli_h)
        shared_stop = np.maximum(floor_c1, peak - TRAIL_DIST)
        c1_armed_mask = (peak - entry_px) >= 2.5
        c1_armed_at = (int(np.argmax(c1_armed_mask)) if
                              c1_armed_mask.any() else -1)
        c2_armed_mask = (peak - entry_px) >= ADD_AT_MFE
        c2_armed_at = (int(np.argmax(c2_armed_mask)) if
                              c2_armed_mask.any() else -1)
        if c1_armed_at >= 0:
            active_from = c1_armed_at + BE_DELAY
            if active_from < nbars:
                hit = sli_l[active_from:] <= shared_stop[active_from:]
                stop_idx = (active_from + int(np.argmax(hit))
                                if hit.any() else -1)
            else:
                stop_idx = -1
        else:
            stop_idx = -1
        tgt_hit = sli_h >= target
        tgt_idx = (int(np.argmax(tgt_hit)) if tgt_hit.any() else -1)
    else:
        peak = np.minimum.accumulate(sli_l)
        shared_stop = np.minimum(floor_c1, peak + TRAIL_DIST)
        c1_armed_mask = (entry_px - peak) >= 2.5
        c1_armed_at = (int(np.argmax(c1_armed_mask)) if
                              c1_armed_mask.any() else -1)
        c2_armed_mask = (entry_px - peak) >= ADD_AT_MFE
        c2_armed_at = (int(np.argmax(c2_armed_mask)) if
                              c2_armed_mask.any() else -1)
        if c1_armed_at >= 0:
            active_from = c1_armed_at + BE_DELAY
            if active_from < nbars:
                hit = sli_h[active_from:] >= shared_stop[active_from:]
                stop_idx = (active_from + int(np.argmax(hit))
                                if hit.any() else -1)
            else:
                stop_idx = -1
        else:
            stop_idx = -1
        tgt_hit = sli_l <= target
        tgt_idx = (int(np.argmax(tgt_hit)) if tgt_hit.any() else -1)

    # Resolve common exit
    candidates = []
    if stop_idx >= 0:
        candidates.append(
            (stop_idx, "trail", float(shared_stop[stop_idx])))
    if tgt_idx >= 0:
        candidates.append((tgt_idx, "win", target))
    if not candidates:
        outcome = "eod_flat"
        exit_idx = nbars - 1
        exit_px = float(sli_c[-1])
    else:
        candidates.sort(key=lambda x: (x[0],
            0 if x[1] == "trail" else 1))
        exit_idx, outcome, exit_px = candidates[0]

    # C1 PnL
    c1_gross = (exit_px - entry_px) * di
    c1_net = c1_gross - COMMISSION_PTS
    c1_outcome = outcome

    # C2 PnL: filled at c2_armed_at, exits at common exit_px.
    # C2 only fires if c2_armed_at occurs at or before exit_idx.
    if not two_contracts or c2_armed_at < 0 or c2_armed_at > exit_idx:
        c2_net = None
        c2_outcome = "no_fill" if two_contracts else None
        c2_exit_idx = None
    else:
        c2_gross = (exit_px - c2_entry) * di
        c2_net = c2_gross - COMMISSION_PTS
        c2_outcome = outcome
        c2_exit_idx = exit_idx

    return {
        "chain_exit_global": entry_idx + exit_idx,
        "c1_outcome": c1_outcome,
        "c1_pnl_net": c1_net,
        "c2_outcome": c2_outcome,
        "c2_pnl_net": c2_net,
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
        bars_1m_reset = bars_1m.reset_index(drop=False)
        triggers = detect_triggers(bars_1m_reset)

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

        # First pass: re-run no-cat + BE=2.5 baseline, identify
        # which trades are RtB (clean armer, MAE strictly before
        # arm = false meaning max_mae_at >= arm_at).
        trades = []
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
            r = simulate_trade_1s(e1s, di, entry_px, target,
                                           sl_px, be_px, 2.5, eod_idx,
                                           opens_1s, highs_1s,
                                           lows_1s, closes_1s)
            if r is None: continue
            xi = min(int(r["exit_idx_global"]),
                          len(highs_1s) - 1)
            sli_h = highs_1s[e1s : xi + 1]
            sli_l = lows_1s[e1s : xi + 1]
            if di == 1:
                mae_series = entry_px - sli_l
                mfe_series = sli_h - entry_px
            else:
                mae_series = sli_h - entry_px
                mfe_series = entry_px - sli_l
            mae_at = (int(np.argmax(mae_series)) if
                            len(mae_series) else -1)
            arm_mask = mfe_series >= 2.5
            arm_at = (int(np.argmax(arm_mask)) if
                            arm_mask.any() else -1)
            is_rtb = (arm_at >= 0 and mae_at >= arm_at)

            trades.append({
                "entry_idx": e1s, "di": di,
                "entry_px": entry_px, "target": target,
                "eod_idx": eod_idx,
                "is_rtb": is_rtb,
                "base_pnl_net": r["pnl_net"],
                "base_outcome": r["outcome"],
                "base_exit_idx": int(r["exit_idx_global"]),
            })
            last_chain_exit = r["exit_idx_global"]

        df = pd.DataFrame(trades)
        n_total = len(df)
        n_rtb = int(df["is_rtb"].sum())
        print(f"  Total: {n_total:,}, RtB: {n_rtb:,} "
              f"({100*n_rtb/n_total:.1f}%)")

        # Replay RtB rows under Strategy A and Strategy B.
        # Non-RtB rows keep base_pnl_net unchanged.
        a_pnls = []  # per-trade total pnl under Strategy A
        b_pnls = []  # per-trade total pnl under Strategy B
        a_outcomes = []
        b_c1_outcomes = []
        b_c2_outcomes = []
        b_c2_filled = 0

        for _, row in df.iterrows():
            if not row["is_rtb"]:
                a_pnls.append(row["base_pnl_net"])
                b_pnls.append(row["base_pnl_net"])
                a_outcomes.append("non_rtb")
                b_c1_outcomes.append("non_rtb")
                b_c2_outcomes.append("non_rtb")
                continue
            # Strategy A: 1 contract trailing
            ra = simulate_rtb_trail(
                int(row["entry_idx"]), int(row["di"]),
                float(row["entry_px"]), float(row["target"]),
                int(row["eod_idx"]),
                opens_1s, highs_1s, lows_1s, closes_1s,
                two_contracts=False)
            if ra is None:
                a_pnls.append(row["base_pnl_net"])
                a_outcomes.append("none")
            else:
                a_pnls.append(ra["c1_pnl_net"])
                a_outcomes.append(ra["c1_outcome"])
            # Strategy B: 2 contracts
            rb = simulate_rtb_trail(
                int(row["entry_idx"]), int(row["di"]),
                float(row["entry_px"]), float(row["target"]),
                int(row["eod_idx"]),
                opens_1s, highs_1s, lows_1s, closes_1s,
                two_contracts=True)
            if rb is None:
                b_pnls.append(row["base_pnl_net"])
                b_c1_outcomes.append("none")
                b_c2_outcomes.append("none")
            else:
                tot = rb["c1_pnl_net"]
                if rb["c2_pnl_net"] is not None:
                    tot += rb["c2_pnl_net"]
                    b_c2_filled += 1
                b_pnls.append(tot)
                b_c1_outcomes.append(rb["c1_outcome"])
                b_c2_outcomes.append(rb["c2_outcome"]
                                                or "no_fill")

        df["a_pnl"] = a_pnls
        df["b_pnl"] = b_pnls
        df["a_out"] = a_outcomes
        df["b_c1_out"] = b_c1_outcomes
        df["b_c2_out"] = b_c2_outcomes

        rtb = df[df["is_rtb"]]
        non_rtb = df[~df["is_rtb"]]

        # Aggregate within RtB
        base_rtb_total = float(rtb["base_pnl_net"].sum())
        a_rtb_total = float(rtb["a_pnl"].sum())
        b_rtb_total = float(rtb["b_pnl"].sum())

        # Overall (RtB + non-RtB) totals for each strategy
        non_rtb_total = float(non_rtb["base_pnl_net"].sum())
        base_overall = float(df["base_pnl_net"].sum())
        a_overall = a_rtb_total + non_rtb_total
        b_overall = b_rtb_total + non_rtb_total

        print(f"\n[{year}] === RtB-only PnL (n={len(rtb):,}) ===")
        print(f"  BASE  total: {base_rtb_total:+.2f} pts | "
              f"${base_rtb_total*NQ_DOLLAR_PER_PT:+,.0f} | "
              f"mean {base_rtb_total/len(rtb):+.3f}")
        print(f"  A     total: {a_rtb_total:+.2f} pts | "
              f"${a_rtb_total*NQ_DOLLAR_PER_PT:+,.0f} | "
              f"mean {a_rtb_total/len(rtb):+.3f}")
        print(f"  B     total: {b_rtb_total:+.2f} pts | "
              f"${b_rtb_total*NQ_DOLLAR_PER_PT:+,.0f} | "
              f"mean {b_rtb_total/len(rtb):+.3f}")
        print(f"  Δ A vs BASE: ${(a_rtb_total-base_rtb_total)*NQ_DOLLAR_PER_PT:+,.0f}")
        print(f"  Δ B vs BASE: ${(b_rtb_total-base_rtb_total)*NQ_DOLLAR_PER_PT:+,.0f}")
        print(f"  Δ B vs A:    ${(b_rtb_total-a_rtb_total)*NQ_DOLLAR_PER_PT:+,.0f}")
        print(f"  C2 filled in B: {b_c2_filled:,} of "
              f"{len(rtb):,} RtB trades "
              f"({100*b_c2_filled/len(rtb):.1f}%)")

        # Outcome breakdowns
        print(f"\n[{year}] Strategy A RtB outcomes:")
        for k, v in rtb["a_out"].value_counts().items():
            print(f"  {k:12s} {v:>5,} ({100*v/len(rtb):4.1f}%)")
        print(f"\n[{year}] Strategy B RtB C1 outcomes:")
        for k, v in rtb["b_c1_out"].value_counts().items():
            print(f"  {k:12s} {v:>5,} ({100*v/len(rtb):4.1f}%)")
        print(f"\n[{year}] Strategy B RtB C2 outcomes:")
        for k, v in rtb["b_c2_out"].value_counts().items():
            print(f"  {k:12s} {v:>5,} ({100*v/len(rtb):4.1f}%)")

        print(f"\n[{year}] === OVERALL (RtB + non-RtB unchanged) ===")
        print(f"  BASE  overall: ${base_overall*NQ_DOLLAR_PER_PT:>+11,.0f}")
        print(f"  A     overall: ${a_overall*NQ_DOLLAR_PER_PT:>+11,.0f}  "
              f"(Δ ${(a_overall-base_overall)*NQ_DOLLAR_PER_PT:+,.0f})")
        print(f"  B     overall: ${b_overall*NQ_DOLLAR_PER_PT:>+11,.0f}  "
              f"(Δ ${(b_overall-base_overall)*NQ_DOLLAR_PER_PT:+,.0f})")

        summary[year] = {
            "n_rtb": len(rtb), "n_total": n_total,
            "base_overall": base_overall * NQ_DOLLAR_PER_PT,
            "a_overall": a_overall * NQ_DOLLAR_PER_PT,
            "b_overall": b_overall * NQ_DOLLAR_PER_PT,
            "rtb_base": base_rtb_total * NQ_DOLLAR_PER_PT,
            "rtb_a": a_rtb_total * NQ_DOLLAR_PER_PT,
            "rtb_b": b_rtb_total * NQ_DOLLAR_PER_PT,
        }

        df.to_csv(OUT / f"trades_{year}.csv", index=False)

    print(f"\n{'='*70}\nSUMMARY:")
    print(f"{'Year':<6} {'n_rtb':<8} {'BASE rtb':>13} "
          f"{'A rtb':>13} {'B rtb':>13} "
          f"{'Δ A':>10} {'Δ B':>10}")
    for yr, s in summary.items():
        da = s["rtb_a"] - s["rtb_base"]
        db = s["rtb_b"] - s["rtb_base"]
        print(f"{yr:<6} {s['n_rtb']:<8,} "
              f"${s['rtb_base']:>+11,.0f} "
              f"${s['rtb_a']:>+11,.0f} "
              f"${s['rtb_b']:>+11,.0f} "
              f"${da:>+8,.0f} ${db:>+8,.0f}")


if __name__ == "__main__":
    main()
