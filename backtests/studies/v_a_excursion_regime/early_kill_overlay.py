"""Early-kill overlay study — target C5 uncaught losers at +1m / +2m.

Base population: V_A T0 trades (HH/LL + 30s delay) filtered by
total_excursion_slow=mid.

Each trade is classified into 5 classes (per attribution study):
  C1 good_runner       — final MFE_atr >= 3 AND won
  C2 good_normal_win   — won AND MFE_atr < 3
  C3 V4 false_exit     — V4 fires AND baseline net_pnl > 0
  C4 V4 true_save      — V4 fires AND baseline net_pnl <= 0
  C5 uncaught_loser    — V4 doesn't fire AND net_pnl <= 0

5 candidate early-kill triggers, each evaluated at +1m AND +2m:
  T1 low MFE / high MAE       : mfe_to_mae < 1.0
  T2 weak price location       : close_loc_in_range < 0.5
  T3 negative flow             : net_move_xfast < 0
  T4 combined                  : T1 AND T3
  T5 strong combined           : T1 AND T2 AND T3

Exit fill: OPEN of next 1s bar at the checkpoint (NT-realistic).

Reports:
  Per (checkpoint × trigger):
    - % of C5 caught
    - % of C1 (runner) cut early — guardrail
    - % of C2/C3/C4 caught
    - net PnL change vs baseline
    - $/trade change

  Per (checkpoint × trigger):
    Stack vs V4 (V4 + early-kill = whichever fires first):
      - 2024 / 2025 / 2026 net + $/tr + max DD
      - all-years total
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
SLOW_LO_CUT = 43.00
SLOW_HI_CUT = 71.75
EPS = 1e-6

CHECKPOINTS_S = [60, 120]   # +1m, +2m
CHECKPOINT_NAMES = ["+1m", "+2m"]

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
    """Compute trade-state + xfast features at t_ns. Causal."""
    # Trade-state since entry
    j_lo = np.searchsorted(ts_idx, entry_ts, side="left")
    j_hi = np.searchsorted(ts_idx, t_ns, side="left")
    if j_hi <= j_lo: return None
    seg_h = highs[j_lo:j_hi]
    seg_l = lows[j_lo:j_hi]
    seg_c = closes[j_hi - 1]
    if direction == 1:
        cur_mfe = float(seg_h.max() - fill_px)
        cur_mae = float(fill_px - seg_l.min())
        unr_pts = float(seg_c - fill_px)
        if seg_h.max() - seg_l.min() > EPS:
            close_loc = ((float(seg_c) - float(seg_l.min()))
                         / float(seg_h.max() - seg_l.min()))
        else:
            close_loc = 0.5
    else:
        cur_mfe = float(fill_px - seg_l.min())
        cur_mae = float(seg_h.max() - fill_px)
        unr_pts = float(fill_px - seg_c)
        if seg_h.max() - seg_l.min() > EPS:
            close_loc = ((float(seg_h.max()) - float(seg_c))
                         / float(seg_h.max() - seg_l.min()))
        else:
            close_loc = 0.5
    out = {
        "current_mfe_atr": cur_mfe / max(atr, 0.01),
        "current_mae_atr": cur_mae / max(atr, 0.01),
        "unrealized_pnl": unr_pts * NQ_MULT,
        "mfe_to_mae": (cur_mfe / max(atr, 0.01))
                       / max(cur_mae / max(atr, 0.01), 0.01),
        "close_loc_in_range": close_loc,
        "fill_at_next_bar": (
            float(opens[j_hi]) if j_hi < len(opens) else np.nan),
    }
    # xfast (5×30s = 150s) net_move, direction-aware, strictly before t_ns
    win_start = t_ns - 5 * 30 * 1_000_000_000
    i_lo = np.searchsorted(ts_idx, win_start, side="left")
    if j_hi - i_lo < 30:
        out["net_move_xfast"] = np.nan
    else:
        anc = float(opens[i_lo])
        cn = float(closes[j_hi - 1])
        out["net_move_xfast"] = (cn - anc) if direction == 1 else (anc - cn)
    return out


def compute_alt_pnl(direction, fill_px, alt_px):
    if pd.isna(alt_px): return np.nan
    pts = (alt_px - fill_px) if direction == 1 else (fill_px - alt_px)
    return pts * NQ_MULT - 2 * COMMISSION


def evaluate_v4(direction, atr, fill_px, entry_ns, exit_ns, ts_idx,
                  opens, highs, lows, closes):
    """Return (v4_fired, v4_pnl_if_fired_else_nan, v4_fire_ts_else_None)."""
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
    pnl = compute_alt_pnl(direction, fill_px, s4["fill_at_next_bar"])
    return True, pnl, ts_4m


def fires_T1(f): return f.get("mfe_to_mae", np.inf) < 1.0
def fires_T2(f): return f.get("close_loc_in_range", np.inf) < 0.5
def fires_T3(f):
    v = f.get("net_move_xfast", np.nan)
    return False if pd.isna(v) else v < 0
def fires_T4(f): return fires_T1(f) and fires_T3(f)
def fires_T5(f): return fires_T1(f) and fires_T2(f) and fires_T3(f)

TRIGGERS = {
    "T1_lowMFE":     fires_T1,
    "T2_weakLoc":    fires_T2,
    "T3_negFlow":    fires_T3,
    "T4_combined":   fires_T4,
    "T5_strong":     fires_T5,
}


def add_drawdown(df, col):
    df = df.sort_values("entry_ts").copy()
    df["cum"] = df[col].cumsum()
    df["cum_max"] = df["cum"].cummax()
    df["dd"] = df["cum"] - df["cum_max"]
    return df


def yearly_metrics(df, col):
    if not len(df): return {}
    n = len(df)
    wins = (df[col] > 0).sum()
    net = df[col].sum()
    df_dd = add_drawdown(df, col)
    max_dd = df_dd["dd"].min()
    df = df.copy()
    df["entry_dt"] = pd.to_datetime(df["entry_ts"], unit="ns", utc=True)
    df["month"] = df["entry_dt"].dt.tz_convert("UTC").dt.to_period("M")
    monthly = df.groupby("month")[col].sum()
    return {"n": n, "wr_pct": wins / n * 100, "net_pnl": net,
            "per_trade": net / n, "max_dd": max_dd,
            "pos_months": (monthly > 0).sum(),
            "total_months": len(monthly)}


def main():
    t0 = time.time()
    print("=" * 78)
    print("EARLY-KILL OVERLAY @ +1m / +2m — targets C5 uncaught losers")
    print("=" * 78)

    all_rows = []
    for yr in (2024, 2025, 2026):
        print(f"\n--- year {yr} ---", flush=True)
        # Load filtered T0 trades (HH/LL + total_excursion_slow=mid)
        wex = pd.read_parquet(OUT / f"v_a_v0_{yr}_with_excursion.parquet")
        filt = wex[(wex["total_excursion_slow"] >= SLOW_LO_CUT)
                     & (wex["total_excursion_slow"] < SLOW_HI_CUT)].copy()
        filt = filt.reset_index(drop=True)
        print(f"  filtered trades: {len(filt):,}", flush=True)

        bars = load_year_bars(yr)
        ts_idx = bars.index.astype("int64").to_numpy()
        opens = bars["open"].values.astype(np.float64)
        highs = bars["high"].values.astype(np.float64)
        lows = bars["low"].values.astype(np.float64)
        closes = bars["close"].values.astype(np.float64)

        for _, tr in filt.iterrows():
            entry_ns = int(tr["entry_ts"])
            exit_ns = int(tr["exit_ts"])
            direction = int(tr["direction"])
            atr = float(tr["atr_at_signal"])
            fill_px = float(tr["fill_price"])
            baseline_pnl = float(tr["net_pnl"])
            final_mfe_atr = float(tr["running_mfe"]) / max(atr, 0.01)

            # V4 evaluation
            v4_fired, v4_pnl, v4_fire_ts = evaluate_v4(
                direction, atr, fill_px, entry_ns, exit_ns,
                ts_idx, opens, highs, lows, closes)

            # Class
            if v4_fired:
                cls = "C3" if baseline_pnl > 0 else "C4"
            else:
                if baseline_pnl > 0 and final_mfe_atr >= 3.0: cls = "C1"
                elif baseline_pnl > 0: cls = "C2"
                else: cls = "C5"

            row = {
                "year": yr, "direction": direction, "atr": atr,
                "fill_px": fill_px, "entry_ts": entry_ns,
                "exit_ts": exit_ns, "baseline_pnl": baseline_pnl,
                "v4_fired": v4_fired,
                "v4_pnl": v4_pnl if v4_fired else baseline_pnl,
                "v4_fire_ts": v4_fire_ts,
                "final_mfe_atr": final_mfe_atr, "class": cls,
            }

            # Compute features at +1m and +2m
            states = {}
            for cp_name, cp_s in zip(CHECKPOINT_NAMES, CHECKPOINTS_S):
                cp_ts = entry_ns + cp_s * 1_000_000_000
                if cp_ts >= exit_ns:
                    states[cp_name] = None
                    continue
                states[cp_name] = features_at(
                    cp_ts, direction, atr, fill_px, ts_idx,
                    opens, highs, lows, closes, entry_ns)

            # For each trigger × checkpoint, determine fire + alt pnl + ts
            for tname, fn in TRIGGERS.items():
                for cp_name, cp_s in zip(CHECKPOINT_NAMES, CHECKPOINTS_S):
                    s = states[cp_name]
                    if s is None:
                        row[f"{tname}_{cp_name}_fired"] = False
                        row[f"{tname}_{cp_name}_pnl"] = baseline_pnl
                        row[f"{tname}_{cp_name}_fire_ts"] = None
                        continue
                    if fn(s):
                        cp_ts = entry_ns + cp_s * 1_000_000_000
                        alt_pnl = compute_alt_pnl(
                            direction, fill_px, s["fill_at_next_bar"])
                        row[f"{tname}_{cp_name}_fired"] = True
                        row[f"{tname}_{cp_name}_pnl"] = alt_pnl
                        row[f"{tname}_{cp_name}_fire_ts"] = cp_ts
                    else:
                        row[f"{tname}_{cp_name}_fired"] = False
                        row[f"{tname}_{cp_name}_pnl"] = baseline_pnl
                        row[f"{tname}_{cp_name}_fire_ts"] = None

            # Stack: V4 + early kill (whichever fires first)
            for tname in TRIGGERS:
                for cp_name in CHECKPOINT_NAMES:
                    ek_fired = row[f"{tname}_{cp_name}_fired"]
                    ek_ts = row[f"{tname}_{cp_name}_fire_ts"]
                    ek_pnl = row[f"{tname}_{cp_name}_pnl"]
                    # Stack: pick whichever happens first (early kill happens
                    # at +1m or +2m, V4 at +4m, so EK always earlier if fired)
                    if ek_fired:
                        stack_pnl = ek_pnl
                    elif v4_fired:
                        stack_pnl = v4_pnl
                    else:
                        stack_pnl = baseline_pnl
                    row[f"stack_{tname}_{cp_name}_pnl"] = stack_pnl
                    row[f"stack_{tname}_{cp_name}_fired"] = (
                        ek_fired or v4_fired)
            all_rows.append(row)

    full = pd.DataFrame(all_rows)
    full.to_parquet(OUT / "early_kill_overlay_results.parquet")
    print(f"\n  wrote {OUT}/early_kill_overlay_results.parquet  "
          f"({len(full):,} rows)", flush=True)

    # ============================================================
    # Per-class catch rates
    # ============================================================
    print(f"\n{'='*78}")
    print("PER-CLASS CATCH RATES (across 3 years)")
    print(f"{'='*78}")
    classes_ordered = ["C1", "C2", "C3", "C4", "C5"]
    class_counts = full["class"].value_counts().to_dict()
    print(f"\n  Class counts: " + "  ".join(
        f"{c}={class_counts.get(c, 0):,}" for c in classes_ordered))

    for cp_name in CHECKPOINT_NAMES:
        print(f"\n--- Checkpoint {cp_name} ---")
        print(f"  {'trigger':<12} " + "".join(
            f"{c:>9}" for c in classes_ordered) + f"  {'fire%':>6}")
        for tname in TRIGGERS:
            line = f"  {tname:<12} "
            total_fired = full[f"{tname}_{cp_name}_fired"].sum()
            for c in classes_ordered:
                sub = full[full["class"] == c]
                if len(sub) == 0:
                    line += f"{'-':>9}"; continue
                fired = sub[f"{tname}_{cp_name}_fired"].sum()
                pct = 100 * fired / len(sub)
                line += f"{pct:>+8.1f}%"
            line += f"  {100*total_fired/len(full):>+5.1f}%"
            print(line)

    # ============================================================
    # PnL economics per (checkpoint × trigger) — early-kill only
    # ============================================================
    print(f"\n{'='*78}")
    print("EARLY-KILL ONLY PnL (no V4 stacked)")
    print(f"{'='*78}")
    print(f"\n  (deltas vs baseline, all 3 years pooled)\n")
    print(f"  {'trigger':<12} " + "".join(
        f"{cp:>20}" for cp in CHECKPOINT_NAMES))
    print(f"  {'':12} " + "".join(
        f"{'net':>10}{'$/tr':>10}" for _ in CHECKPOINT_NAMES))
    base_net = full["baseline_pnl"].sum()
    base_per = base_net / len(full)
    print(f"  {'baseline':<12} {base_net:>+9,.0f} {base_per:>+9.1f}")
    for tname in TRIGGERS:
        line = f"  {tname:<12} "
        for cp_name in CHECKPOINT_NAMES:
            col = f"{tname}_{cp_name}_pnl"
            net = full[col].sum()
            per = net / len(full)
            line += f"{net:>+9,.0f} {per:>+9.1f}"
        print(line)

    # ============================================================
    # PnL economics for STACK (V4 + early kill)
    # ============================================================
    print(f"\n{'='*78}")
    print("STACK (V4 + early-kill) PnL — all 3 years")
    print(f"{'='*78}")
    v4_net = full["v4_pnl"].sum()
    print(f"  baseline:  ${base_net:>+9,.0f}  ({base_per:>+5.1f}/tr)")
    print(f"  V4 only:   ${v4_net:>+9,.0f}  ({v4_net/len(full):>+5.1f}/tr)  "
          f"Δ {v4_net - base_net:>+9,.0f}")
    print()
    print(f"  {'trigger':<12} " + "".join(
        f"{cp:>20}" for cp in CHECKPOINT_NAMES))
    print(f"  {'':12} " + "".join(
        f"{'net':>10}{'Δ_v4':>10}" for _ in CHECKPOINT_NAMES))
    for tname in TRIGGERS:
        line = f"  {tname:<12} "
        for cp_name in CHECKPOINT_NAMES:
            col = f"stack_{tname}_{cp_name}_pnl"
            stack_net = full[col].sum()
            line += f"{stack_net:>+9,.0f} {stack_net - v4_net:>+9,.0f}"
        print(line)

    # ============================================================
    # Per-year stack metrics for promising candidates
    # ============================================================
    print(f"\n{'='*78}")
    print("PER-YEAR STACK METRICS (V4 + early-kill)")
    print(f"{'='*78}")
    # Identify promising stacks: those where C1 cut < 5% and Δ_v4 > 0
    for cp_name in CHECKPOINT_NAMES:
        for tname in TRIGGERS:
            stack_col = f"stack_{tname}_{cp_name}_pnl"
            ek_col = f"{tname}_{cp_name}_fired"
            c1_cut = full[(full["class"] == "C1")
                            & (full[ek_col])][ek_col].sum()
            c1_total = (full["class"] == "C1").sum()
            c1_cut_pct = 100 * c1_cut / max(c1_total, 1)
            stack_net = full[stack_col].sum()
            if stack_net > v4_net and c1_cut_pct < 8.0:
                print(f"\n  PROMISING: V4 + {tname} @ {cp_name}  "
                      f"(C1 cut {c1_cut_pct:.1f}%, Δ vs V4 "
                      f"${stack_net - v4_net:+,.0f})")
                print(f"  {'year':<6} {'n':>5} {'WR%':>5} {'net':>9} "
                      f"{'$/tr':>7} {'maxDD':>9} {'posM':>5}")
                for yr in (2024, 2025, 2026):
                    sub = full[full["year"] == yr]
                    m = yearly_metrics(sub, stack_col)
                    print(f"  {yr:<6} {int(m['n']):>5,} "
                          f"{m['wr_pct']:>4.1f}% {m['net_pnl']:>+8,.0f} "
                          f"{m['per_trade']:>+6.1f} "
                          f"{m['max_dd']:>+8,.0f} "
                          f"{int(m['pos_months']):>2}/"
                          f"{int(m['total_months']):>2}")

    # ============================================================
    # Detailed per-trigger PnL by class (to see savings vs runner-cuts)
    # ============================================================
    print(f"\n{'='*78}")
    print("PER-CLASS PnL DELTA from each early-kill (vs baseline)")
    print(f"{'='*78}")
    for cp_name in CHECKPOINT_NAMES:
        print(f"\n--- Checkpoint {cp_name} ---")
        print(f"  {'trigger':<12} " + "".join(
            f"{c:>10}" for c in classes_ordered))
        for tname in TRIGGERS:
            line = f"  {tname:<12} "
            for c in classes_ordered:
                sub = full[full["class"] == c]
                if not len(sub):
                    line += f"{'-':>10}"; continue
                col = f"{tname}_{cp_name}_pnl"
                delta = sub[col].sum() - sub["baseline_pnl"].sum()
                line += f"{delta:>+9,.0f}"
            print(line)

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
