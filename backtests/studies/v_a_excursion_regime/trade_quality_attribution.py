"""Trade-quality attribution study on V_A + total_excursion_slow=mid (T0).

Classifies each filtered trade into 5 mutually-exclusive classes:
  1. good_runner       — final MFE_atr >= 3.0
  2. good_normal_win   — net_pnl > 0 AND final MFE_atr < 3.0  (V4 doesn't fire)
  3. v4_false_exit     — V4 fires AND baseline net_pnl > 0  (V4 cuts a winner)
  4. v4_true_save      — V4 fires AND baseline net_pnl <= 0  (V4 saves a loser)
  5. v4_missed_loser   — V4 doesn't fire AND net_pnl <= 0   (V4 misses a loser)

For each (trade, checkpoint) at +1m / +2m / +3m / +4m, computes:
  Trade-state:
    unrealized_pnl, current_mfe_atr, current_mae_atr, mfe_to_mae,
    close_loc_in_range, dd_from_peak_mfe_atr, rec_from_max_mae_atr
  Rolling micro-regime:
    ratio_xfast, ratio_fast, net_move_xfast, net_move_fast,
    efficiency_xfast, efficiency_fast,
    adverse_dominant_xfast (mae>mfe), improving_xfast vs prior_cp
  Entry-trigger (one per trade, from snapshots):
    bar1_body_pct, bar1_close_loc, bar1_range_atr,
    hhll_extension_atr, dist_from_ema3_atr, dist_from_ema9_atr,
    flip_bar_range_atr, dist_from_flip_close_atr,
    excursion_slow_pre_entry

Outputs:
  - feature distributions (median, p25, p75) per class
  - separation scores between class pairs:
      false_exit (3) vs true_save (4)   — what makes V4 wrong?
      runner (1) vs missed_loser (5)    — could earlier check flag missed losers?
      good_normal_win (2) vs v4_false_exit (3) — winner detection
  - top features by |separation| at each checkpoint
  - candidate rules table (no thresholds optimized)

V4 reproduced inline:
  candidate at +3m: unr<-50 AND mfe_atr<0.25
  confirm at +4m: unr<0 AND mfe_atr<0.35 AND xfast_net_move<0
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
SLOW_LO_CUT = 43.00
SLOW_HI_CUT = 71.75
CHECKPOINT_S = [60, 120, 180, 240]
CHECKPOINT_LABELS = ["+1m", "+2m", "+3m", "+4m"]

OUT = Path("studies/v_a_excursion_regime/results_v0")


def load_year_bars(year):
    files_for_year = {
        2024: ["data/raw/NQ_v0_1s_2023.parquet",
                "data/raw/NQ_v0_1s_2024.parquet"],
        2025: ["data/raw/NQ_v0_1s_2024.parquet",
                "data/raw/NQ_v0_1s_2025.parquet"],
        2026: ["data/raw/NQ_v0_1s_2025.parquet",
                "data/raw/NQ_v0_1s_2026_ytd.parquet"],
    }
    parts = []
    for f in files_for_year[year]:
        if Path(f).exists():
            df = pd.read_parquet(f, columns=["open","high","low","close"])
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            parts.append(df)
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    return bars


def features_at_tick(t_ns, direction, atr, ts_idx, opens, highs, lows,
                       closes, entry_ts, fill_px, prev_cp_state):
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
        # close location within MFE/MAE band
        peak_high = float(seg_h.max())
        trough_low = float(seg_l.min())
        if peak_high > trough_low:
            close_loc = (seg_c - trough_low) / (peak_high - trough_low)
        else:
            close_loc = 0.5
        # current price vs peak high (drawdown from peak MFE)
        dd_from_peak_atr = (peak_high - seg_c) / max(atr, 0.01)
        # current price vs trough low (recovery from max MAE)
        rec_from_max_atr = (seg_c - trough_low) / max(atr, 0.01)
    else:
        cur_mfe = float(fill_px - seg_l.min())
        cur_mae = float(seg_h.max() - fill_px)
        unr_pts = float(fill_px - seg_c)
        peak_low = float(seg_l.min())
        trough_high = float(seg_h.max())
        if trough_high > peak_low:
            close_loc = (trough_high - seg_c) / (trough_high - peak_low)
        else:
            close_loc = 0.5
        dd_from_peak_atr = (seg_c - peak_low) / max(atr, 0.01)
        rec_from_max_atr = (trough_high - seg_c) / max(atr, 0.01)

    out = {
        "unrealized_pnl": unr_pts * NQ_MULT,
        "current_mfe_atr": cur_mfe / max(atr, 0.01),
        "current_mae_atr": cur_mae / max(atr, 0.01),
        "mfe_to_mae": cur_mfe / max(cur_mae, 0.25),
        "close_loc_in_range": close_loc,
        "dd_from_peak_mfe_atr": dd_from_peak_atr,
        "rec_from_max_mae_atr": rec_from_max_atr,
    }

    # Rolling windows: xfast (2.5min), fast (5min)
    for win_name, win_secs in (("xfast", 5*30), ("fast", 5*60)):
        win_start = t_ns - win_secs * 1_000_000_000
        i_lo = np.searchsorted(ts_idx, win_start, side="left")
        if j_hi - i_lo < 30:
            for k in ("ratio", "net_move", "efficiency", "mfe", "mae"):
                out[f"{k}_{win_name}"] = np.nan
            continue
        anchor_open = float(opens[i_lo])
        hi = float(highs[i_lo:j_hi].max())
        lo = float(lows[i_lo:j_hi].min())
        close_now = float(closes[j_hi - 1])
        if direction == 1:
            mfe = hi - anchor_open
            mae = anchor_open - lo
            net = close_now - anchor_open
        else:
            mfe = anchor_open - lo
            mae = hi - anchor_open
            net = anchor_open - close_now
        total_exc = mfe + mae
        out[f"ratio_{win_name}"] = mfe / max(mae, 0.25)
        out[f"net_move_{win_name}"] = net
        out[f"efficiency_{win_name}"] = abs(close_now - anchor_open) / max(total_exc, 0.25)
        out[f"mfe_{win_name}"] = mfe
        out[f"mae_{win_name}"] = mae

    # adverse_dominant flag (xfast)
    out["adverse_dominant_xfast"] = (
        out.get("mae_xfast", 0) > out.get("mfe_xfast", 0))

    # improving from prior CP (any of: mfe_atr up, ratio_xfast up, unr up)
    if prev_cp_state is not None:
        out["mfe_improving"] = (out["current_mfe_atr"]
                                       > prev_cp_state["current_mfe_atr"])
        out["unr_improving"] = (out["unrealized_pnl"]
                                       > prev_cp_state["unrealized_pnl"])
        ratio_now = out.get("ratio_xfast", 0) or 0
        ratio_prev = prev_cp_state.get("ratio_xfast", 0) or 0
        out["xfast_ratio_improving"] = ratio_now > ratio_prev
    else:
        out["mfe_improving"] = False
        out["unr_improving"] = False
        out["xfast_ratio_improving"] = False

    return out


def classify_trade(net_pnl, final_mfe_atr, v4_fired):
    if final_mfe_atr >= 3.0 and net_pnl > 0:
        return "1_good_runner"
    if v4_fired:
        if net_pnl > 0:
            return "3_v4_false_exit"
        else:
            return "4_v4_true_save"
    if net_pnl > 0:
        return "2_good_normal_win"
    return "5_v4_missed_loser"


def compute_v4_decision(s_3m, s_4m):
    if s_3m is None or s_4m is None:
        return False
    if not (s_3m["unrealized_pnl"] < -50
              and s_3m["current_mfe_atr"] < 0.25):
        return False
    if not (s_4m["unrealized_pnl"] < 0
              and s_4m["current_mfe_atr"] < 0.35
              and not pd.isna(s_4m.get("net_move_xfast", np.nan))
              and s_4m["net_move_xfast"] < 0):
        return False
    return True


def entry_trigger_features(snap_b1, atr, fill_px, direction):
    """One row per trade — entry-trigger features from bar1_check snapshot.
    `snap_b1` is a dict with bar1_h/l/o/c, flip_bar_h/l/c, dist_close_to_ema*."""
    bar1_h = snap_b1["bar1_h"]
    bar1_l = snap_b1["bar1_l"]
    bar1_o = snap_b1["bar1_o"]
    bar1_c = snap_b1["bar1_c"]
    flip_h = snap_b1["flip_bar_h"]
    flip_l = snap_b1["flip_bar_l"]
    flip_c = snap_b1["flip_bar_c"]
    out = {}
    bar1_range = bar1_h - bar1_l
    flip_range = flip_h - flip_l
    out["bar1_body_pct"] = ((bar1_c - bar1_o) / bar1_range
                                if bar1_range > 0 else 0.0)
    if direction == 1:
        out["bar1_close_loc"] = ((bar1_c - bar1_l) / bar1_range
                                       if bar1_range > 0 else 0.5)
        out["hhll_extension_atr"] = (bar1_h - flip_h) / max(atr, 0.01)
        out["dist_from_flip_close_atr"] = (fill_px - flip_c) / max(atr, 0.01)
    else:
        out["bar1_close_loc"] = ((bar1_h - bar1_c) / bar1_range
                                       if bar1_range > 0 else 0.5)
        out["hhll_extension_atr"] = (flip_l - bar1_l) / max(atr, 0.01)
        out["dist_from_flip_close_atr"] = (flip_c - fill_px) / max(atr, 0.01)
    out["bar1_range_atr"] = bar1_range / max(atr, 0.01)
    out["flip_bar_range_atr"] = flip_range / max(atr, 0.01)
    # Direction-aware EMA distance: positive = above EMA-h (bullish trend)
    out["dist_from_ema3_atr"] = (snap_b1.get("dist_close_to_ema3_h_1m_atr",
                                                  np.nan)
                                       if direction == 1 else
                                       -snap_b1.get(
                                           "dist_close_to_ema3_l_1m_atr",
                                           np.nan))
    out["dist_from_ema9_atr"] = (snap_b1.get("dist_close_to_ema9_h_1m_atr",
                                                  np.nan)
                                       if direction == 1 else
                                       -snap_b1.get(
                                           "dist_close_to_ema9_l_1m_atr",
                                           np.nan))
    return out


def process_year(year):
    print(f"\n=== {year} ===", flush=True)
    base = Path(f"collectors/collector_v2/results/v_a_v0_{year}")
    trades = pd.read_parquet(base / "trades.parquet")
    snaps = pd.read_parquet(base / "snapshots.parquet")
    wex = pd.read_parquet(OUT / f"v_a_v0_{year}_with_excursion.parquet")

    # Apply filter
    f = wex[(wex["total_excursion_slow"] >= SLOW_LO_CUT)
              & (wex["total_excursion_slow"] < SLOW_HI_CUT)].copy()
    print(f"  filtered trades: {len(f):,}", flush=True)

    # Index snapshots by event_id
    bar1 = snaps[snaps["kind"] == "bar1_check"].set_index("event_id")

    # Load bars
    bars = load_year_bars(year)
    ts_idx = bars.index.astype("int64").to_numpy()
    opens = bars["open"].values.astype(np.float64)
    highs = bars["high"].values.astype(np.float64)
    lows = bars["low"].values.astype(np.float64)
    closes = bars["close"].values.astype(np.float64)

    rows = []
    t0 = time.time()
    for i, tr in f.iterrows():
        entry_ts = int(tr["entry_ts"])
        exit_ts = int(tr["exit_ts"])
        direction = int(tr["direction"])
        atr = float(tr["atr_at_signal"])
        fill_px = float(tr["fill_price"])
        net_pnl = float(tr["net_pnl"])
        final_mfe_atr = float(tr["running_mfe"]) / max(atr, 0.01)

        # Compute checkpoint features
        cp_states = []
        prev_state = None
        for cp_s in CHECKPOINT_S:
            t_ns = entry_ts + cp_s * 1_000_000_000
            if t_ns >= exit_ts:
                cp_states.append(None)
                continue
            s = features_at_tick(t_ns, direction, atr, ts_idx,
                                     opens, highs, lows, closes,
                                     entry_ts, fill_px, prev_state)
            cp_states.append(s)
            prev_state = s

        # V4 fire decision (uses +3m and +4m states)
        v4_fired = compute_v4_decision(cp_states[2], cp_states[3])
        cls = classify_trade(net_pnl, final_mfe_atr, v4_fired)

        # Entry-trigger features
        deid = int(tr["decision_event_id"])
        if deid in bar1.index:
            snap_b1 = bar1.loc[deid].to_dict()
            ent_feats = entry_trigger_features(
                snap_b1, atr, fill_px, direction)
        else:
            ent_feats = {}

        # Combine into rows (one row per checkpoint per trade)
        base_row = {
            "year": year, "trade_idx": i, "direction": direction,
            "atr": atr, "fill_price": fill_px,
            "net_pnl": net_pnl, "final_mfe_atr": final_mfe_atr,
            "v4_fired": v4_fired, "class": cls,
            "excursion_slow_pre_entry": float(tr["total_excursion_slow"]),
            "hold_s": float(tr["hold_s"]),
            **{f"ent_{k}": v for k, v in ent_feats.items()},
        }
        for cp_s, cp_label, s in zip(CHECKPOINT_S, CHECKPOINT_LABELS,
                                          cp_states):
            r = dict(base_row)
            r["cp"] = cp_label
            r["cp_elapsed_s"] = cp_s
            if s is not None:
                r.update({f"cp_{k}": v for k, v in s.items()})
            rows.append(r)

        if i and i % 250 == 0:
            print(f"   {i}  elapsed {time.time()-t0:.0f}s", flush=True)

    print(f"   year {year} done in {time.time()-t0:.0f}s", flush=True)
    return pd.DataFrame(rows)


def report(full):
    classes = ["1_good_runner", "2_good_normal_win", "3_v4_false_exit",
                "4_v4_true_save", "5_v4_missed_loser"]
    print(f"\n{'='*78}")
    print(f"CLASS DISTRIBUTION (per trade, all years)")
    print(f"{'='*78}")
    one_per_trade = full.drop_duplicates(["year", "trade_idx"])
    total = len(one_per_trade)
    print(f"  Total filtered trades: {total:,}\n")
    for c in classes:
        sub = one_per_trade[one_per_trade["class"] == c]
        n = len(sub)
        if not n: continue
        net = sub["net_pnl"].sum()
        pertr = sub["net_pnl"].mean()
        med_mfe = sub["final_mfe_atr"].median()
        print(f"  {c:<22} n={n:>5,} ({100*n/total:>5.1f}%)  "
              f"net ${net:>+9,.0f}  $/tr {pertr:>+7.1f}  "
              f"med_mfe_atr {med_mfe:.2f}")

    # Per-year class counts
    print(f"\n--- Class counts by year ---")
    print(f"  {'class':<22} {'2024':>7} {'2025':>7} {'2026':>7}")
    for c in classes:
        line = f"  {c:<22}"
        for yr in (2024, 2025, 2026):
            sub = one_per_trade[(one_per_trade["class"] == c)
                                    & (one_per_trade["year"] == yr)]
            line += f" {len(sub):>7,}"
        print(line)

    # ---- Feature distributions per class × checkpoint ----
    cp_features = [
        "cp_unrealized_pnl", "cp_current_mfe_atr", "cp_current_mae_atr",
        "cp_mfe_to_mae", "cp_close_loc_in_range",
        "cp_dd_from_peak_mfe_atr", "cp_rec_from_max_mae_atr",
        "cp_ratio_xfast", "cp_ratio_fast",
        "cp_net_move_xfast", "cp_net_move_fast",
        "cp_efficiency_xfast", "cp_efficiency_fast",
    ]
    cp_features = [c for c in cp_features if c in full.columns]

    print(f"\n{'='*78}")
    print(f"CHECKPOINT-FEATURE MEDIANS BY CLASS")
    print(f"{'='*78}")
    for cp in CHECKPOINT_LABELS:
        sub = full[full["cp"] == cp]
        if not len(sub): continue
        print(f"\n--- Checkpoint {cp} ---")
        print(f"  {'feature':<30}" + "".join(
            f"{c[:14]:>15}" for c in classes))
        for feat in cp_features:
            line = f"  {feat:<30}"
            for c in classes:
                g = sub[sub["class"] == c]
                if not len(g): line += f"{'-':>15}"; continue
                med = g[feat].median()
                if pd.isna(med):
                    line += f"{'nan':>15}"
                else:
                    line += f"{med:>+15.2f}"
            print(line)

    # ---- Entry-trigger features per class ----
    ent_features = [c for c in full.columns if c.startswith("ent_")]
    if ent_features:
        print(f"\n{'='*78}")
        print(f"ENTRY-TRIGGER FEATURE MEDIANS BY CLASS (one per trade)")
        print(f"{'='*78}")
        sub = full.drop_duplicates(["year", "trade_idx"])
        print(f"  {'feature':<35}" + "".join(
            f"{c[:14]:>15}" for c in classes))
        for feat in ent_features + ["excursion_slow_pre_entry"]:
            if feat not in sub.columns: continue
            line = f"  {feat:<35}"
            for c in classes:
                g = sub[sub["class"] == c]
                if not len(g): line += f"{'-':>15}"; continue
                med = g[feat].median()
                line += (f"{med:>+15.3f}" if not pd.isna(med)
                          else f"{'nan':>15}")
            print(line)

    # ---- Separation analysis ----
    print(f"\n{'='*78}")
    print("KEY SEPARATIONS (false_exit vs true_save) at +3m and +4m")
    print(f"{'='*78}")
    print("Question: at V4 decision time, what distinguishes V4 false-exits")
    print("from V4 true-saves? If features differ, we can refine V4 to")
    print("avoid cutting bounce-back winners.\n")
    for cp in ("+3m", "+4m"):
        sub = full[full["cp"] == cp]
        if not len(sub): continue
        false_exit = sub[sub["class"] == "3_v4_false_exit"]
        true_save = sub[sub["class"] == "4_v4_true_save"]
        if not len(false_exit) or not len(true_save): continue
        rows = []
        for feat in cp_features:
            fe_med = false_exit[feat].median()
            ts_med = true_save[feat].median()
            if pd.isna(fe_med) or pd.isna(ts_med): continue
            sep = fe_med - ts_med
            rows.append({"feat": feat, "false_exit": fe_med,
                          "true_save": ts_med, "sep": sep,
                          "abs_sep": abs(sep)})
        sdf = pd.DataFrame(rows).sort_values("abs_sep", ascending=False)
        print(f"\n  --- {cp} | top 10 by |separation| ---")
        print(f"  {'feature':<28} {'false_exit':>12} {'true_save':>12} "
              f"{'sep':>10}")
        for _, r in sdf.head(10).iterrows():
            print(f"  {r['feat']:<28} {r['false_exit']:>+12.2f} "
                  f"{r['true_save']:>+12.2f} {r['sep']:>+10.2f}")

    # ---- Runner vs missed-loser separation (could earlier check flag losers?) ----
    print(f"\n{'='*78}")
    print("KEY SEPARATIONS (runner vs missed_loser) at each checkpoint")
    print(f"{'='*78}")
    print("Question: could earlier features distinguish 3+ATR runners from")
    print("the eventual losers V4 missed?\n")
    for cp in CHECKPOINT_LABELS:
        sub = full[full["cp"] == cp]
        if not len(sub): continue
        runners = sub[sub["class"] == "1_good_runner"]
        missed = sub[sub["class"] == "5_v4_missed_loser"]
        if not len(runners) or not len(missed): continue
        rows = []
        for feat in cp_features:
            r_med = runners[feat].median()
            m_med = missed[feat].median()
            if pd.isna(r_med) or pd.isna(m_med): continue
            sep = r_med - m_med
            rows.append({"feat": feat, "runner": r_med,
                          "missed_loser": m_med, "sep": sep,
                          "abs_sep": abs(sep)})
        sdf = pd.DataFrame(rows).sort_values("abs_sep", ascending=False)
        print(f"\n  --- {cp} | top 10 by |separation| ---")
        print(f"  {'feature':<28} {'runner':>12} {'missed':>12} {'sep':>10}")
        for _, r in sdf.head(10).iterrows():
            print(f"  {r['feat']:<28} {r['runner']:>+12.2f} "
                  f"{r['missed_loser']:>+12.2f} {r['sep']:>+10.2f}")

    # ---- Entry-trigger separation (could entry features predict class?) ----
    print(f"\n{'='*78}")
    print("ENTRY-TRIGGER SEPARATION: runner vs missed_loser, "
          "false_exit vs true_save")
    print(f"{'='*78}")
    sub = full.drop_duplicates(["year", "trade_idx"])
    for c1, c2 in [("1_good_runner", "5_v4_missed_loser"),
                     ("3_v4_false_exit", "4_v4_true_save"),
                     ("2_good_normal_win", "3_v4_false_exit")]:
        g1 = sub[sub["class"] == c1]
        g2 = sub[sub["class"] == c2]
        if not len(g1) or not len(g2): continue
        rows = []
        for feat in ent_features + ["excursion_slow_pre_entry"]:
            if feat not in sub.columns: continue
            m1 = g1[feat].median()
            m2 = g2[feat].median()
            if pd.isna(m1) or pd.isna(m2): continue
            sep = m1 - m2
            rows.append({"feat": feat, c1: m1, c2: m2, "sep": sep,
                          "abs_sep": abs(sep)})
        sdf = pd.DataFrame(rows).sort_values("abs_sep", ascending=False)
        print(f"\n  --- {c1} vs {c2} ---")
        print(f"  {'feature':<35} {c1[:12]:>14} {c2[:12]:>14} {'sep':>10}")
        for _, r in sdf.head(10).iterrows():
            print(f"  {r['feat']:<35} {r[c1]:>+14.3f} {r[c2]:>+14.3f} "
                  f"{r['sep']:>+10.3f}")


def main():
    t0 = time.time()
    print("=" * 78)
    print("V_A TRADE-QUALITY ATTRIBUTION STUDY")
    print("=" * 78)

    parts = []
    for yr in (2024, 2025, 2026):
        parts.append(process_year(yr))
    full = pd.concat(parts, ignore_index=True)
    full.to_parquet(OUT / "trade_quality_attribution.parquet")

    report(full)
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
