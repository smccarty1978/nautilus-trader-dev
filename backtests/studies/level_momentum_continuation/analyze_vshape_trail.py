"""On V-recovery trades only, test trailing-stop exits with
optional 2nd contract added at +2.5 MFE (after recovery).

V-shape (V-recovery) = trade that DIPPED first (max MAE before
arm), then recovered to +2.5 MFE. The +2.5 cross is the
'confirmation' moment — that's where C2 enters.

Strategies (each contract has its OWN trail stop and BE floor):

  BASE: 1 contract, BE stop at entry +1 tick.
  A:    1 contract with trailing stop = max(entry+1tick,
        MFE_peak - 2.5).
  B:    2 contracts (C1 original + C2 added at +2.5).
        - C1 stop = max(entry + 1tick, peak - 2.5)
        - C2 stop = max(entry + 2.5 + 1tick, peak - 2.5)
        Both target the next-level price.
        EACH contract managed independently.

Trail distance = 2.5 pts behind absolute MFE peak.
For non-V-shape trades, baseline is unchanged.
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
    "studies/level_momentum_continuation/results_vshape_trail")
OUT.mkdir(parents=True, exist_ok=True)
NQ_DOLLAR_PER_PT = 20.0
COMMISSION_PTS = 0.25
TRAIL_DIST = 2.5
ADD_AT_MFE = 2.5


def simulate_vshape_trail(entry_idx, di, entry_px, target,
                                  eod_idx, opens, highs, lows, closes,
                                  two_contracts):
    """Simulate one V-shape trade with trail (one or two
    INDEPENDENTLY-STOPPED contracts).

    For two_contracts=True:
      C2 entry = entry_px + 2.5 (or entry - 2.5 short)
      C1 trail = max(entry + 1tick, peak - 2.5)
      C2 trail = max(entry + 2.5 + 1tick, peak - 2.5)
      Stops/targets active after arm + 1 bar delay (each).
    """
    n = len(opens)
    last = min(eod_idx, n - 1)
    if entry_idx >= n or last < entry_idx: return None
    sli_h = highs[entry_idx : last + 1]
    sli_l = lows[entry_idx : last + 1]
    sli_c = closes[entry_idx : last + 1]
    nbars = len(sli_h)
    if nbars == 0: return None

    floor_c1 = (entry_px + TICK_SIZE if di == 1
                       else entry_px - TICK_SIZE)
    c2_entry = (entry_px + ADD_AT_MFE if di == 1
                       else entry_px - ADD_AT_MFE)
    floor_c2 = (c2_entry + TICK_SIZE if di == 1
                       else c2_entry - TICK_SIZE)
    BE_DELAY = 1

    if di == 1:
        peak = np.maximum.accumulate(sli_h)
        c1_stop = np.maximum(floor_c1, peak - TRAIL_DIST)
        c2_stop = np.maximum(floor_c2, peak - TRAIL_DIST)
        c1_armed_mask = (peak - entry_px) >= 2.5
        c1_armed_at = (int(np.argmax(c1_armed_mask)) if
                              c1_armed_mask.any() else -1)
        c2_armed_mask = (peak - entry_px) >= ADD_AT_MFE
        c2_armed_at = (int(np.argmax(c2_armed_mask)) if
                              c2_armed_mask.any() else -1)

        if c1_armed_at >= 0:
            af = c1_armed_at + BE_DELAY
            if af < nbars:
                hit = sli_l[af:] <= c1_stop[af:]
                c1_stop_idx = (af + int(np.argmax(hit))
                                      if hit.any() else -1)
            else:
                c1_stop_idx = -1
        else:
            c1_stop_idx = -1
        c1_tgt_hit = sli_h >= target
        c1_tgt_idx = (int(np.argmax(c1_tgt_hit)) if
                             c1_tgt_hit.any() else -1)

        if two_contracts and c2_armed_at >= 0:
            af = c2_armed_at + BE_DELAY
            if af < nbars:
                hit = sli_l[af:] <= c2_stop[af:]
                c2_stop_idx = (af + int(np.argmax(hit))
                                      if hit.any() else -1)
                c2_tgt_after = sli_h[af:] >= target
                c2_tgt_idx = (af + int(np.argmax(c2_tgt_after))
                                     if c2_tgt_after.any() else -1)
            else:
                c2_stop_idx = -1
                c2_tgt_idx = -1
        else:
            c2_stop_idx = -1
            c2_tgt_idx = -1
    else:
        peak = np.minimum.accumulate(sli_l)
        c1_stop = np.minimum(floor_c1, peak + TRAIL_DIST)
        c2_stop = np.minimum(floor_c2, peak + TRAIL_DIST)
        c1_armed_mask = (entry_px - peak) >= 2.5
        c1_armed_at = (int(np.argmax(c1_armed_mask)) if
                              c1_armed_mask.any() else -1)
        c2_armed_mask = (entry_px - peak) >= ADD_AT_MFE
        c2_armed_at = (int(np.argmax(c2_armed_mask)) if
                              c2_armed_mask.any() else -1)

        if c1_armed_at >= 0:
            af = c1_armed_at + BE_DELAY
            if af < nbars:
                hit = sli_h[af:] >= c1_stop[af:]
                c1_stop_idx = (af + int(np.argmax(hit))
                                      if hit.any() else -1)
            else:
                c1_stop_idx = -1
        else:
            c1_stop_idx = -1
        c1_tgt_hit = sli_l <= target
        c1_tgt_idx = (int(np.argmax(c1_tgt_hit)) if
                             c1_tgt_hit.any() else -1)

        if two_contracts and c2_armed_at >= 0:
            af = c2_armed_at + BE_DELAY
            if af < nbars:
                hit = sli_h[af:] >= c2_stop[af:]
                c2_stop_idx = (af + int(np.argmax(hit))
                                      if hit.any() else -1)
                c2_tgt_after = sli_l[af:] <= target
                c2_tgt_idx = (af + int(np.argmax(c2_tgt_after))
                                     if c2_tgt_after.any() else -1)
            else:
                c2_stop_idx = -1
                c2_tgt_idx = -1
        else:
            c2_stop_idx = -1
            c2_tgt_idx = -1

    # Resolve C1 exit
    cs = []
    if c1_stop_idx >= 0:
        cs.append((c1_stop_idx, "trail",
                       float(c1_stop[c1_stop_idx])))
    if c1_tgt_idx >= 0:
        cs.append((c1_tgt_idx, "win", target))
    if not cs:
        c1_outcome = "eod_flat"
        c1_exit_idx = nbars - 1
        c1_exit_px = float(sli_c[-1])
    else:
        cs.sort(key=lambda x: (x[0],
            0 if x[1] == "trail" else 1))
        c1_exit_idx, c1_outcome, c1_exit_px = cs[0]
    c1_net = (c1_exit_px - entry_px) * di - COMMISSION_PTS

    if not two_contracts or c2_armed_at < 0:
        c2_net = None
        c2_outcome = "no_fill" if two_contracts else None
        c2_exit_idx = None
    else:
        cs2 = []
        if c2_stop_idx >= 0:
            cs2.append((c2_stop_idx, "trail",
                            float(c2_stop[c2_stop_idx])))
        if c2_tgt_idx >= 0:
            cs2.append((c2_tgt_idx, "win", target))
        if not cs2:
            c2_outcome = "eod_flat"
            c2_exit_idx = nbars - 1
            c2_exit_px = float(sli_c[-1])
        else:
            cs2.sort(key=lambda x: (x[0],
                0 if x[1] == "trail" else 1))
            c2_exit_idx, c2_outcome, c2_exit_px = cs2[0]
        c2_net = (c2_exit_px - c2_entry) * di - COMMISSION_PTS

    chain_exit = c1_exit_idx
    if c2_exit_idx is not None:
        chain_exit = max(chain_exit, c2_exit_idx)
    return {
        "chain_exit_global": entry_idx + chain_exit,
        "c1_outcome": c1_outcome, "c1_pnl_net": c1_net,
        "c2_outcome": c2_outcome, "c2_pnl_net": c2_net,
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

        # Pass 1: classify trades from no-cat + BE=2.5 baseline
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
            # V-shape = armed AND max MAE strictly before arm
            is_v = (arm_at >= 0 and mae_at < arm_at)

            trades.append({
                "entry_idx": e1s, "di": di,
                "entry_px": entry_px, "target": target,
                "eod_idx": eod_idx,
                "is_v": is_v,
                "base_pnl_net": r["pnl_net"],
                "base_outcome": r["outcome"],
                "base_exit_idx": int(r["exit_idx_global"]),
            })
            last_chain_exit = r["exit_idx_global"]

        df = pd.DataFrame(trades)
        n_total = len(df)
        n_v = int(df["is_v"].sum())
        print(f"  Total: {n_total:,}, V-shape: {n_v:,} "
              f"({100*n_v/n_total:.1f}%)")

        # Pass 2: replay V-shape under A and B (distinct stops)
        a_pnls = []
        b_pnls = []
        a_outs = []
        b_c1_outs = []
        b_c2_outs = []
        b_c2_filled = 0

        for _, row in df.iterrows():
            if not row["is_v"]:
                a_pnls.append(row["base_pnl_net"])
                b_pnls.append(row["base_pnl_net"])
                a_outs.append("non_v")
                b_c1_outs.append("non_v")
                b_c2_outs.append("non_v")
                continue
            ra = simulate_vshape_trail(
                int(row["entry_idx"]), int(row["di"]),
                float(row["entry_px"]), float(row["target"]),
                int(row["eod_idx"]),
                opens_1s, highs_1s, lows_1s, closes_1s,
                two_contracts=False)
            if ra is None:
                a_pnls.append(row["base_pnl_net"])
                a_outs.append("none")
            else:
                a_pnls.append(ra["c1_pnl_net"])
                a_outs.append(ra["c1_outcome"])
            rb = simulate_vshape_trail(
                int(row["entry_idx"]), int(row["di"]),
                float(row["entry_px"]), float(row["target"]),
                int(row["eod_idx"]),
                opens_1s, highs_1s, lows_1s, closes_1s,
                two_contracts=True)
            if rb is None:
                b_pnls.append(row["base_pnl_net"])
                b_c1_outs.append("none")
                b_c2_outs.append("none")
            else:
                tot = rb["c1_pnl_net"]
                if rb["c2_pnl_net"] is not None:
                    tot += rb["c2_pnl_net"]
                    b_c2_filled += 1
                b_pnls.append(tot)
                b_c1_outs.append(rb["c1_outcome"])
                b_c2_outs.append(rb["c2_outcome"]
                                            or "no_fill")

        df["a_pnl"] = a_pnls
        df["b_pnl"] = b_pnls
        df["a_out"] = a_outs
        df["b_c1_out"] = b_c1_outs
        df["b_c2_out"] = b_c2_outs

        v = df[df["is_v"]]
        non_v = df[~df["is_v"]]

        base_v_total = float(v["base_pnl_net"].sum())
        a_v_total = float(v["a_pnl"].sum())
        b_v_total = float(v["b_pnl"].sum())
        non_v_total = float(non_v["base_pnl_net"].sum())
        base_overall = float(df["base_pnl_net"].sum())
        a_overall = a_v_total + non_v_total
        b_overall = b_v_total + non_v_total

        print(f"\n[{year}] === V-shape only PnL (n={len(v):,}) ===")
        print(f"  BASE  total: {base_v_total:+.2f} pts | "
              f"${base_v_total*NQ_DOLLAR_PER_PT:+,.0f} | "
              f"mean {base_v_total/len(v):+.3f}")
        print(f"  A     total: {a_v_total:+.2f} pts | "
              f"${a_v_total*NQ_DOLLAR_PER_PT:+,.0f} | "
              f"mean {a_v_total/len(v):+.3f}")
        print(f"  B     total: {b_v_total:+.2f} pts | "
              f"${b_v_total*NQ_DOLLAR_PER_PT:+,.0f} | "
              f"mean {b_v_total/len(v):+.3f}")
        print(f"  Δ A vs BASE: ${(a_v_total-base_v_total)*NQ_DOLLAR_PER_PT:+,.0f}")
        print(f"  Δ B vs BASE: ${(b_v_total-base_v_total)*NQ_DOLLAR_PER_PT:+,.0f}")
        print(f"  Δ B vs A:    ${(b_v_total-a_v_total)*NQ_DOLLAR_PER_PT:+,.0f}")
        print(f"  C2 filled in B: {b_c2_filled:,} of "
              f"{len(v):,} V trades "
              f"({100*b_c2_filled/len(v):.1f}%)")

        print(f"\n[{year}] Strategy A V outcomes:")
        for k, vc in v["a_out"].value_counts().items():
            print(f"  {k:12s} {vc:>5,} "
                  f"({100*vc/len(v):4.1f}%)")
        print(f"\n[{year}] Strategy B V C1 outcomes:")
        for k, vc in v["b_c1_out"].value_counts().items():
            print(f"  {k:12s} {vc:>5,} "
                  f"({100*vc/len(v):4.1f}%)")
        print(f"\n[{year}] Strategy B V C2 outcomes:")
        for k, vc in v["b_c2_out"].value_counts().items():
            print(f"  {k:12s} {vc:>5,} "
                  f"({100*vc/len(v):4.1f}%)")

        print(f"\n[{year}] === OVERALL (V-shape rebuilt; "
              f"non-V unchanged) ===")
        print(f"  BASE  overall: ${base_overall*NQ_DOLLAR_PER_PT:>+11,.0f}")
        print(f"  A     overall: ${a_overall*NQ_DOLLAR_PER_PT:>+11,.0f}  "
              f"(Δ ${(a_overall-base_overall)*NQ_DOLLAR_PER_PT:+,.0f})")
        print(f"  B     overall: ${b_overall*NQ_DOLLAR_PER_PT:>+11,.0f}  "
              f"(Δ ${(b_overall-base_overall)*NQ_DOLLAR_PER_PT:+,.0f})")

        summary[year] = {
            "n_v": len(v), "n_total": n_total,
            "base_overall": base_overall * NQ_DOLLAR_PER_PT,
            "a_overall": a_overall * NQ_DOLLAR_PER_PT,
            "b_overall": b_overall * NQ_DOLLAR_PER_PT,
            "v_base": base_v_total * NQ_DOLLAR_PER_PT,
            "v_a": a_v_total * NQ_DOLLAR_PER_PT,
            "v_b": b_v_total * NQ_DOLLAR_PER_PT,
        }
        df.to_csv(OUT / f"trades_{year}.csv", index=False)

    print(f"\n{'='*70}\nSUMMARY (V-shape):")
    print(f"{'Year':<6} {'n_v':<8} {'BASE V':>13} "
          f"{'A V':>13} {'B V':>13} "
          f"{'Δ A':>10} {'Δ B':>10}")
    for yr, s in summary.items():
        da = s["v_a"] - s["v_base"]
        db = s["v_b"] - s["v_base"]
        print(f"{yr:<6} {s['n_v']:<8,} "
              f"${s['v_base']:>+11,.0f} "
              f"${s['v_a']:>+11,.0f} "
              f"${s['v_b']:>+11,.0f} "
              f"${da:>+8,.0f} ${db:>+8,.0f}")
    print(f"\n{'Year':<6} {'BASE all':>13} {'A all':>13} {'B all':>13}")
    for yr, s in summary.items():
        print(f"{yr:<6} ${s['base_overall']:>+11,.0f} "
              f"${s['a_overall']:>+11,.0f} "
              f"${s['b_overall']:>+11,.0f}")


if __name__ == "__main__":
    main()
