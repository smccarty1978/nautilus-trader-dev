"""Delayed-only entry sweep + V4 stack on delayed entry.

Strategy variant: skip original V_A entry. Wait T seconds. If trade is
still "alive" (regime hasn't flipped), enter NOW at OPEN of next 1s bar.
Exit at the original regime-flip exit_px.

Question (c): wait-time sweep. Which T in {120, 180, 240, 300, 420, 600,
900}s gives the best total $ / $/tr / OOS-2026?

Question (a): does V4 still add value when applied to the delayed
entry? V4 windows shift to T+180s (candidate) and T+240s (confirm),
evaluated against the DELAYED entry price as fill_px.

Reports:
  1. Per-T cohort sizes (alive count, % survive) per year + all
  2. Per-T delayed-only PnL (1c) per year + all
  3. Per-T delayed + V4 stack PnL per year + all
  4. Headline comparison: 1c V_A baseline vs each delayed variant
  5. V4 fire rate when applied to delayed entry

Causality: same as alive_at_5m_study.py — every read uses bars with
ts_event < cp_ts. V4 uses entry_ts = delayed cp_ts, fill_px = price at
delayed entry. ATR remains atr_at_signal from original V_A signal.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

NQ_MULT = 20.0
COMMISSION = 5.0
EPS = 1e-6

WAIT_TIMES_S = [120, 180, 240, 300, 420, 600, 900]
WAIT_LABELS = ["+2m", "+3m", "+4m", "+5m", "+7m", "+10m", "+15m"]

OUT = Path("studies/v_a_excursion_regime/results_v0")


def load_year_bars(year):
    parts = []
    files_for_year = {
        2024: ["data/raw/NQ_v0_1s_2023.parquet",
                "data/raw/NQ_v0_1s_2024.parquet"],
        2025: ["data/raw/NQ_v0_1s_2024.parquet",
                "data/raw/NQ_v0_1s_2025.parquet"],
        2026: ["data/raw/NQ_v0_1s_2025.parquet",
                "data/raw/NQ_v0_1s_2026_ytd.parquet"],
    }
    for f in files_for_year[year]:
        if Path(f).exists():
            df = pd.read_parquet(f, columns=["open","high","low","close"])
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            parts.append(df)
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    return bars


def features_at(t_ns, direction, atr, fill_px, ts_idx, opens, highs,
                  lows, closes, entry_ts):
    """V4 features at t_ns relative to entry_ts/fill_px. Causal."""
    j_lo = np.searchsorted(ts_idx, entry_ts, side="left")
    j_hi = np.searchsorted(ts_idx, t_ns, side="left")
    if j_hi <= j_lo: return None
    seg_h = highs[j_lo:j_hi]
    seg_l = lows[j_lo:j_hi]
    seg_c = closes[j_hi - 1]
    if direction == 1:
        cur_mfe = float(seg_h.max() - fill_px)
        unr_pts = float(seg_c - fill_px)
    else:
        cur_mfe = float(fill_px - seg_l.min())
        unr_pts = float(fill_px - seg_c)
    out = {
        "current_mfe_atr": cur_mfe / max(atr, 0.01),
        "unrealized_pnl": unr_pts * NQ_MULT,
        "fill_at_next_bar": (
            float(opens[j_hi]) if j_hi < len(opens) else np.nan),
    }
    # xfast: 5 × 30s net move, direction-aware, strictly before t_ns
    win_start = t_ns - 5 * 30 * 1_000_000_000
    i_lo = np.searchsorted(ts_idx, win_start, side="left")
    if j_hi - i_lo < 30:
        out["net_move_xfast"] = np.nan
    else:
        anc = float(opens[i_lo])
        cn = float(closes[j_hi - 1])
        out["net_move_xfast"] = (cn - anc) if direction == 1 else (anc - cn)
    return out


def evaluate_v4_from(entry_ns, fill_px, direction, atr, exit_ns,
                       ts_idx, opens, highs, lows, closes):
    """V4: candidate at +3m (unr<-50 AND mfe<0.25), confirm at +4m
    (unr<0 AND mfe<0.35 AND xfast_net<0). Anchored on the entry_ns and
    fill_px passed in (so callable for original OR delayed entry).
    Returns (fired, pnl, fire_ts)."""
    ts_3m = entry_ns + 180 * 1_000_000_000
    ts_4m = entry_ns + 240 * 1_000_000_000
    if ts_3m >= exit_ns or ts_4m >= exit_ns:
        return False, np.nan, None
    s3 = features_at(ts_3m, direction, atr, fill_px, ts_idx, opens,
                       highs, lows, closes, entry_ns)
    if s3 is None: return False, np.nan, None
    if not (s3["unrealized_pnl"] < -50 and s3["current_mfe_atr"] < 0.25):
        return False, np.nan, None
    s4 = features_at(ts_4m, direction, atr, fill_px, ts_idx, opens,
                       highs, lows, closes, entry_ns)
    if s4 is None: return False, np.nan, None
    if not (s4["unrealized_pnl"] < 0
              and s4["current_mfe_atr"] < 0.35
              and not pd.isna(s4["net_move_xfast"])
              and s4["net_move_xfast"] < 0):
        return False, np.nan, None
    alt_px = s4["fill_at_next_bar"]
    if pd.isna(alt_px): return False, np.nan, None
    pts = (alt_px - fill_px) if direction == 1 else (fill_px - alt_px)
    pnl = pts * NQ_MULT - 2 * COMMISSION
    return True, pnl, ts_4m


def main():
    t0 = time.time()
    print("=" * 78)
    print("DELAYED-ONLY ENTRY SWEEP + V4 STACK ON DELAYED ENTRY")
    print("=" * 78)
    print(f"  Wait times: {WAIT_LABELS}")
    print(f"  V4 windows: T+3m (candidate), T+4m (confirm)")
    print()

    all_rows = []
    for yr in (2024, 2025, 2026):
        print(f"\n--- loading {yr} ---", flush=True)
        base = Path(f"collectors/collector_v2/results/v_a_v0_{yr}")
        trades = pd.read_parquet(base / "trades.parquet")
        bars = load_year_bars(yr)
        ts_idx = bars.index.astype("int64").to_numpy()
        opens = bars["open"].values.astype(np.float64)
        highs = bars["high"].values.astype(np.float64)
        lows = bars["low"].values.astype(np.float64)
        closes = bars["close"].values.astype(np.float64)

        n_proc = 0
        for _, tr in trades.iterrows():
            entry_ts = int(tr["entry_ts"])
            exit_ts = int(tr["exit_ts"])
            direction = int(tr["direction"])
            atr = float(tr["atr_at_signal"])
            net_pnl = float(tr["net_pnl"])
            exit_px = float(tr["exit_price"])

            row = {
                "year": yr, "entry_ts": entry_ts, "exit_ts": exit_ts,
                "direction": direction, "atr": atr,
                "baseline_pnl": net_pnl, "exit_px": exit_px,
            }

            for T_s, T_lab in zip(WAIT_TIMES_S, WAIT_LABELS):
                cp_ts = entry_ts + T_s * 1_000_000_000
                if cp_ts >= exit_ts:
                    row[f"alive_{T_lab}"] = False
                    row[f"d_pnl_{T_lab}"] = 0.0
                    row[f"v4_fired_{T_lab}"] = False
                    row[f"d_v4_pnl_{T_lab}"] = 0.0
                    continue
                j_hi = np.searchsorted(ts_idx, cp_ts, side="left")
                if j_hi >= len(opens):
                    row[f"alive_{T_lab}"] = False
                    row[f"d_pnl_{T_lab}"] = 0.0
                    row[f"v4_fired_{T_lab}"] = False
                    row[f"d_v4_pnl_{T_lab}"] = 0.0
                    continue
                price_at_cp = float(opens[j_hi])
                # Delayed-only PnL: 1c entered at price_at_cp, exit at exit_px
                if direction == 1:
                    pts = exit_px - price_at_cp
                else:
                    pts = price_at_cp - exit_px
                d_pnl = pts * NQ_MULT - 2 * COMMISSION
                row[f"alive_{T_lab}"] = True
                row[f"d_pnl_{T_lab}"] = d_pnl
                # V4 from delayed entry
                v4_fired, v4_pnl, _ = evaluate_v4_from(
                    cp_ts, price_at_cp, direction, atr, exit_ts,
                    ts_idx, opens, highs, lows, closes)
                row[f"v4_fired_{T_lab}"] = v4_fired
                row[f"d_v4_pnl_{T_lab}"] = (
                    v4_pnl if v4_fired else d_pnl)

            all_rows.append(row)
            n_proc += 1
        print(f"  {yr}: processed {n_proc:,} trades", flush=True)

    df = pd.DataFrame(all_rows)
    df.to_parquet(OUT / "delayed_only_sweep.parquet")
    print(f"\n  total trades processed: {len(df):,}")

    # ============ COHORT SIZES BY WAIT TIME ============
    print(f"\n{'='*78}")
    print("COHORT SIZES — alive at +T (would have taken delayed entry)")
    print(f"{'='*78}")
    print(f"  {'wait':<6}", end="")
    for yr in (2024, 2025, 2026, "ALL"):
        print(f"  {yr:>10}", end="")
    print()
    for T_lab in WAIT_LABELS:
        print(f"  {T_lab:<6}", end="")
        for yr in (2024, 2025, 2026):
            sub = df[df["year"] == yr]
            alive = sub[f"alive_{T_lab}"].sum()
            print(f"  {alive:>5,} ({100*alive/len(sub):>3.0f}%)", end="")
        alive = df[f"alive_{T_lab}"].sum()
        print(f"  {alive:>5,} ({100*alive/len(df):>3.0f}%)")

    # ============ 1c BASELINE (V_A original) ============
    print(f"\n{'='*78}")
    print("1c V_A BASELINE (every entry, exit at regime)")
    print(f"{'='*78}")
    print(f"  {'year':<6}  {'n':>6}  {'total$':>12}  {'$/tr':>7}  {'WR%':>5}")
    for yr in (2024, 2025, 2026):
        sub = df[df["year"] == yr]
        n = len(sub)
        pnl = sub["baseline_pnl"].sum()
        wr = (sub["baseline_pnl"] > 0).mean() * 100
        print(f"  {yr:<6}  {n:>6,}  ${pnl:>+10,.0f}  "
              f"{pnl/n:>+6.2f}  {wr:>4.1f}")
    n = len(df)
    pnl = df["baseline_pnl"].sum()
    wr = (df["baseline_pnl"] > 0).mean() * 100
    print(f"  {'ALL':<6}  {n:>6,}  ${pnl:>+10,.0f}  "
          f"{pnl/n:>+6.2f}  {wr:>4.1f}")

    # ============ DELAYED-ONLY (1c entered at +T if alive) ============
    print(f"\n{'='*78}")
    print("DELAYED-ONLY @ +T (skip if dead before T)")
    print(f"{'='*78}")
    print(f"  {'wait':<6}", end="")
    for yr in (2024, 2025, 2026, "ALL"):
        print(f"  {yr:>15}", end="")
    print()
    print(f"  {'':<6}", end="")
    for _ in range(4):
        print(f"  {'$':>9}{'$/tr':>6}", end="")
    print()
    for T_lab in WAIT_LABELS:
        print(f"  {T_lab:<6}", end="")
        for yr in (2024, 2025, 2026):
            sub = df[(df["year"] == yr) & df[f"alive_{T_lab}"]]
            n = len(sub)
            if n == 0:
                print(f"  {'-':>15}", end="")
                continue
            pnl = sub[f"d_pnl_{T_lab}"].sum()
            print(f"  ${pnl:>+8,.0f}{pnl/n:>+6.2f}", end="")
        sub = df[df[f"alive_{T_lab}"]]
        n = len(sub)
        pnl = sub[f"d_pnl_{T_lab}"].sum()
        print(f"  ${pnl:>+8,.0f}{pnl/n:>+6.2f}")

    # ============ DELAYED + V4 STACK ============
    print(f"\n{'='*78}")
    print("DELAYED-ONLY @ +T + V4 OVERLAY (V4 windows at T+3m, T+4m)")
    print(f"{'='*78}")
    print(f"  {'wait':<6}", end="")
    for yr in (2024, 2025, 2026, "ALL"):
        print(f"  {yr:>15}", end="")
    print()
    print(f"  {'':<6}", end="")
    for _ in range(4):
        print(f"  {'$':>9}{'$/tr':>6}", end="")
    print()
    for T_lab in WAIT_LABELS:
        print(f"  {T_lab:<6}", end="")
        for yr in (2024, 2025, 2026):
            sub = df[(df["year"] == yr) & df[f"alive_{T_lab}"]]
            n = len(sub)
            if n == 0:
                print(f"  {'-':>15}", end="")
                continue
            pnl = sub[f"d_v4_pnl_{T_lab}"].sum()
            print(f"  ${pnl:>+8,.0f}{pnl/n:>+6.2f}", end="")
        sub = df[df[f"alive_{T_lab}"]]
        n = len(sub)
        pnl = sub[f"d_v4_pnl_{T_lab}"].sum()
        print(f"  ${pnl:>+8,.0f}{pnl/n:>+6.2f}")

    # ============ V4 FIRE RATE & DELTA ============
    print(f"\n{'='*78}")
    print("V4 FIRE RATE ON DELAYED ENTRY  +  Δ(stack − delayed-only)")
    print(f"{'='*78}")
    print(f"  {'wait':<6}  {'alive':>6}  {'V4_fired':>9}  {'V4_rate':>8}"
          f"  {'Δ_2024':>9}  {'Δ_2025':>9}  {'Δ_2026':>9}  {'Δ_ALL':>9}")
    for T_lab in WAIT_LABELS:
        alive_mask = df[f"alive_{T_lab}"]
        n_alive = alive_mask.sum()
        v4_fired = df[alive_mask & df[f"v4_fired_{T_lab}"]]
        n_v4 = len(v4_fired)
        rate = 100 * n_v4 / max(n_alive, 1)
        deltas = []
        for yr in (2024, 2025, 2026):
            sub = df[(df["year"] == yr) & alive_mask]
            d = sub[f"d_v4_pnl_{T_lab}"].sum() - sub[f"d_pnl_{T_lab}"].sum()
            deltas.append(d)
        d_all = (df[alive_mask][f"d_v4_pnl_{T_lab}"].sum()
                  - df[alive_mask][f"d_pnl_{T_lab}"].sum())
        print(f"  {T_lab:<6}  {n_alive:>6,}  {n_v4:>9,}  {rate:>7.1f}%"
              f"  ${deltas[0]:>+7,.0f}  ${deltas[1]:>+7,.0f}"
              f"  ${deltas[2]:>+7,.0f}  ${d_all:>+7,.0f}")

    # ============ HEADLINE COMPARISON ============
    print(f"\n{'='*78}")
    print("HEADLINE — 1c V_A baseline vs delayed-only vs delayed+V4")
    print(f"{'='*78}")
    base_total = df["baseline_pnl"].sum()
    base_n = len(df)
    print(f"  V_A 1c baseline:  n={base_n:,}  "
          f"${base_total:>+11,.0f}  ({base_total/base_n:>+6.2f}/tr)")
    print()
    print(f"  {'strategy':<30}  {'n':>6}  {'total$':>11}  {'$/tr':>7}  "
          f"{'vs base':>9}")
    for T_lab in WAIT_LABELS:
        alive_mask = df[f"alive_{T_lab}"]
        n_a = alive_mask.sum()
        d_pnl = df[alive_mask][f"d_pnl_{T_lab}"].sum()
        dv4_pnl = df[alive_mask][f"d_v4_pnl_{T_lab}"].sum()
        print(f"  delayed-only @ {T_lab:<14}  {n_a:>6,}  "
              f"${d_pnl:>+10,.0f}  {d_pnl/n_a:>+6.2f}  "
              f"${d_pnl - base_total:>+7,.0f}")
        print(f"  delayed + V4  @ {T_lab:<14}  {n_a:>6,}  "
              f"${dv4_pnl:>+10,.0f}  {dv4_pnl/n_a:>+6.2f}  "
              f"${dv4_pnl - base_total:>+7,.0f}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
