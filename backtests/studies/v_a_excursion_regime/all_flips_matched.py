"""All-regime-flips (no HH/LL filter) matched-baseline comparison at
+6m and +8m from flip detection.

Anchor: decision_ts of the regime_flip snapshot. This is
~flip_bar_event + 61s = flip_bar_close + 1s = when we operationally
know the flip has occurred.

  All-flips "+6m" from decision_ts ≈ V_A "+5m from V_A entry" (intended,
                                       no 30s delay)
  All-flips "+8m" from decision_ts ≈ V_A "+7m from V_A entry" (intended)

Note: the existing v_a_v0 trades.parquet has entry_ts at
flip_bar_event + 150s (a leftover 30s delay). The V_A study results
quoted earlier are at flip_bar_close + 6.5m / +8.5m (30s off vs
"intended" anchor). All-flips here uses the proper convention.

Strategies (mirroring the V_A study):
  T0_all   matched T0 baseline = enter at OPEN of 1s bar at
           decision_ts, exit at next opposing flip's decision_ts
  B6       delayed-only @+6m
  C6       delayed @+6m + (f_unr_pnl_T_6m >= IS-q80)
  D8       delayed-only @+8m
  E8       delayed @+8m + (f_net_move_150s_8m >= IS-q10 AND
                            f_net_move_300s_8m >= IS-q20)

Cohorts:
  +6m cohort = flips alive past +6m
  +8m cohort = flips alive past +8m
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

CHECKPOINTS_S = [360, 480]   # +6m, +8m from decision_ts
CHECKPOINT_LABELS = ["6m", "8m"]

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


def compute_features(entry_ts, cp_ts, direction, atr, fill_px,
                       ts_idx, opens, highs, lows, closes):
    """Checkpoint features at cp_ts, given fill at entry_ts. Causal:
    strictly bars[ts_event < cp_ts]."""
    j_lo = np.searchsorted(ts_idx, entry_ts, side="left")
    j_hi = np.searchsorted(ts_idx, cp_ts, side="left")
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
        "f_mfe_atr_T": cur_mfe / max(atr, 0.01),
        "f_mae_atr_T": cur_mae / max(atr, 0.01),
        "f_unr_pnl_T": unr_pts * NQ_MULT,
        "f_mfe_to_mae": ((cur_mfe / max(atr, 0.01))
                          / max(cur_mae / max(atr, 0.01), 0.01)),
        "f_close_loc_in_range": close_loc,
    }
    for win_s, name in [(30, "30s"), (60, "60s"),
                          (150, "150s"), (300, "300s")]:
        win_start = cp_ts - win_s * 1_000_000_000
        i_lo = np.searchsorted(ts_idx, win_start, side="left")
        if j_hi - i_lo < max(10, win_s // 3):
            out[f"f_net_move_{name}"] = np.nan
            continue
        anc = float(opens[i_lo])
        cn = float(closes[j_hi - 1])
        out[f"f_net_move_{name}"] = (
            (cn - anc) if direction == 1 else (anc - cn))
    out["f_atr"] = atr
    out["f_direction"] = direction
    return out


def collect_all_flips():
    """Iterate snapshots.parquet across years; each regime_flip is a
    candidate signal. Exit = decision_ts of NEXT opposing flip
    (intra-year only — no cross-year exits)."""
    all_rows = []
    for yr in (2024, 2025, 2026):
        print(f"\n--- loading {yr} ---", flush=True)
        snap_p = (f"collectors/collector_v2/results/v_a_v0_{yr}"
                    f"/snapshots.parquet")
        snap = pd.read_parquet(snap_p)
        rf = snap[snap["kind"] == "regime_flip"].copy()
        rf = rf[["decision_ts", "bar_ts_event", "direction",
                   "atr_1m", "session"]]
        rf = rf.sort_values("decision_ts").reset_index(drop=True)
        # Filter to RTH (already all RTH in our data, but explicit)
        rf = rf[rf["session"] == "RTH"].copy().reset_index(drop=True)
        # Compute exit_ts as decision_ts of NEXT opposing flip.
        # Since flips alternate direction (collector logic), the
        # next row IS the opposing flip — EXCEPT possibly across
        # ETH-only flips that aren't snapshotted. We can verify
        # by checking direction inversion.
        rf["next_decision_ts"] = rf["decision_ts"].shift(-1)
        rf["next_direction"] = rf["direction"].shift(-1)
        # If next direction is SAME, an ETH flip happened in between
        # → we can't determine the exit cleanly; drop those.
        invalid = (rf["next_direction"] == rf["direction"]) & \
                    rf["next_decision_ts"].notna()
        rf = rf[~invalid].copy()
        # Drop last row (no exit)
        rf = rf[rf["next_decision_ts"].notna()].copy()
        # Cap exit_ts at decision_ts + 4 hours to avoid overnight
        # carry; if next flip is > 4h away, drop the row (regime
        # likely flipped during ETH back-and-forth).
        max_hold_ns = 4 * 3600 * 1_000_000_000
        rf["hold_ns"] = rf["next_decision_ts"] - rf["decision_ts"]
        rf = rf[rf["hold_ns"] <= max_hold_ns].copy().reset_index(drop=True)
        rf["year"] = yr
        rf = rf.rename(columns={"next_decision_ts": "exit_ts",
                                  "atr_1m": "atr"})
        print(f"  regime_flip rows after filtering: {len(rf):,}")

        bars = load_year_bars(yr)
        ts_idx = bars.index.astype("int64").to_numpy()
        opens = bars["open"].values.astype(np.float64)
        highs = bars["high"].values.astype(np.float64)
        lows = bars["low"].values.astype(np.float64)
        closes = bars["close"].values.astype(np.float64)

        for _, r in rf.iterrows():
            decision_ts = int(r["decision_ts"])
            exit_ts = int(r["exit_ts"])
            direction = int(r["direction"])
            atr = float(r["atr"])
            if atr <= 0 or pd.isna(atr): continue
            # T0 entry: OPEN of next 1s bar at decision_ts
            j0 = np.searchsorted(ts_idx, decision_ts, side="left")
            if j0 >= len(opens): continue
            fill_px = float(opens[j0])
            # Exit at OPEN of next 1s bar at exit_ts
            je = np.searchsorted(ts_idx, exit_ts, side="left")
            if je >= len(opens): continue
            exit_px = float(opens[je])
            # T0 baseline PnL
            pts_T0 = ((exit_px - fill_px) if direction == 1
                       else (fill_px - exit_px))
            baseline_pnl = pts_T0 * NQ_MULT - 2 * COMMISSION

            row = {
                "year": yr,
                "decision_ts": decision_ts,
                "exit_ts": exit_ts,
                "direction": direction,
                "atr": atr,
                "fill_px": fill_px,
                "exit_px": exit_px,
                "baseline_pnl": baseline_pnl,
            }

            # Checkpoints
            for cp_s, cp_lab in zip(CHECKPOINTS_S, CHECKPOINT_LABELS):
                cp_ts = decision_ts + cp_s * 1_000_000_000
                if cp_ts >= exit_ts:
                    row[f"alive_{cp_lab}"] = False
                    row[f"d_pnl_{cp_lab}"] = 0.0
                    continue
                jc = np.searchsorted(ts_idx, cp_ts, side="left")
                if jc >= len(opens):
                    row[f"alive_{cp_lab}"] = False
                    row[f"d_pnl_{cp_lab}"] = 0.0
                    continue
                price_at_cp = float(opens[jc])
                pts_d = ((exit_px - price_at_cp) if direction == 1
                          else (price_at_cp - exit_px))
                d_pnl = pts_d * NQ_MULT - 2 * COMMISSION
                row[f"alive_{cp_lab}"] = True
                row[f"d_pnl_{cp_lab}"] = d_pnl
                row[f"price_at_cp_{cp_lab}"] = price_at_cp

                # Features at the checkpoint (using T0 entry frame)
                feats = compute_features(
                    decision_ts, cp_ts, direction, atr, fill_px,
                    ts_idx, opens, highs, lows, closes)
                if feats:
                    for k, v in feats.items():
                        row[f"{k}_{cp_lab}"] = v

            all_rows.append(row)

    return pd.DataFrame(all_rows)


def metrics(df, pnl_col):
    if not len(df):
        return {"n": 0, "total": 0.0, "per_tr": 0.0, "max_dd": 0.0,
                "y2024": 0.0, "y2025": 0.0, "y2026": 0.0,
                "pos_months": 0, "total_months": 0}
    df = df.sort_values("decision_ts").copy()
    total = df[pnl_col].sum()
    n = len(df)
    df["cum"] = df[pnl_col].cumsum()
    df["cum_max"] = df["cum"].cummax()
    max_dd = float((df["cum"] - df["cum_max"]).min())
    y = df.groupby("year")[pnl_col].sum()
    df["entry_dt"] = pd.to_datetime(df["decision_ts"], unit="ns",
                                        utc=True)
    df["month"] = df["entry_dt"].dt.to_period("M")
    monthly = df.groupby("month")[pnl_col].sum()
    return {
        "n": n, "total": float(total), "per_tr": float(total / n),
        "max_dd": max_dd,
        "y2024": float(y.get(2024, 0.0)),
        "y2025": float(y.get(2025, 0.0)),
        "y2026": float(y.get(2026, 0.0)),
        "pos_months": int((monthly > 0).sum()),
        "total_months": int(len(monthly)),
    }


def print_row(label, m, indent="  "):
    pos_str = f"{m['pos_months']}/{m['total_months']}"
    print(f"{indent}{label:<42}  {m['n']:>5,}  "
          f"${m['total']:>+10,.0f}  {m['per_tr']:>+7.2f}  "
          f"${m['max_dd']:>+9,.0f}  "
          f"${m['y2024']:>+9,.0f}  ${m['y2025']:>+9,.0f}  "
          f"${m['y2026']:>+9,.0f}  {pos_str:>6}")


def main():
    t0 = time.time()
    print("=" * 78)
    print("ALL-REGIME-FLIPS  MATCHED-BASELINE COMPARISON")
    print("Anchor: decision_ts (= flip_bar_close + ~1s)")
    print("=" * 78)

    feats_path = OUT / "all_flips_features.parquet"
    if feats_path.exists():
        print("\nLoading cached features...")
        df = pd.read_parquet(feats_path)
    else:
        print("\nComputing features (this may take a few min)...")
        df = collect_all_flips()
        df.to_parquet(feats_path)
    n_pre = len(df)
    # Dedupe at year boundary (same trade in two year-file collector runs)
    df = df.sort_values(["decision_ts", "year"]).drop_duplicates(
        subset="decision_ts", keep="first").reset_index(drop=True)
    if n_pre != len(df):
        print(f"  deduped cross-year overlaps: "
              f"{n_pre:,} → {len(df):,}  (-{n_pre - len(df)})")
    print(f"\n  total regime-flip events: {len(df):,}")
    # Per-year + cohort sizes
    print(f"\n  Per-year flip counts and cohort survival:")
    print(f"  {'year':<5}  {'n flips':>8}  {'alive +6m':>10}  "
          f"{'alive +8m':>10}")
    for yr in (2024, 2025, 2026):
        sub = df[df["year"] == yr]
        a6 = sub["alive_6m"].sum()
        a8 = sub["alive_8m"].sum()
        print(f"  {yr:<5}  {len(sub):>8,}  "
              f"{a6:>7,} ({100*a6/len(sub):.0f}%)  "
              f"{a8:>7,} ({100*a8/len(sub):.0f}%)")

    # ===== Fix thresholds from IS-only =====
    assert set(df["year"].unique()).issubset({2024, 2025, 2026})
    is_alive_6m = df[df["alive_6m"]
                       & df["year"].isin([2024, 2025])
                       & df["f_unr_pnl_T_6m"].notna()]
    assert is_alive_6m["year"].max() <= 2025
    thr_unr_6m = is_alive_6m["f_unr_pnl_T_6m"].quantile(0.80)
    print(f"\n  +6m filter threshold (IS q=0.80): "
          f"f_unr_pnl_T >= ${thr_unr_6m:.0f}")

    is_alive_8m = df[df["alive_8m"]
                       & df["year"].isin([2024, 2025])
                       & df["f_net_move_150s_8m"].notna()
                       & df["f_net_move_300s_8m"].notna()]
    assert is_alive_8m["year"].max() <= 2025
    thr_150_8m = is_alive_8m["f_net_move_150s_8m"].quantile(0.10)
    thr_300_8m = is_alive_8m["f_net_move_300s_8m"].quantile(0.20)
    print(f"  +8m filter thresholds (IS-fit): "
          f"f_net_move_150s >= ${thr_150_8m:.2f}, "
          f"f_net_move_300s >= ${thr_300_8m:.2f}")

    # ===== Build cohorts =====
    alive_6m = df[df["alive_6m"]].copy()
    alive_8m = df[df["alive_8m"]].copy()

    c6_mask = alive_6m["f_unr_pnl_T_6m"] >= thr_unr_6m
    e8_mask = ((alive_8m["f_net_move_150s_8m"] >= thr_150_8m)
                 & (alive_8m["f_net_move_300s_8m"] >= thr_300_8m))

    # ===== Compute metrics =====
    full_T0 = metrics(df, "baseline_pnl")
    A6m_T0  = metrics(alive_6m, "baseline_pnl")
    B6      = metrics(alive_6m, "d_pnl_6m")
    C6      = metrics(alive_6m[c6_mask], "d_pnl_6m")
    C6_T0   = metrics(alive_6m[c6_mask], "baseline_pnl")

    A8m_T0  = metrics(alive_8m, "baseline_pnl")
    D8      = metrics(alive_8m, "d_pnl_8m")
    E8      = metrics(alive_8m[e8_mask], "d_pnl_8m")
    E8_T0   = metrics(alive_8m[e8_mask], "baseline_pnl")

    # ===== Report =====
    print(f"\n{'='*120}")
    print("ALL-FLIPS STRATEGIES")
    print(f"{'='*120}")
    print(f"  {'strategy':<42}  {'n':>5}  {'total$':>11}  {'$/tr':>7}  "
          f"{'max DD':>10}  {'2024':>10}  {'2025':>10}  {'2026':>10}  "
          f"{'+mo':>6}")
    print("  " + "-" * 118)
    print_row("(context) full all-flips 1c T0", full_T0)
    print()
    print(f"  +6m cohort (alive @ +6m, n={len(alive_6m):,})")
    print_row("A6m_T0  matched T0 (alive@6m cohort)", A6m_T0)
    print_row("B6      delayed-only @+6m", B6)
    print_row("C6      delayed @+6m + unr filter", C6)
    print_row("  C6_T0  same filtered cohort, T0 entry", C6_T0,
                indent="    ")
    print()
    print(f"  +8m cohort (alive @ +8m, n={len(alive_8m):,})")
    print_row("A8m_T0  matched T0 (alive@8m cohort)", A8m_T0)
    print_row("D8      delayed-only @+8m", D8)
    print_row("E8      delayed @+8m + dual momentum", E8)
    print_row("  E8_T0  same filtered cohort, T0 entry", E8_T0,
                indent="    ")

    # ===== Pairwise lifts =====
    print(f"\n{'='*120}")
    print("PAIRWISE LIFT (delayed/filtered  vs  matched T0)")
    print(f"{'='*120}")
    print(f"  {'comparison':<60}  {'Δtotal':>10}  {'Δ$/tr':>7}  "
          f"{'Δ2024':>10}  {'Δ2025':>10}  {'Δ2026':>10}")

    def diff(a, b, label):
        return (f"{label:<60}  ${a['total']-b['total']:>+8,.0f}  "
                f"{a['per_tr']-b['per_tr']:>+7.2f}  "
                f"${a['y2024']-b['y2024']:>+8,.0f}  "
                f"${a['y2025']-b['y2025']:>+8,.0f}  "
                f"${a['y2026']-b['y2026']:>+8,.0f}")

    print("  " + diff(B6, A6m_T0, "B6 (delay+6m) vs A6m_T0"))
    print("  " + diff(C6, A6m_T0, "C6 (+6m+filter) vs A6m_T0"))
    print("  " + diff(C6, C6_T0, "C6 (+6m+filter) vs C6_T0 (same trades, T0)"))
    print("  " + diff(D8, A8m_T0, "D8 (delay+8m) vs A8m_T0"))
    print("  " + diff(E8, A8m_T0, "E8 (+8m+dual) vs A8m_T0"))
    print("  " + diff(E8, E8_T0, "E8 (+8m+dual) vs E8_T0 (same trades, T0)"))

    # ===== Side-by-side with V_A results (loaded from V_A matched output) =====
    print(f"\n{'='*120}")
    print("ALL-FLIPS vs V_A (analogous strategies — same methodology)")
    print(f"  NOTE: V_A timing has +30s misalignment vs all-flips here")
    print(f"        due to legacy entry_ts delay. V_A '+5m'=flip+6.5m,")
    print(f"        all-flips '+6m'=flip+6m. Comparison is approximate.")
    print(f"{'='*120}")
    # Load V_A matched results from prior run (just the headlines)
    print(f"  {'metric':<42}  {'all-flips':>10}  {'V_A (prior)':>12}  "
          f"{'ratio':>6}")
    print("  " + "-" * 80)
    # T0 full baselines
    print(f"  {'Full T0 baseline n':<42}  {full_T0['n']:>10,}  "
          f"{'(7,745)':>12}")
    print(f"  {'Full T0 baseline total $':<42}  "
          f"${full_T0['total']:>+8,.0f}  {'(+$33,700)':>12}")
    print(f"  {'A_T0 alive cohort total $':<42}  "
          f"${A6m_T0['total']:>+8,.0f}  {'(A_5m +$816,745)':>12}")
    print(f"  {'B delayed-only +6m total $':<42}  "
          f"${B6['total']:>+8,.0f}  {'(B +$50,520)':>12}")
    print(f"  {'C +6m+unr filter total $':<42}  "
          f"${C6['total']:>+8,.0f}  {'(C +$61,370)':>12}")
    print(f"  {'C +6m+unr filter $/tr':<42}  "
          f"{C6['per_tr']:>+10.2f}  {'(C +$48.36)':>12}")
    print(f"  {'D delayed-only +8m total $':<42}  "
          f"${D8['total']:>+8,.0f}  {'(D +$46,525)':>12}")
    print(f"  {'E +8m+dual mom total $':<42}  "
          f"${E8['total']:>+8,.0f}  {'(E +$65,415)':>12}")
    print(f"  {'E +8m+dual mom $/tr':<42}  "
          f"{E8['per_tr']:>+10.2f}  {'(E +$16.82)':>12}")

    # ===== Monthly for C6 and E8 =====
    print(f"\n{'='*120}")
    print("MONTHLY PnL — C6 (+6m + unr filter, all flips)")
    print(f"{'='*120}")
    sub = alive_6m[c6_mask].sort_values("decision_ts").copy()
    sub["month"] = pd.to_datetime(sub["decision_ts"], unit="ns",
                                      utc=True).dt.to_period("M")
    monthly = sub.groupby("month").agg(
        n=("d_pnl_6m", "size"), pnl=("d_pnl_6m", "sum"),
    )
    monthly["cum"] = monthly["pnl"].cumsum()
    for m, row in monthly.iterrows():
        marker = "+" if row["pnl"] > 0 else "-"
        print(f"  {m}  n={int(row['n']):>3,}  "
              f"${row['pnl']:>+8,.0f} {marker}  "
              f"cum=${row['cum']:>+9,.0f}")

    print(f"\n{'='*120}")
    print("MONTHLY PnL — E8 (+8m + dual momentum, all flips)")
    print(f"{'='*120}")
    sub = alive_8m[e8_mask].sort_values("decision_ts").copy()
    sub["month"] = pd.to_datetime(sub["decision_ts"], unit="ns",
                                      utc=True).dt.to_period("M")
    monthly = sub.groupby("month").agg(
        n=("d_pnl_8m", "size"), pnl=("d_pnl_8m", "sum"),
    )
    monthly["cum"] = monthly["pnl"].cumsum()
    for m, row in monthly.iterrows():
        marker = "+" if row["pnl"] > 0 else "-"
        print(f"  {m}  n={int(row['n']):>3,}  "
              f"${row['pnl']:>+8,.0f} {marker}  "
              f"cum=${row['cum']:>+9,.0f}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
