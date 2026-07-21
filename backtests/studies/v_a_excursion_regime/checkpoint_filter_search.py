"""Checkpoint filter search for delayed-only entry at +5m and +7m.

Goal: at the moment of delayed entry (+5m or +7m from original V_A
signal), compute features that distinguish trades that will go on to
succeed vs fail (label = sign of d_pnl when held to regime exit).

Features at the checkpoint:
  Trade history (since V_A entry → checkpoint):
    f_mfe_atr_T              MFE / atr_at_signal
    f_mae_atr_T              MAE / atr_at_signal
    f_unr_pnl_T              Unrealized $ at checkpoint
    f_mfe_to_mae             MFE / MAE ratio
    f_close_loc_in_range     close position in [low, high] of segment
  Momentum (causal, ending strictly before checkpoint):
    f_net_move_30s           direction-aware 30s net move ($)
    f_net_move_60s           60s net move ($)
    f_net_move_150s          150s net move ($) (xfast)
    f_net_move_300s          300s net move ($)
  Context:
    f_atr                    atr_at_signal
    f_direction              long=+1, short=-1
    f_hour_utc               hour of day (UTC)

Analysis:
  1. Univariate quintile PnL — for each feature, split alive cohort
     into 5 quantiles and report mean d_pnl per quintile.
  2. Threshold sweep — for the most predictive features, sweep
     "skip if feature < / > X" thresholds. Report:
       n_kept, % kept, total_$, $/tr, vs no-filter
       per-year and IS (2024+2025) vs OOS (2026)
  3. Best AND-pair combinations.

Causality: every feature read uses bars with ts_event < cp_ts.
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

CHECKPOINTS_S = [300, 420]
CHECKPOINT_LABELS = ["5m", "7m"]

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
    """Compute checkpoint features. Causal — strictly < cp_ts."""
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

    # Momentum windows ending strictly before cp_ts
    for win_s, name in [(30, "30s"), (60, "60s"),
                          (150, "150s"), (300, "300s")]:
        win_start = cp_ts - win_s * 1_000_000_000
        i_lo = np.searchsorted(ts_idx, win_start, side="left")
        # Need at least win_s/2 bars present
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


def collect_features():
    """Compute checkpoint features for each V_A trade × each cp."""
    rows = []
    for yr in (2024, 2025, 2026):
        print(f"  loading {yr}...", flush=True)
        base = Path(f"collectors/collector_v2/results/v_a_v0_{yr}")
        trades = pd.read_parquet(base / "trades.parquet")
        bars = load_year_bars(yr)
        ts_idx = bars.index.astype("int64").to_numpy()
        opens = bars["open"].values.astype(np.float64)
        highs = bars["high"].values.astype(np.float64)
        lows = bars["low"].values.astype(np.float64)
        closes = bars["close"].values.astype(np.float64)

        for _, tr in trades.iterrows():
            entry_ts = int(tr["entry_ts"])
            exit_ts = int(tr["exit_ts"])
            direction = int(tr["direction"])
            atr = float(tr["atr_at_signal"])
            fill_px = float(tr["fill_price"])
            exit_px = float(tr["exit_price"])

            row = {
                "year": yr, "entry_ts": entry_ts, "exit_ts": exit_ts,
                "direction": direction, "atr": atr,
                "fill_px": fill_px, "exit_px": exit_px,
                "f_hour_utc": pd.Timestamp(entry_ts, unit="ns",
                                              tz="UTC").hour,
            }

            for cp_s, cp_lab in zip(CHECKPOINTS_S, CHECKPOINT_LABELS):
                cp_ts = entry_ts + cp_s * 1_000_000_000
                if cp_ts >= exit_ts:
                    row[f"alive_{cp_lab}"] = False
                    row[f"d_pnl_{cp_lab}"] = 0.0
                    continue
                j_hi = np.searchsorted(ts_idx, cp_ts, side="left")
                if j_hi >= len(opens):
                    row[f"alive_{cp_lab}"] = False
                    row[f"d_pnl_{cp_lab}"] = 0.0
                    continue
                price_at_cp = float(opens[j_hi])

                if direction == 1:
                    pts = exit_px - price_at_cp
                else:
                    pts = price_at_cp - exit_px
                d_pnl = pts * NQ_MULT - 2 * COMMISSION

                row[f"alive_{cp_lab}"] = True
                row[f"d_pnl_{cp_lab}"] = d_pnl
                row[f"price_at_cp_{cp_lab}"] = price_at_cp

                feats = compute_features(
                    entry_ts, cp_ts, direction, atr, fill_px,
                    ts_idx, opens, highs, lows, closes)
                if feats is None:
                    continue
                for k, v in feats.items():
                    row[f"{k}_{cp_lab}"] = v

            rows.append(row)
    return pd.DataFrame(rows)


def quintile_analysis(df, cp_lab, feature):
    """Split alive cohort by feature quintile, report d_pnl per bucket.
    Quintile EDGES + MEANS for feature ranking are computed on IS-only
    (2024+2025). Returns dict with `is_summary` and `oos_summary` so we
    can rank features by IS spread without leaking 2026."""
    fcol = f"{feature}_{cp_lab}"
    pcol = f"d_pnl_{cp_lab}"
    alive = df[(df[f"alive_{cp_lab}"]) & df[fcol].notna()].copy()
    if len(alive) < 50: return None
    is_alive = alive[alive["year"].isin([2024, 2025])].copy()
    oos_alive = alive[alive["year"] == 2026].copy()
    if len(is_alive) < 50: return None
    # qcut on IS only to get edges
    try:
        _, edges = pd.qcut(is_alive[fcol], 5, retbins=True,
                              duplicates="drop")
    except ValueError:
        return None
    if len(edges) < 3: return None
    is_alive["q"] = pd.cut(is_alive[fcol], bins=edges, labels=False,
                              include_lowest=True)
    is_alive = is_alive.dropna(subset=["q"])
    is_summary = is_alive.groupby("q").agg(
        n=(pcol, "size"), total=(pcol, "sum"),
        mean=(pcol, "mean"), wr=(pcol, lambda x: (x > 0).mean() * 100),
        f_min=(fcol, "min"), f_max=(fcol, "max"),
    ).reset_index()
    # OOS binned with same IS-derived edges (for descriptive view only)
    oos_alive["q"] = pd.cut(oos_alive[fcol], bins=edges, labels=False,
                                include_lowest=True)
    oos_alive = oos_alive.dropna(subset=["q"])
    if len(oos_alive) >= 10:
        oos_summary = oos_alive.groupby("q").agg(
            n=(pcol, "size"), mean=(pcol, "mean"),
            wr=(pcol, lambda x: (x > 0).mean() * 100),
        ).reset_index()
    else:
        oos_summary = None
    return {"is": is_summary, "oos": oos_summary}


def threshold_sweep(df, cp_lab, feature, direction="ge",
                       quantiles=None):
    """Sweep thresholds on a feature. direction='ge' means KEEP if
    feature >= threshold. 'le' means KEEP if feature <= threshold.
    THRESHOLDS ARE FIT ON IS-ONLY (2024+2025). OOS (2026) is evaluated
    at the same fixed threshold to avoid distributional leakage."""
    fcol = f"{feature}_{cp_lab}"
    pcol = f"d_pnl_{cp_lab}"
    alive = df[df[f"alive_{cp_lab}"]].copy()
    is_alive = alive[alive["year"].isin([2024, 2025])]
    if quantiles is None:
        quantiles = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30,
                       0.40, 0.50, 0.60, 0.70, 0.80]
    rows = []
    full_n = len(alive)
    full_total = alive[pcol].sum()
    for q in quantiles:
        thr = is_alive[fcol].quantile(q)
        if pd.isna(thr): continue
        if direction == "ge":
            keep = alive[fcol] >= thr
        else:
            keep = alive[fcol] <= thr
        kept = alive[keep]
        # IS / OOS split
        is_mask = alive["year"].isin([2024, 2025])
        oos_mask = alive["year"] == 2026
        is_kept = alive[keep & is_mask]
        oos_kept = alive[keep & oos_mask]
        is_full = alive[is_mask]
        oos_full = alive[oos_mask]
        rows.append({
            "q": q, "thr": thr,
            "n_kept": len(kept), "kept_pct": 100 * len(kept) / full_n,
            "total_kept": kept[pcol].sum(),
            "vs_nofilter": kept[pcol].sum() - full_total,
            "is_n": len(is_kept), "is_total": is_kept[pcol].sum(),
            "is_per_tr": (is_kept[pcol].sum() / len(is_kept)
                          if len(is_kept) else 0),
            "is_lift": is_kept[pcol].sum() - is_full[pcol].sum(),
            "oos_n": len(oos_kept), "oos_total": oos_kept[pcol].sum(),
            "oos_per_tr": (oos_kept[pcol].sum() / len(oos_kept)
                           if len(oos_kept) else 0),
            "oos_lift": oos_kept[pcol].sum() - oos_full[pcol].sum(),
        })
    return pd.DataFrame(rows)


def main():
    t0 = time.time()
    print("=" * 78)
    print("CHECKPOINT FILTER SEARCH — +5m and +7m delayed entries")
    print("=" * 78)

    feat_path = OUT / "checkpoint_features.parquet"
    if feat_path.exists():
        print("\nLoading cached features...")
        df = pd.read_parquet(feat_path)
    else:
        print("\nComputing features (this may take ~30s)...")
        df = collect_features()
        df.to_parquet(feat_path)
    print(f"  total trades: {len(df):,}")

    # ===== Sanity check: cohort sizes & PnL =====
    print(f"\n{'='*78}")
    print("BASELINE — delayed-only PnL (no filter)")
    print(f"{'='*78}")
    print(f"  {'cp':<4}  {'n alive':>8}  {'2024':>10}  {'2025':>10}  "
          f"{'2026':>10}  {'ALL':>10}  {'$/tr':>7}")
    for cp_lab in CHECKPOINT_LABELS:
        alive = df[df[f"alive_{cp_lab}"]]
        print(f"  +{cp_lab:<3}  {len(alive):>8,}", end="")
        for yr in (2024, 2025, 2026):
            sub = alive[alive["year"] == yr]
            print(f"  ${sub[f'd_pnl_{cp_lab}'].sum():>+8,.0f}", end="")
        total = alive[f'd_pnl_{cp_lab}'].sum()
        print(f"  ${total:>+8,.0f}  {total/len(alive):>+6.2f}")

    # ===== Univariate quintile analysis =====
    candidate_feats = [
        "f_mfe_atr_T", "f_mae_atr_T", "f_unr_pnl_T",
        "f_mfe_to_mae", "f_close_loc_in_range",
        "f_net_move_30s", "f_net_move_60s",
        "f_net_move_150s", "f_net_move_300s",
        "f_atr",
    ]

    print(f"\n{'='*78}")
    print("UNIVARIATE QUINTILE ANALYSIS  (mean $ d_pnl by quintile)")
    print("Quintile 1 = lowest values, Quintile 5 = highest values.")
    print("Spread (Q5-Q1) > 0 means HIGH values do better → KEEP if >= ...")
    print("Spread (Q5-Q1) < 0 means LOW values do better → KEEP if <= ...")
    print(f"{'='*78}")

    spread_summary = {}
    for cp_lab in CHECKPOINT_LABELS:
        print(f"\n--- checkpoint +{cp_lab} (IS=2024+2025 only) ---")
        rows_to_show = []
        for feat in candidate_feats:
            res = quintile_analysis(df, cp_lab, feat)
            if res is None: continue
            q = res["is"]
            oos = res["oos"]
            spread = q.iloc[-1]["mean"] - q.iloc[0]["mean"]
            # Also OOS spread (validation, not selection)
            oos_spread = (oos.iloc[-1]["mean"] - oos.iloc[0]["mean"]
                            if oos is not None and len(oos) >= 2 else np.nan)
            spread_summary[(cp_lab, feat)] = spread
            rows_to_show.append({
                "feature": feat,
                "is_q1_mean": q.iloc[0]["mean"],
                "is_q3_mean": q.iloc[2]["mean"] if len(q) > 2 else np.nan,
                "is_q5_mean": q.iloc[-1]["mean"],
                "is_spread": spread,
                "oos_spread": oos_spread,
            })
        out = pd.DataFrame(rows_to_show)
        out = out.sort_values("is_spread",
                                key=lambda x: x.abs(), ascending=False)
        print(out.to_string(index=False, float_format=lambda x: f"{x:+.2f}"))

    # ===== Threshold sweep on top features =====
    print(f"\n{'='*78}")
    print("THRESHOLD SWEEP — top features per checkpoint")
    print(f"{'='*78}")

    for cp_lab in CHECKPOINT_LABELS:
        # Pick top 4 features by absolute spread
        cp_spreads = [(f, sp) for (cp, f), sp in spread_summary.items()
                       if cp == cp_lab]
        cp_spreads.sort(key=lambda x: abs(x[1]), reverse=True)
        top = cp_spreads[:5]
        print(f"\n--- checkpoint +{cp_lab} ---")
        print(f"  Top features by Q5-Q1 spread:")
        for f, sp in top:
            print(f"    {f}: spread = {sp:+.2f}")

        for feat, spread in top:
            direction = "ge" if spread > 0 else "le"
            print(f"\n  >> {feat}  (KEEP if {direction})")
            print(f"     {'q':>5}  {'thr':>9}  {'kept':>6}  "
                  f"{'kept%':>6}  {'IS$':>10}  {'IS$/tr':>7}  "
                  f"{'IS_lift':>8}  {'OOS$':>9}  {'OOS$/tr':>8}  "
                  f"{'OOS_lift':>8}")
            sw = threshold_sweep(df, cp_lab, feat, direction=direction)
            for _, r in sw.iterrows():
                print(f"     {r['q']:>5.2f}  {r['thr']:>+8.2f}  "
                      f"{int(r['n_kept']):>6,}  "
                      f"{r['kept_pct']:>5.1f}%  "
                      f"${r['is_total']:>+8,.0f}  "
                      f"{r['is_per_tr']:>+6.2f}  "
                      f"${r['is_lift']:>+6,.0f}  "
                      f"${r['oos_total']:>+7,.0f}  "
                      f"{r['oos_per_tr']:>+7.2f}  "
                      f"${r['oos_lift']:>+6,.0f}")

    # ===== AND-pair combinations on top 3 features =====
    print(f"\n{'='*78}")
    print("AND-PAIR COMBINATIONS — best 2-feature filters")
    print(f"{'='*78}")

    for cp_lab in CHECKPOINT_LABELS:
        print(f"\n--- checkpoint +{cp_lab} ---")
        cp_spreads = [(f, sp) for (cp, f), sp in spread_summary.items()
                       if cp == cp_lab]
        cp_spreads.sort(key=lambda x: abs(x[1]), reverse=True)
        top3 = cp_spreads[:3]

        alive = df[df[f"alive_{cp_lab}"]].copy()
        is_alive = alive[alive["year"].isin([2024, 2025])]
        is_full = is_alive[f"d_pnl_{cp_lab}"].sum()
        oos_full = alive[alive["year"] == 2026][f"d_pnl_{cp_lab}"].sum()
        full_n = len(alive)
        print(f"  baseline  IS=${is_full:+,.0f}  OOS=${oos_full:+,.0f}  "
              f"n={full_n:,}  (thresholds fit on IS-only)")
        print(f"  {'feat_A':<22}  {'qA':>3}  {'feat_B':<22}  {'qB':>3}  "
              f"{'kept':>5}  {'kept%':>6}  {'IS$':>9}  {'IS_lift':>8}  "
              f"{'OOS$':>9}  {'OOS_lift':>8}")

        rows = []
        for fa, sa in top3:
            for fb, sb in top3:
                if fa >= fb: continue
                dir_a = "ge" if sa > 0 else "le"
                dir_b = "ge" if sb > 0 else "le"
                fcol_a = f"{fa}_{cp_lab}"
                fcol_b = f"{fb}_{cp_lab}"
                for qa in [0.10, 0.20, 0.30]:
                    for qb in [0.10, 0.20, 0.30]:
                        thr_a = is_alive[fcol_a].quantile(qa)
                        thr_b = is_alive[fcol_b].quantile(qb)
                        if pd.isna(thr_a) or pd.isna(thr_b): continue
                        if dir_a == "ge":
                            ka = alive[fcol_a] >= thr_a
                        else:
                            ka = alive[fcol_a] <= thr_a
                        if dir_b == "ge":
                            kb = alive[fcol_b] >= thr_b
                        else:
                            kb = alive[fcol_b] <= thr_b
                        keep = ka & kb
                        kept = alive[keep]
                        if len(kept) < 200: continue
                        is_kept = kept[kept["year"].isin([2024, 2025])]
                        oos_kept = kept[kept["year"] == 2026]
                        if len(is_kept) < 100 or len(oos_kept) < 30:
                            continue
                        rows.append({
                            "fa": fa, "qa": qa, "fb": fb, "qb": qb,
                            "n": len(kept),
                            "is": is_kept[f"d_pnl_{cp_lab}"].sum(),
                            "is_lift": is_kept[f"d_pnl_{cp_lab}"].sum()
                                        - is_full,
                            "oos": oos_kept[f"d_pnl_{cp_lab}"].sum(),
                            "oos_lift": oos_kept[f"d_pnl_{cp_lab}"].sum()
                                          - oos_full,
                        })
        rows = pd.DataFrame(rows)
        if not len(rows):
            print("  (no valid pairs)")
            continue
        # Sort by combined IS+OOS lift (with both >0 preferred)
        rows["combined_lift"] = rows["is_lift"] + rows["oos_lift"]
        rows["both_positive"] = ((rows["is_lift"] > 0)
                                   & (rows["oos_lift"] > 0))
        rows = rows.sort_values(
            ["both_positive", "combined_lift"], ascending=[False, False]
        ).head(10)
        for _, r in rows.iterrows():
            print(f"  {r['fa']:<22}  {r['qa']:>3.2f}  "
                  f"{r['fb']:<22}  {r['qb']:>3.2f}  "
                  f"{int(r['n']):>5,}  "
                  f"{100*r['n']/full_n:>5.1f}%  "
                  f"${r['is']:>+7,.0f}  ${r['is_lift']:>+6,.0f}  "
                  f"${r['oos']:>+7,.0f}  ${r['oos_lift']:>+6,.0f}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
