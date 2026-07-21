"""Tick-replay validation of V_A + filter + V4 overlay on 2026 OOS.

Goal: confirm V4 overlay's +$1,980 OOS lift survives realistic tick fills.

Approach:
  - Use existing v_a_v0_2026 trades (HH/LL-confirmed entries on
    NQ.v.0 catalog), filtered to total_excursion_slow=mid.
  - Load NQ.v.0 MBP-1 trade events (action='T') for Jan-Apr 2026.
  - For each filtered trade, walk forward in ticks from entry_ts.
  - At +3m elapsed: evaluate V4 candidate (unr<-50 AND mfe<0.25)
    using TICK-derived running mfe/mae/unrealized.
  - At +4m elapsed: evaluate V4 confirm (unr<0 AND mfe<0.35 AND
    xfast_net_move<0). Use 2.5-min trailing window of ticks for
    xfast_net_move.
  - If V4 fires (per tick state): exit at the FIRST TICK AT-OR-AFTER
    +4m. fill_price = that tick's price.
  - If V4 doesn't fire: trade exits at original regime exit (unchanged).

Compare:
  - tick_baseline:  per-trade baseline_pnl (regime exit only) — should
    closely match 1s-bar baseline since regime exit timing is set by
    1m bar boundaries
  - tick_v4_stack:  V4 overlay applied with tick-derived state
  - 1s_v4_stack:    existing v4_pnl from 1s-bar reading (control)

Key metrics:
  - 2026 net delta tick_v4 - 1s_v4
  - Per-trade: how often does V4 fire/not-fire under ticks vs 1s
  - Average exit price difference

Tick fills assume:
  - Market order at trigger detection. fill at NEXT trade tick.
  - This is conservative — actual fill could be ahead or behind by
    a few ticks depending on liquidity. Memory rule: tick mode is
    the gold standard for fill realism.
"""
from __future__ import annotations
import os, sys, time, gc
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
OUT = Path("studies/v_a_excursion_regime/results_v0")


def load_trades_in_window(month_idx, start_ts_ns=None, end_ts_ns=None):
    """Load MBP-1 trade events (action='T') for a single month file.
    Returns numpy arrays (ts_ns, price)."""
    path = f"data/raw/NQ_v0_mbp1_2026_{month_idx:02d}.parquet"
    if not Path(path).exists():
        return np.array([], dtype=np.int64), np.array([], dtype=np.float64)
    print(f"  loading {path}...", flush=True)
    df = pd.read_parquet(path, columns=["action", "ts_event", "price"])
    df = df[df["action"] == "T"]
    if start_ts_ns is not None:
        df = df[df["ts_event"].astype("int64") >= start_ts_ns]
    if end_ts_ns is not None:
        df = df[df["ts_event"].astype("int64") <= end_ts_ns]
    df = df.sort_values("ts_event")
    ts = df["ts_event"].astype("int64").to_numpy()
    px = df["price"].astype(np.float64).to_numpy()
    print(f"    {len(ts):,} trade events", flush=True)
    return ts, px


def evaluate_v4_with_ticks(direction, atr, fill_px, entry_ts, exit_ts,
                              ts_arr, px_arr):
    """Evaluate V4 at +3m and +4m using tick state. Returns
    (fired, exit_price_if_fired). Causal: only ticks with ts < cp_ts."""
    ts_3m = entry_ts + 180 * 1_000_000_000
    ts_4m = entry_ts + 240 * 1_000_000_000
    if ts_3m >= exit_ts or ts_4m >= exit_ts:
        return False, np.nan, "checkpoint past exit"

    # Find tick range from entry_ts to ts_3m (strictly before)
    i_entry = np.searchsorted(ts_arr, entry_ts, side="left")
    i_3m = np.searchsorted(ts_arr, ts_3m, side="left")
    if i_3m <= i_entry:
        return False, np.nan, "no ticks in [entry, +3m)"
    seg_3m = px_arr[i_entry:i_3m]
    if direction == 1:
        cur_mfe_3m = float(seg_3m.max() - fill_px)
        cur_mae_3m = float(fill_px - seg_3m.min())
        unr_pts_3m = float(seg_3m[-1] - fill_px)
    else:
        cur_mfe_3m = float(fill_px - seg_3m.min())
        cur_mae_3m = float(seg_3m.max() - fill_px)
        unr_pts_3m = float(fill_px - seg_3m[-1])
    mfe_atr_3m = cur_mfe_3m / max(atr, 0.01)
    unr_3m = unr_pts_3m * NQ_MULT
    if not (unr_3m < -50 and mfe_atr_3m < 0.25):
        return False, np.nan, "candidate failed"

    # Now check confirm at +4m: unr<0 AND mfe<0.35 AND xfast_net<0
    i_4m = np.searchsorted(ts_arr, ts_4m, side="left")
    if i_4m <= i_entry:
        return False, np.nan, "no ticks in [entry, +4m)"
    seg_4m = px_arr[i_entry:i_4m]
    if direction == 1:
        cur_mfe_4m = float(seg_4m.max() - fill_px)
        cur_mae_4m = float(fill_px - seg_4m.min())
        unr_pts_4m = float(seg_4m[-1] - fill_px)
    else:
        cur_mfe_4m = float(fill_px - seg_4m.min())
        cur_mae_4m = float(seg_4m.max() - fill_px)
        unr_pts_4m = float(fill_px - seg_4m[-1])
    mfe_atr_4m = cur_mfe_4m / max(atr, 0.01)
    unr_4m = unr_pts_4m * NQ_MULT

    # xfast_net_move: 2.5-min trailing window ending at +4m, direction-
    # aware. anchor = price of first tick at-or-after (ts_4m - 150s).
    win_start = ts_4m - 150 * 1_000_000_000
    i_xfast_lo = np.searchsorted(ts_arr, win_start, side="left")
    if i_xfast_lo >= i_4m:
        # Not enough ticks in xfast window — can't evaluate confirm
        return False, np.nan, "no xfast ticks"
    anchor_px = float(px_arr[i_xfast_lo])
    last_px = float(px_arr[i_4m - 1])
    xfast_net = (last_px - anchor_px) if direction == 1 else (anchor_px - last_px)

    if not (unr_4m < 0 and mfe_atr_4m < 0.35 and xfast_net < 0):
        return False, np.nan, "confirm failed"

    # Fire — exit at FIRST TICK AT-OR-AFTER +4m
    if i_4m >= len(ts_arr):
        return True, np.nan, "no fill tick"
    exit_px = float(px_arr[i_4m])
    return True, exit_px, "fired"


def add_drawdown(df, col):
    df = df.sort_values("entry_ts").copy()
    df["cum"] = df[col].cumsum()
    df["cum_max"] = df["cum"].cummax()
    df["dd"] = df["cum"] - df["cum_max"]
    return df


def main():
    t0 = time.time()
    print("=" * 78)
    print("TICK-VALIDATE V4 OVERLAY ON V_A 2026 (NQ.v.0 MBP-1)")
    print("=" * 78)

    # Load filtered V_A 2026 trades + 1s-bar V4 status
    wex = pd.read_parquet(OUT / "v_a_v0_2026_with_excursion.parquet")
    filt = wex[(wex["total_excursion_slow"] >= SLOW_LO_CUT)
                 & (wex["total_excursion_slow"] < SLOW_HI_CUT)].copy()
    filt = filt.reset_index(drop=True)
    print(f"\n  filtered trades 2026: {len(filt):,}")

    # Load existing 1s-bar V4 status (from attribution parquet)
    attr = pd.read_parquet(OUT / "trade_quality_attribution.parquet")
    a26 = attr[(attr["year"] == 2026) & (attr["cp"] == "+1m")][
        ["trade_idx", "v4_fired", "class"]].copy()

    # Map: filt has its own row index; attribution's trade_idx came from
    # the un-reset wex index. Re-create the un-reset index for join.
    filt_orig = wex[(wex["total_excursion_slow"] >= SLOW_LO_CUT)
                       & (wex["total_excursion_slow"] < SLOW_HI_CUT)].copy()
    filt_orig["trade_idx"] = filt_orig.index
    filt_orig = filt_orig.merge(a26, on="trade_idx", how="left")
    filt_orig = filt_orig.reset_index(drop=True)
    n_with_v4 = filt_orig["v4_fired"].notna().sum()
    print(f"  trades with V4 status: {n_with_v4:,}")
    print(f"  V4 1s-bar fires: {filt_orig['v4_fired'].sum():,}")

    # Load all MBP-1 trade ticks for 2026 Jan-Apr at once (combined)
    print(f"\n  loading MBP-1 trade ticks for 2026 Jan-Apr...")
    all_ts = []; all_px = []
    for m in (1, 2, 3, 4):
        ts, px = load_trades_in_window(m)
        all_ts.append(ts); all_px.append(px)
    ts_arr = np.concatenate(all_ts); px_arr = np.concatenate(all_px)
    # Sort just to be safe
    order = np.argsort(ts_arr, kind="stable")
    ts_arr = ts_arr[order]; px_arr = px_arr[order]
    del all_ts, all_px; gc.collect()
    print(f"  total ticks: {ts_arr.shape[0]:,}  "
          f"range {pd.Timestamp(ts_arr[0], unit='ns', tz='UTC')} -> "
          f"{pd.Timestamp(ts_arr[-1], unit='ns', tz='UTC')}")

    # Walk each filtered trade
    print(f"\n  evaluating V4 with ticks...", flush=True)
    rows = []
    n_skipped_no_ticks = 0
    for i, tr in filt_orig.iterrows():
        entry_ts = int(tr["entry_ts"])
        exit_ts = int(tr["exit_ts"])
        direction = int(tr["direction"])
        atr = float(tr["atr_at_signal"])
        fill_px = float(tr["fill_price"])
        baseline_pnl = float(tr["net_pnl"])
        v4_fired_1s = bool(tr["v4_fired"]) if not pd.isna(
            tr.get("v4_fired", np.nan)) else False
        cls = tr.get("class", None)

        # Skip trades whose entry is before our tick coverage
        if entry_ts < ts_arr[0]:
            n_skipped_no_ticks += 1
            continue

        fired_tick, exit_px_tick, reason = evaluate_v4_with_ticks(
            direction, atr, fill_px, entry_ts, exit_ts, ts_arr, px_arr)
        if fired_tick and not pd.isna(exit_px_tick):
            if direction == 1:
                pts = exit_px_tick - fill_px
            else:
                pts = fill_px - exit_px_tick
            v4_tick_pnl = pts * NQ_MULT - 2 * COMMISSION
        else:
            v4_tick_pnl = baseline_pnl

        rows.append({
            "trade_idx": int(tr["trade_idx"]),
            "entry_ts": entry_ts, "exit_ts": exit_ts,
            "direction": direction, "fill_price": fill_px,
            "atr": atr, "baseline_pnl": baseline_pnl,
            "class": cls,
            "v4_1s_fired": v4_fired_1s,
            "v4_tick_fired": fired_tick,
            "v4_tick_reason": reason,
            "v4_tick_exit_px": exit_px_tick,
            "v4_tick_pnl": v4_tick_pnl,
        })

    print(f"  walked {len(rows):,} trades  ({n_skipped_no_ticks} "
          f"skipped — entry before tick coverage)", flush=True)

    res = pd.DataFrame(rows)
    res.to_parquet(OUT / "tick_validate_v4_2026.parquet")

    # ============ Compare 1s-V4 vs tick-V4 ============
    print(f"\n{'='*78}")
    print(f"FIRE AGREEMENT (1s vs tick)")
    print(f"{'='*78}")
    fired_both = ((res["v4_1s_fired"]) & (res["v4_tick_fired"])).sum()
    fired_1s_only = ((res["v4_1s_fired"]) & (~res["v4_tick_fired"])).sum()
    fired_tick_only = ((~res["v4_1s_fired"]) & (res["v4_tick_fired"])).sum()
    not_fired_either = ((~res["v4_1s_fired"])
                          & (~res["v4_tick_fired"])).sum()
    print(f"  fired in BOTH:        {fired_both:,}")
    print(f"  fired 1s only:        {fired_1s_only:,}")
    print(f"  fired tick only:      {fired_tick_only:,}")
    print(f"  not fired either:     {not_fired_either:,}")
    print(f"  total fires 1s:       {res['v4_1s_fired'].sum():,}")
    print(f"  total fires tick:     {res['v4_tick_fired'].sum():,}")

    # ============ Per-trade exit-price comparison (when both fire) ============
    print(f"\n{'='*78}")
    print(f"EXIT-PRICE DIFFERENCE (when V4 fired in BOTH 1s and tick)")
    print(f"{'='*78}")
    both = res[(res["v4_1s_fired"]) & (res["v4_tick_fired"])
                 & res["v4_tick_exit_px"].notna()].copy()
    if len(both):
        # Need 1s-V4 exit price — recompute from 1s bars at +4m
        # (we don't have it directly; reconstruct as v4_pnl back to fill)
        # Instead: compute v4_tick_pnl - v4_1s_pnl
        # Need v4_1s_pnl: from attribution data
        # Quick reconstruction: compute the 1s-bar V4 PnL using
        # the +4m fill price from 1s bars.
        bars = pd.read_parquet("data/raw/NQ_v0_1s_2026_ytd.parquet",
                                  columns=["open"])
        if bars.index.tz is None:
            bars.index = bars.index.tz_localize("UTC")
        bts = bars.index.astype("int64").to_numpy()
        bopens = bars["open"].values.astype(np.float64)
        v4_1s_pnls = []
        for _, r in both.iterrows():
            cp4 = int(r["entry_ts"]) + 240 * 1_000_000_000
            i = np.searchsorted(bts, cp4, side="left")
            if i >= len(bopens):
                v4_1s_pnls.append(np.nan); continue
            fp_1s = float(bopens[i])
            d = int(r["direction"])
            if d == 1:
                pts = fp_1s - r["fill_price"]
            else:
                pts = r["fill_price"] - fp_1s
            v4_1s_pnls.append(pts * NQ_MULT - 2 * COMMISSION)
        both["v4_1s_pnl"] = v4_1s_pnls
        both["pnl_diff_tick_minus_1s"] = (both["v4_tick_pnl"]
                                                - both["v4_1s_pnl"])
        print(f"  n with both fires + valid prices: {len(both):,}")
        print(f"  median 1s_v4_pnl: ${both['v4_1s_pnl'].median():+,.0f}")
        print(f"  median tick_v4_pnl: ${both['v4_tick_pnl'].median():+,.0f}")
        print(f"  median tick−1s diff: "
              f"${both['pnl_diff_tick_minus_1s'].median():+,.0f}")
        print(f"  mean tick−1s diff: "
              f"${both['pnl_diff_tick_minus_1s'].mean():+,.0f}")
        print(f"  total tick−1s diff: "
              f"${both['pnl_diff_tick_minus_1s'].sum():+,.0f}")
    else:
        print(f"  No trades fired in BOTH — skipping comparison")

    # ============ Stack PnL: V_A baseline + V4_tick vs V4_1s ============
    print(f"\n{'='*78}")
    print(f"2026 STACK PnL — tick V4 vs 1s V4 (filtered trades only)")
    print(f"{'='*78}")
    n = len(res)
    base_total = res["baseline_pnl"].sum()
    v4_tick_total = res["v4_tick_pnl"].sum()
    print(f"  n trades evaluated:        {n:,}")
    print(f"  baseline PnL (no overlay): ${base_total:+,.0f} "
          f"(${base_total/n:+.2f}/tr)")
    print(f"  V4 TICK stack PnL:         ${v4_tick_total:+,.0f} "
          f"(${v4_tick_total/n:+.2f}/tr)")
    print(f"  V4 TICK Δ vs baseline:     "
          f"${v4_tick_total - base_total:+,.0f}")

    # Compare to 1s V4 stack — recompute baseline from same evaluated set
    # using the v4_pnl logic from prior scripts
    v4_1s_pnls_full = []
    bars = pd.read_parquet("data/raw/NQ_v0_1s_2026_ytd.parquet",
                              columns=["open"])
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    bts = bars.index.astype("int64").to_numpy()
    bopens = bars["open"].values.astype(np.float64)
    for _, r in res.iterrows():
        if not r["v4_1s_fired"]:
            v4_1s_pnls_full.append(r["baseline_pnl"]); continue
        cp4 = int(r["entry_ts"]) + 240 * 1_000_000_000
        i = np.searchsorted(bts, cp4, side="left")
        if i >= len(bopens):
            v4_1s_pnls_full.append(r["baseline_pnl"]); continue
        fp_1s = float(bopens[i])
        d = int(r["direction"])
        if d == 1:
            pts = fp_1s - r["fill_price"]
        else:
            pts = r["fill_price"] - fp_1s
        v4_1s_pnls_full.append(pts * NQ_MULT - 2 * COMMISSION)
    res["v4_1s_pnl"] = v4_1s_pnls_full
    v4_1s_total = res["v4_1s_pnl"].sum()
    print(f"  V4 1s stack PnL:           ${v4_1s_total:+,.0f} "
          f"(${v4_1s_total/n:+.2f}/tr)")
    print(f"  V4 1s Δ vs baseline:       "
          f"${v4_1s_total - base_total:+,.0f}")
    print(f"\n  TICK V4 vs 1s V4 delta:    "
          f"${v4_tick_total - v4_1s_total:+,.0f}  "
          f"(${ (v4_tick_total - v4_1s_total)/n:+.2f}/tr)")

    # Drawdowns
    res_b = add_drawdown(res, "baseline_pnl")
    res_1s = add_drawdown(res, "v4_1s_pnl")
    res_tk = add_drawdown(res, "v4_tick_pnl")
    print(f"\n  max DD baseline: ${res_b['dd'].min():+,.0f}")
    print(f"  max DD 1s-V4:    ${res_1s['dd'].min():+,.0f}")
    print(f"  max DD tick-V4:  ${res_tk['dd'].min():+,.0f}")

    # Verdict
    print(f"\n{'='*78}")
    print(f"VERDICT")
    print(f"{'='*78}")
    if v4_tick_total > base_total:
        print(f"  ✓ V4 tick-validated: improves baseline by "
              f"${v4_tick_total - base_total:+,.0f}")
    else:
        print(f"  ✗ V4 does NOT improve baseline under tick fills.")
    one_s_lift = v4_1s_total - base_total
    tick_lift = v4_tick_total - base_total
    if one_s_lift > 0:
        retention = 100 * tick_lift / one_s_lift if one_s_lift > 0 else 0
        print(f"  1s-bar V4 lift: ${one_s_lift:+,.0f}")
        print(f"  Tick V4 lift:   ${tick_lift:+,.0f}")
        print(f"  Retention:      {retention:.0f}%")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
