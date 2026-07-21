"""T_A2v2 refinement: 4 variants with persistence / flow confirmation.

Base candidate (T_A2v2):
  At +3m exact:
    unrealized_pnl < -50 AND current_mfe_atr < 0.25  → exit immediately

Variants:
  V1 — Persistence confirmation:
    Candidate at +3m: unr<-50 AND mfe_atr<0.25
    Exit at +4m only if STILL: unr<-50 AND mfe_atr<0.35
  V2 — Short-term flow confirmation (still exits at +3m):
    Exit at +3m if: unr<-50 AND mfe_atr<0.25 AND xfast_net_move<0
  V3 — No-improvement confirmation:
    Candidate at +3m: unr<-50 AND mfe_atr<0.25
    Exit at +4m if: mfe_atr_4m - mfe_atr_3m < 0.10
                    OR unr_4m - unr_3m < 50
  V4 — Hybrid strict:
    Candidate at +3m: unr<-50 AND mfe_atr<0.25
    Exit at +4m if: still unr<0 AND mfe_atr<0.35 AND xfast_net_move<0

Metrics per variant:
  - per-year net, $/tr, max DD, positive months, median monthly PnL
  - n exits fired
  - % exits helped / hurt
  - mean Δ on helped / hurt
  - number of 3+ ATR runners cut early  (critical guardrail)

Compare each to:
  - baseline filtered V_A (no overlay)
  - T_A2v2 (immediate exit at +3m on unr<-50 AND mfe<0.25)
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
TICK_S = 30   # 30s tick interval is fine for ±30s checkpoint windows

OUT = Path("studies/v_a_excursion_regime/results_v0")


def compute_tertile_cuts(dfs):
    is_combined = pd.concat(
        [dfs[yr] for yr in (2024, 2025) if yr in dfs], ignore_index=True)
    return is_combined["total_excursion_slow"].quantile([1/3, 2/3]).values


def tertile_label(v, lo, hi):
    if pd.isna(v): return np.nan
    if v < lo: return "low"
    if v < hi: return "mid"
    return "high"


def load_year_bars(year: int):
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


def trade_state_and_xfast(checkpoint_ns, direction, atr, ts_index_ns,
                              opens, highs, lows, closes,
                              entry_ns, fill_px):
    """Compute current MFE/MAE/unrealized at checkpoint AND xfast
    (2.5min = 5×30s) net_move (direction-aware).

    All bars used satisfy ts_event < checkpoint_ns (causal).
    """
    out = {}
    # Trade-state since entry
    j_lo = np.searchsorted(ts_index_ns, entry_ns, side="left")
    j_hi = np.searchsorted(ts_index_ns, checkpoint_ns, side="left")
    if j_hi <= j_lo:
        return None
    seg_h = highs[j_lo:j_hi]
    seg_l = lows[j_lo:j_hi]
    seg_c = closes[j_hi - 1]
    if direction == 1:
        cur_mfe = float(seg_h.max() - fill_px)
        cur_mae = float(fill_px - seg_l.min())
        unrealized_pts = float(seg_c - fill_px)
    else:
        cur_mfe = float(fill_px - seg_l.min())
        cur_mae = float(seg_h.max() - fill_px)
        unrealized_pts = float(fill_px - seg_c)
    out["current_mfe_atr"] = cur_mfe / max(atr, 0.01)
    out["current_mae_atr"] = cur_mae / max(atr, 0.01)
    out["unrealized_pnl"] = unrealized_pts * NQ_MULT
    out["fill_at_next_bar"] = (
        float(opens[j_hi]) if j_hi < len(opens) else np.nan)
    # xfast net_move: 2.5-min window strictly before checkpoint
    win_secs = 5 * 30
    win_start_ns = checkpoint_ns - win_secs * 1_000_000_000
    i_lo = np.searchsorted(ts_index_ns, win_start_ns, side="left")
    i_hi = j_hi   # = up-to-checkpoint
    if i_hi - i_lo < 30:
        out["xfast_net_move"] = np.nan
    else:
        anchor_open = float(opens[i_lo])
        close_now = float(closes[i_hi - 1])
        if direction == 1:
            out["xfast_net_move"] = close_now - anchor_open
        else:
            out["xfast_net_move"] = anchor_open - close_now
    return out


def compute_alt_pnl(direction, fill_price, alt_exit_px):
    if pd.isna(alt_exit_px): return np.nan
    if direction == 1:
        pts = alt_exit_px - fill_price
    else:
        pts = fill_price - alt_exit_px
    return pts * NQ_MULT - 2 * COMMISSION


def add_drawdown(df, pnl_col):
    df = df.sort_values("entry_ts").copy()
    df["cum"] = df[pnl_col].cumsum()
    df["cum_max"] = df["cum"].cummax()
    df["dd"] = df["cum"] - df["cum_max"]
    return df


def yearly_metrics(df, pnl_col):
    if not len(df): return {}
    n = len(df)
    wins = (df[pnl_col] > 0).sum()
    net = df[pnl_col].sum()
    df_dd = add_drawdown(df, pnl_col)
    max_dd = df_dd["dd"].min()
    df = df.copy()
    df["entry_dt"] = pd.to_datetime(df["entry_ts"], unit="ns", utc=True)
    df["month"] = df["entry_dt"].dt.tz_convert("UTC").dt.to_period("M")
    monthly = df.groupby("month")[pnl_col].sum()
    return {
        "n": n,
        "wr_pct": wins / n * 100,
        "net_pnl": net,
        "per_trade": net / n,
        "max_dd": max_dd,
        "pos_months": (monthly > 0).sum(),
        "total_months": len(monthly),
        "median_monthly_pnl": monthly.median(),
    }


def evaluate_variants(year, lo_cut, hi_cut, dfs):
    print(f"\n=== Year {year} ===", flush=True)
    d = dfs[year].copy()
    d["bkt"] = d["total_excursion_slow"].apply(
        lambda v: tertile_label(v, lo_cut, hi_cut))
    filtered = d[d["bkt"] == "mid"].copy().reset_index(drop=True)
    print(f"  filtered trades: {len(filtered):,}", flush=True)

    bars = load_year_bars(year)
    ts_index_ns = bars.index.astype("int64").to_numpy()
    opens = bars["open"].values.astype(np.float64)
    highs = bars["high"].values.astype(np.float64)
    lows = bars["low"].values.astype(np.float64)
    closes = bars["close"].values.astype(np.float64)

    rows = []
    t0 = time.time()
    for i, tr in filtered.iterrows():
        entry_ns = int(tr["entry_ts"])
        exit_ns = int(tr["exit_ts"])
        direction = int(tr["direction"])
        atr = float(tr["atr_at_signal"])
        fill_px = float(tr["fill_price"])
        baseline_pnl = float(tr["net_pnl"])
        final_mfe_atr = float(tr["running_mfe"]) / max(atr, 0.01)
        is_runner = final_mfe_atr >= 3.0

        # State at +3m and +4m
        ts_3m = entry_ns + 180 * 1_000_000_000
        ts_4m = entry_ns + 240 * 1_000_000_000
        s3 = (trade_state_and_xfast(ts_3m, direction, atr, ts_index_ns,
                                       opens, highs, lows, closes,
                                       entry_ns, fill_px)
                if ts_3m < exit_ns else None)
        s4 = (trade_state_and_xfast(ts_4m, direction, atr, ts_index_ns,
                                       opens, highs, lows, closes,
                                       entry_ns, fill_px)
                if ts_4m < exit_ns else None)

        row = {
            "year": year, "trade_idx": i,
            "direction": direction, "fill_price": fill_px,
            "entry_ts": entry_ns, "exit_ts": exit_ns,
            "baseline_net_pnl": baseline_pnl,
            "final_mfe_atr": final_mfe_atr,
            "is_runner": is_runner,
        }

        # ---- T_A2v2 (base): exit at +3m if unr<-50 AND mfe<0.25 ----
        if (s3 is not None and s3["unrealized_pnl"] < -50
                and s3["current_mfe_atr"] < 0.25):
            row["base_pnl"] = compute_alt_pnl(
                direction, fill_px, s3["fill_at_next_bar"])
            row["base_fired"] = True
        else:
            row["base_pnl"] = baseline_pnl
            row["base_fired"] = False

        # ---- V1 — Persistence: candidate +3m, confirm +4m ----
        # exit at +4m if STILL unr<-50 AND mfe<0.35
        if (s3 is not None and s3["unrealized_pnl"] < -50
                and s3["current_mfe_atr"] < 0.25
                and s4 is not None and s4["unrealized_pnl"] < -50
                and s4["current_mfe_atr"] < 0.35):
            row["v1_pnl"] = compute_alt_pnl(
                direction, fill_px, s4["fill_at_next_bar"])
            row["v1_fired"] = True
        else:
            row["v1_pnl"] = baseline_pnl
            row["v1_fired"] = False

        # ---- V2 — Short-term flow at +3m ----
        # exit at +3m if unr<-50 AND mfe<0.25 AND xfast_net_move < 0
        if (s3 is not None and s3["unrealized_pnl"] < -50
                and s3["current_mfe_atr"] < 0.25
                and not pd.isna(s3.get("xfast_net_move", np.nan))
                and s3["xfast_net_move"] < 0):
            row["v2_pnl"] = compute_alt_pnl(
                direction, fill_px, s3["fill_at_next_bar"])
            row["v2_fired"] = True
        else:
            row["v2_pnl"] = baseline_pnl
            row["v2_fired"] = False

        # ---- V3 — No-improvement: candidate +3m, confirm +4m ----
        # exit at +4m if mfe_atr improved < 0.10 OR unr improved < 50
        if (s3 is not None and s3["unrealized_pnl"] < -50
                and s3["current_mfe_atr"] < 0.25
                and s4 is not None):
            mfe_improvement = s4["current_mfe_atr"] - s3["current_mfe_atr"]
            unr_improvement = s4["unrealized_pnl"] - s3["unrealized_pnl"]
            if mfe_improvement < 0.10 or unr_improvement < 50:
                row["v3_pnl"] = compute_alt_pnl(
                    direction, fill_px, s4["fill_at_next_bar"])
                row["v3_fired"] = True
            else:
                row["v3_pnl"] = baseline_pnl
                row["v3_fired"] = False
        else:
            row["v3_pnl"] = baseline_pnl
            row["v3_fired"] = False

        # ---- V4 — Hybrid strict: candidate +3m, confirm +4m ----
        # exit at +4m if still unr<0 AND mfe<0.35 AND xfast_net_move<0
        if (s3 is not None and s3["unrealized_pnl"] < -50
                and s3["current_mfe_atr"] < 0.25
                and s4 is not None and s4["unrealized_pnl"] < 0
                and s4["current_mfe_atr"] < 0.35
                and not pd.isna(s4.get("xfast_net_move", np.nan))
                and s4["xfast_net_move"] < 0):
            row["v4_pnl"] = compute_alt_pnl(
                direction, fill_px, s4["fill_at_next_bar"])
            row["v4_fired"] = True
        else:
            row["v4_pnl"] = baseline_pnl
            row["v4_fired"] = False

        rows.append(row)
        if i and i % 250 == 0:
            print(f"   {i}/{len(filtered)} elapsed {time.time()-t0:.0f}s",
                  flush=True)

    print(f"   year {year} done in {time.time()-t0:.0f}s", flush=True)
    return pd.DataFrame(rows)


def variant_summary(df, variant, baseline_col="baseline_net_pnl"):
    pnl_col = f"{variant}_pnl"
    fire_col = f"{variant}_fired"
    fired = df[df[fire_col]]
    fired_delta = fired[pnl_col] - fired[baseline_col]
    helped = (fired_delta > 0).sum()
    hurt = (fired_delta < 0).sum()
    runners_cut = (fired["is_runner"]).sum()
    return {
        "n_fired": len(fired),
        "fire_pct": 100 * len(fired) / len(df),
        "helped": helped,
        "hurt": hurt,
        "helped_pct": 100 * helped / len(fired) if len(fired) else 0,
        "hurt_pct": 100 * hurt / len(fired) if len(fired) else 0,
        "mean_save_helped": (fired[fired_delta > 0][pnl_col]
                                  - fired[fired_delta > 0][baseline_col]
                                  ).mean() if helped else 0,
        "mean_loss_hurt": (fired[fired_delta < 0][pnl_col]
                                - fired[fired_delta < 0][baseline_col]
                                ).mean() if hurt else 0,
        "runners_cut_early": int(runners_cut),
    }


def main():
    t0 = time.time()
    print("=" * 78)
    print("T_A2v2 REFINEMENT STUDY — 4 variants vs baseline + base trigger")
    print("=" * 78)

    dfs = {}
    for yr in (2024, 2025, 2026):
        p = OUT / f"v_a_v0_{yr}_with_excursion.parquet"
        dfs[yr] = pd.read_parquet(p)
    lo_cut, hi_cut = compute_tertile_cuts(dfs)

    parts = []
    for yr in (2024, 2025, 2026):
        parts.append(evaluate_variants(yr, lo_cut, hi_cut, dfs))
    full = pd.concat(parts, ignore_index=True)
    full.to_parquet(OUT / "t_a2v2_refinement_results.parquet")

    variants = ["base", "v1", "v2", "v3", "v4"]
    variant_names = {
        "base": "T_A2v2 base (+3m, unr<-50, mfe<0.25)",
        "v1": "V1 persistence (+3m cand, +4m: unr<-50, mfe<0.35)",
        "v2": "V2 flow (+3m + xfast_net<0)",
        "v3": "V3 no-improve (+4m: mfe Δ<0.1 OR unr Δ<$50)",
        "v4": "V4 hybrid strict (+4m: unr<0, mfe<0.35, xfast_net<0)",
    }

    # ---- Per-year performance ----
    print(f"\n{'='*78}")
    print("PER-YEAR PERFORMANCE")
    print(f"{'='*78}")
    rows = []
    for yr in (2024, 2025, 2026):
        sub = full[full["year"] == yr]
        if not len(sub): continue
        # baseline
        m = yearly_metrics(sub, "baseline_net_pnl")
        m["year"] = yr; m["variant"] = "baseline"; rows.append(m)
        for v in variants:
            m = yearly_metrics(sub, f"{v}_pnl")
            m["year"] = yr; m["variant"] = v; rows.append(m)
    perf = pd.DataFrame(rows)
    perf.to_csv(OUT / "t_a2v2_refinement_yearly.csv", index=False)

    for yr in (2024, 2025, 2026):
        s = perf[perf["year"] == yr]
        if not len(s): continue
        baseline_net = s[s["variant"] == "baseline"]["net_pnl"].iloc[0]
        print(f"\n--- {yr} ---")
        print(f"  {'variant':<10} {'n':>5} {'WR%':>5} {'net':>9} "
              f"{'$/tr':>6} {'maxDD':>9} {'posM':>5} {'medM':>9} "
              f"{'Δ':>9}")
        for _, r in s.iterrows():
            d = r["net_pnl"] - baseline_net
            d_str = f"{d:>+9,.0f}" if r["variant"] != "baseline" else "ref"
            print(f"  {r['variant']:<10} {int(r['n']):>5,} "
                  f"{r['wr_pct']:>4.1f}% {r['net_pnl']:>+8,.0f} "
                  f"{r['per_trade']:>+5.1f} "
                  f"{r['max_dd']:>+8,.0f} "
                  f"{int(r['pos_months']):>2}/{int(r['total_months']):>2} "
                  f"{r['median_monthly_pnl']:>+8,.0f} {d_str:>9}")

    # ---- Across-year roll-up ----
    print(f"\n--- ALL YEARS ---")
    print(f"  {'variant':<10} {'n':>5} {'WR%':>5} {'net':>9} "
          f"{'$/tr':>6} {'maxDD':>9} {'posM':>7}")
    base_m = yearly_metrics(full, "baseline_net_pnl")
    print(f"  {'baseline':<10} {int(base_m['n']):>5,} "
          f"{base_m['wr_pct']:>4.1f}% {base_m['net_pnl']:>+8,.0f} "
          f"{base_m['per_trade']:>+5.1f} "
          f"{base_m['max_dd']:>+8,.0f} "
          f"{int(base_m['pos_months']):>2}/{int(base_m['total_months']):>2}")
    for v in variants:
        m = yearly_metrics(full, f"{v}_pnl")
        d = m["net_pnl"] - base_m["net_pnl"]
        print(f"  {v:<10} {int(m['n']):>5,} "
              f"{m['wr_pct']:>4.1f}% {m['net_pnl']:>+8,.0f} "
              f"{m['per_trade']:>+5.1f} "
              f"{m['max_dd']:>+8,.0f} "
              f"{int(m['pos_months']):>2}/{int(m['total_months']):>2} "
              f"  Δ {d:>+8,.0f}")

    # ---- Per-variant fire/helped/hurt diagnostics ----
    print(f"\n{'='*78}")
    print("FIRE QUALITY DIAGNOSTICS (across all years)")
    print(f"{'='*78}")
    for v in variants:
        s = variant_summary(full, v)
        print(f"\n  {variant_names[v]}")
        print(f"    fired: {s['n_fired']:,}  ({s['fire_pct']:.1f}% of trades)")
        print(f"    helped: {s['helped']:,} ({s['helped_pct']:.1f}%)  "
              f"hurt: {s['hurt']:,} ({s['hurt_pct']:.1f}%)")
        print(f"    mean save on helped: ${s['mean_save_helped']:+,.0f}  "
              f"mean loss on hurt: ${s['mean_loss_hurt']:+,.0f}")
        print(f"    3+ ATR runners cut early: {s['runners_cut_early']:,}")

    # ---- Per-year fire diagnostics ----
    print(f"\n{'='*78}")
    print("PER-YEAR FIRE COUNTS")
    print(f"{'='*78}")
    print(f"  {'variant':<10} " + "".join(f"{yr:>9}" for yr in (2024, 2025, 2026)))
    for v in variants:
        line = f"  {v:<10} "
        for yr in (2024, 2025, 2026):
            s = full[full["year"] == yr]
            if not len(s): line += f"{'-':>9}"; continue
            n = s[f"{v}_fired"].sum()
            line += f"{n:>9,}"
        print(line)

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
