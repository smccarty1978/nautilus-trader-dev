"""Tick-validate the grid winner: fallback bracket on no-flip cohort.

Grid winner: PT=1.0 ATR / SL=1.25 ATR / TO=600s + regime-flip transition.

Methodology (NT-correct tick semantics):
- All fills use NEXT-quote-after-event-ts (never last-quote-before)
- LIMIT (PT): fills exactly at PT level when bid (long) / ask (short) reaches level
- STOP-MARKET (SL): triggers when bid (long) / ask (short) crosses SL, fills at NEXT quote
- MARKET (TO/REGIME exit): fills at next quote after event ts
- ENTRY: market order, fills at next ask (long) / bid (short) after entry_ts

For VA-confirm trades, we reuse the existing NT MBP-1 result (already
tick-validated). Only the no-flip cohort (1007 trades) is re-simulated.

State machine (no-flip trades):
  [entry, entry+60s]   : HOLD (no exits)
  [entry+60s, timeout] : BRACKET (PT limit, SL stop, regime transition)
  on regime-flip-in-direction during bracket:
      → transition to CONFIRMED-mode (hold to next opposite regime flip)
"""
from __future__ import annotations
import os, sys, time, gc
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd


SCHEDULE = ("backtests/pre_flip_T1/results/"
              "schedule_T1_n20_2026_top10.parquet")
EXISTING_TICK_TRADES = ("backtests/pre_flip_T1/results/"
                            "nt_mbp1_2026_top10_N20/"
                            "trades_all_months.parquet")
SNAPSHOTS = ("collectors/collector_v2/results/v_a_v0_2026/"
               "snapshots_with_vol_vwap.parquet")
MBP1_DIR = "data/raw"
OUT_DIR = Path("backtests/pre_flip_T1/results/"
                  "nt_mbp1_2026_top10_N20_fallback")
PT_ATR = 1.0
SL_ATR = 1.25
TIMEOUT_S = 600
BRACKET_START_S = 60
NQ_MULT = 20.0
COMMISSION_RT = 10.0
PRICE_TICK = 0.25


def round_tick(px, side_round="nearest"):
    """Round price to NQ tick grid."""
    n = px / PRICE_TICK
    if side_round == "down":
        return np.floor(n) * PRICE_TICK
    elif side_round == "up":
        return np.ceil(n) * PRICE_TICK
    return np.round(n) * PRICE_TICK


def replay_no_flip_trade(
    quote_ts, quote_bid, quote_ask,
    entry_ts_ns, direction, atr_at_signal,
    flips_dir_ts, flips_opp_ts,
    pt_atr, sl_atr, timeout_s, bracket_start_s,
):
    """Replay a single no-flip trade through the MBP-1 quote stream.

    Returns dict with entry/exit fills, levels, exit_reason, exit_ts.
    """
    d = direction
    # ENTRY: next quote after entry_ts_ns
    entry_idx = int(np.searchsorted(quote_ts, entry_ts_ns, side="right"))
    if entry_idx >= len(quote_ts):
        return None
    if d == 1:
        entry_fill = float(quote_ask[entry_idx])
    else:
        entry_fill = float(quote_bid[entry_idx])

    # Level prices (rounded to tick grid, pessimistic direction)
    if d == 1:
        # long: PT is a sell-limit ABOVE entry; round DOWN (harder to fill)
        pt_level = round_tick(entry_fill + pt_atr * atr_at_signal, "down")
        # long: SL is a sell-stop BELOW entry; round UP (triggers earlier)
        sl_level = round_tick(entry_fill - sl_atr * atr_at_signal, "up")
    else:
        # short: PT is a buy-limit BELOW entry; round UP
        pt_level = round_tick(entry_fill - pt_atr * atr_at_signal, "up")
        # short: SL is a buy-stop ABOVE entry; round DOWN (triggers earlier)
        sl_level = round_tick(entry_fill + sl_atr * atr_at_signal, "down")

    bracket_start_ts = entry_ts_ns + bracket_start_s * 1_000_000_000
    timeout_ts = entry_ts_ns + timeout_s * 1_000_000_000
    bracket_start_idx = int(np.searchsorted(
        quote_ts, bracket_start_ts, side="right"))
    timeout_idx = int(np.searchsorted(
        quote_ts, timeout_ts, side="right"))
    timeout_idx = min(timeout_idx, len(quote_ts) - 1)
    if bracket_start_idx >= timeout_idx:
        return None

    # Quotes within bracket window
    # For PT limit on long: fills when bid >= PT (we sell at PT level)
    # For SL stop on long: triggers when bid <= SL (we sell next bid)
    # For PT limit on short: fills when ask <= PT (we buy at PT level)
    # For SL stop on short: triggers when ask >= SL (we buy next ask)
    if d == 1:
        exit_quotes = quote_bid    # we sell on bid
        pt_touch = quote_bid[bracket_start_idx:timeout_idx + 1] >= pt_level
        sl_touch = quote_bid[bracket_start_idx:timeout_idx + 1] <= sl_level
    else:
        exit_quotes = quote_ask    # we buy on ask
        pt_touch = quote_ask[bracket_start_idx:timeout_idx + 1] <= pt_level
        sl_touch = quote_ask[bracket_start_idx:timeout_idx + 1] >= sl_level

    pt_first = int(np.argmax(pt_touch)) if pt_touch.any() else -1
    sl_first = int(np.argmax(sl_touch)) if sl_touch.any() else -1

    # Regime flip in our direction within bracket window
    rg_first_ts = -1
    if len(flips_dir_ts) > 0:
        rel = flips_dir_ts[(flips_dir_ts >= bracket_start_ts)
                              & (flips_dir_ts <= timeout_ts)]
        if len(rel) > 0:
            rg_first_ts = int(rel[0])

    # Pick first event
    events = []
    if pt_first >= 0:
        # LIMIT fills at PT level (no slippage)
        pt_ts = int(quote_ts[bracket_start_idx + pt_first])
        events.append((pt_ts, "PT", pt_level))
    if sl_first >= 0:
        # STOP triggers at touch_idx, fills at NEXT quote
        sl_idx = bracket_start_idx + sl_first
        sl_ts = int(quote_ts[sl_idx])
        next_idx = sl_idx + 1
        if next_idx >= len(quote_ts):
            next_idx = sl_idx
        sl_fill = float(exit_quotes[next_idx])
        events.append((sl_ts, "SL", sl_fill))
    if rg_first_ts > 0:
        events.append((rg_first_ts, "REGIME", None))

    if not events:
        # TIMEOUT: market exit at next quote after timeout_ts
        to_idx = int(np.searchsorted(quote_ts, timeout_ts, side="right"))
        if to_idx >= len(quote_ts):
            to_idx = len(quote_ts) - 1
        to_fill = float(exit_quotes[to_idx])
        return {
            "entry_ts_ns": entry_ts_ns, "entry_fill_price": entry_fill,
            "exit_ts_ns": int(quote_ts[to_idx]),
            "exit_fill_price": to_fill,
            "direction": d, "atr_at_signal": atr_at_signal,
            "pt_level": pt_level, "sl_level": sl_level,
            "exit_reason": "TO",
        }

    events.sort(key=lambda e: e[0])
    first_ts, reason, fill_price = events[0]

    # Same-tick PT/SL tie: pessimistic
    if reason == "PT":
        same_ts_events = [e for e in events if e[0] == first_ts
                              and e[1] == "SL"]
        if same_ts_events:
            first_ts, reason, fill_price = same_ts_events[0]

    if reason in ("PT", "SL"):
        return {
            "entry_ts_ns": entry_ts_ns, "entry_fill_price": entry_fill,
            "exit_ts_ns": first_ts, "exit_fill_price": fill_price,
            "direction": d, "atr_at_signal": atr_at_signal,
            "pt_level": pt_level, "sl_level": sl_level,
            "exit_reason": reason,
        }

    # REGIME transition: switch to confirmed-mode
    # Find next opposite regime flip after first_ts
    opp_after = flips_opp_ts[flips_opp_ts > first_ts]
    if len(opp_after) > 0:
        opp_ts = int(opp_after[0])
        opp_idx = int(np.searchsorted(quote_ts, opp_ts, side="right"))
        if opp_idx >= len(quote_ts):
            opp_idx = len(quote_ts) - 1
        opp_fill = float(exit_quotes[opp_idx])
        return {
            "entry_ts_ns": entry_ts_ns, "entry_fill_price": entry_fill,
            "exit_ts_ns": int(quote_ts[opp_idx]),
            "exit_fill_price": opp_fill,
            "direction": d, "atr_at_signal": atr_at_signal,
            "pt_level": pt_level, "sl_level": sl_level,
            "exit_reason": "REGIME",
        }
    # No opposite flip in available data — hold to last quote
    return {
        "entry_ts_ns": entry_ts_ns, "entry_fill_price": entry_fill,
        "exit_ts_ns": int(quote_ts[-1]),
        "exit_fill_price": float(exit_quotes[-1]),
        "direction": d, "atr_at_signal": atr_at_signal,
        "pt_level": pt_level, "sl_level": sl_level,
        "exit_reason": "REGIME_NO_OPP",
    }


def main():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Loading schedule and existing tick trades...")
    sched = pd.read_parquet(SCHEDULE)
    sched["entry_ts_ns"] = sched["entry_ts_ns"].astype("int64")
    no_flip_sched = sched[~sched["is_va_confirm"]].copy()
    no_flip_sched["entry_dt"] = pd.to_datetime(
        no_flip_sched["entry_ts_ns"], unit="ns", utc=True)
    no_flip_sched["month"] = no_flip_sched["entry_dt"].dt.month
    print(f"  no-flip schedule: {len(no_flip_sched):,}")

    existing_trades = pd.read_parquet(EXISTING_TICK_TRADES)
    existing_trades = existing_trades[existing_trades["exit_filled"]].copy()
    existing_trades["entry_ts_ns"] = existing_trades[
        "entry_ts_ns"].astype("int64")
    va_trades = existing_trades[existing_trades["is_va_confirm"]].copy()
    print(f"  existing VA-confirm tick trades: {len(va_trades):,}  "
          f"(${va_trades['net_pnl'].sum():+,.0f})")

    # Filter to no-flip trades that are also in existing (single-position
    # discipline removed some)
    existing_nf = existing_trades[~existing_trades["is_va_confirm"]
                                       ].copy()
    nf_to_replay = no_flip_sched[
        no_flip_sched["entry_ts_ns"].isin(
            existing_nf["entry_ts_ns"])].copy()
    print(f"  no-flip trades to replay "
          f"(matching existing tick run): {len(nf_to_replay):,}")

    # Load regime flips. Use decision_ts (real-time detection moment
    # = bar_close + 1s), NOT bar_close, to avoid 1s look-ahead.
    snap = pd.read_parquet(SNAPSHOTS,
                              columns=["kind", "decision_ts",
                                        "direction", "session"])
    flips = snap[(snap["kind"] == "regime_flip")
                    & (snap["session"] == "RTH")].copy()
    flips["decision_ts"] = flips["decision_ts"].astype("int64")
    flips = flips.sort_values("decision_ts").reset_index(drop=True)
    flips_up_ts = flips[flips["direction"] == 1
                          ]["decision_ts"].to_numpy()
    flips_dn_ts = flips[flips["direction"] == -1
                          ]["decision_ts"].to_numpy()
    print(f"  RTH regime flips: up={len(flips_up_ts):,}  "
          f"dn={len(flips_dn_ts):,}")

    # Replay per-month
    all_replayed = []
    for month in [1, 2, 3, 4]:
        mbp_path = f"{MBP1_DIR}/NQ_v0_mbp1_2026_{month:02d}.parquet"
        if not Path(mbp_path).exists():
            print(f"  WARN: missing {mbp_path}")
            continue
        print(f"\n  [Month {month:02d}] loading MBP-1...")
        t1 = time.time()
        df = pd.read_parquet(
            mbp_path,
            columns=["ts_event", "bid_px_00", "ask_px_00"])
        if df["ts_event"].dt.tz is None:
            df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")
        # RTH only
        ct = df["ts_event"].dt.tz_convert("America/Chicago")
        mins = ct.dt.hour * 60 + ct.dt.minute
        rth_mask = (mins >= 8 * 60 + 30) & (mins < 15 * 60)
        df = df.loc[rth_mask].copy()
        # Drop invalid
        valid = ((df["bid_px_00"] > 0) & (df["ask_px_00"] > 0)
                  & (df["ask_px_00"] > df["bid_px_00"]))
        df = df.loc[valid].sort_values("ts_event").reset_index(
            drop=True)
        q_ts = df["ts_event"].astype("int64").to_numpy()
        q_bid = df["bid_px_00"].to_numpy().astype("float64")
        q_ask = df["ask_px_00"].to_numpy().astype("float64")
        del df
        gc.collect()
        print(f"    {len(q_ts):,} RTH quotes "
              f"({time.time()-t1:.0f}s)")

        nf_month = nf_to_replay[nf_to_replay["month"] == month]
        print(f"    replaying {len(nf_month):,} no-flip trades...")
        t1 = time.time()
        month_results = []
        for _, tr in nf_month.iterrows():
            d = int(tr["direction"])
            flips_dir = flips_up_ts if d == 1 else flips_dn_ts
            flips_opp = flips_dn_ts if d == 1 else flips_up_ts
            result = replay_no_flip_trade(
                q_ts, q_bid, q_ask,
                int(tr["entry_ts_ns"]), d,
                float(tr["atr_at_signal"]),
                flips_dir, flips_opp,
                PT_ATR, SL_ATR, TIMEOUT_S, BRACKET_START_S)
            if result is not None:
                result["month"] = month
                result["p_score"] = float(tr["p_score"])
                month_results.append(result)
        df_m = pd.DataFrame(month_results)
        df_m["pnl_pts"] = (
            (df_m["exit_fill_price"] - df_m["entry_fill_price"])
            * df_m["direction"])
        df_m["gross_pnl"] = df_m["pnl_pts"] * NQ_MULT
        df_m["net_pnl"] = df_m["gross_pnl"] - COMMISSION_RT
        df_m.to_parquet(OUT_DIR / f"replay_month_{month:02d}.parquet",
                            index=False)
        print(f"    done ({time.time()-t1:.0f}s)  "
              f"n={len(df_m):,}  "
              f"total=${df_m['net_pnl'].sum():+,.0f}  "
              f"mean=${df_m['net_pnl'].mean():+.2f}/tr")
        # Per-reason breakdown
        for reason in ["PT", "SL", "TO", "REGIME"]:
            sub = df_m[df_m["exit_reason"] == reason]
            if len(sub) > 0:
                print(f"      {reason}: n={len(sub)}  "
                      f"total=${sub['net_pnl'].sum():+,.0f}  "
                      f"mean=${sub['net_pnl'].mean():+.2f}/tr  "
                      f"WR={(sub['net_pnl']>0).mean():.1%}")
        all_replayed.append(df_m)
        del q_ts, q_bid, q_ask
        gc.collect()

    # ===== Aggregate =====
    all_nf = pd.concat(all_replayed, ignore_index=True)
    all_nf.to_parquet(OUT_DIR / "no_flip_replay_all.parquet",
                          index=False)

    print(f"\n{'='*78}")
    print("TICK-VALIDATED FALLBACK BRACKET (no-flip cohort, full 2026 OOS)")
    print(f"  Policy: PT={PT_ATR} / SL={SL_ATR} / TO={TIMEOUT_S}s + "
          f"regime transition")
    print(f"{'='*78}")
    print(f"No-flip trades replayed: {len(all_nf):,}")
    print(f"  Total net PnL: ${all_nf['net_pnl'].sum():+,.0f}")
    print(f"  Mean per-tr:   ${all_nf['net_pnl'].mean():+.2f}")
    print(f"  WR:            {(all_nf['net_pnl']>0).mean():.1%}")

    print(f"\nPer-month:")
    for month in [1, 2, 3, 4]:
        sub = all_nf[all_nf["month"] == month]
        if len(sub) > 0:
            print(f"  Mo {month:02d}: n={len(sub):>4}  "
                  f"total=${sub['net_pnl'].sum():+9,.0f}  "
                  f"mean=${sub['net_pnl'].mean():+7.2f}/tr  "
                  f"WR={(sub['net_pnl']>0).mean():.1%}")

    print(f"\nExit reasons:")
    for reason in ["PT", "SL", "TO", "REGIME", "REGIME_NO_OPP"]:
        sub = all_nf[all_nf["exit_reason"] == reason]
        if len(sub) > 0:
            print(f"  {reason:<14}: n={len(sub):>4}  "
                  f"({len(sub)/len(all_nf):>5.1%})  "
                  f"total=${sub['net_pnl'].sum():+9,.0f}  "
                  f"mean=${sub['net_pnl'].mean():+7.2f}/tr")

    print(f"\nCombined (VA-confirm tick + no-flip replay):")
    va_total = va_trades["net_pnl"].sum()
    nf_total = all_nf["net_pnl"].sum()
    combined = va_total + nf_total
    combined_n = len(va_trades) + len(all_nf)
    print(f"  VA-confirm: n={len(va_trades):>4}  "
          f"${va_total:+,.0f}  (${va_trades['net_pnl'].mean():+.2f}/tr)")
    print(f"  No-flip:    n={len(all_nf):>4}  "
          f"${nf_total:+,.0f}  (${all_nf['net_pnl'].mean():+.2f}/tr)")
    print(f"  COMBINED:   n={combined_n:>4}  "
          f"${combined:+,.0f}  (${combined/combined_n:+.2f}/tr)")

    print(f"\nVs baseline (current 60s exit + VA hold):")
    baseline = existing_trades["net_pnl"].sum()
    print(f"  Baseline combined: ${baseline:+,.0f}  "
          f"(${baseline/len(existing_trades):+.2f}/tr)")
    print(f"  Lift: ${combined - baseline:+,.0f}  "
          f"(${(combined - baseline)/combined_n:+.2f}/tr)")

    print(f"\nVs offline 1s-bar prediction:")
    print(f"  Offline grid winner expected: $+35,442 (+$30.61/tr)")
    print(f"  Tick-validated actual:         "
          f"${combined:+,.0f}  (${combined/combined_n:+.2f}/tr)")
    print(f"  Slippage:                      "
          f"${combined - 35442:+,.0f}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
