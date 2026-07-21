"""V_A Stall-to-MA Protection Study v1 — H1 2025 quick study.

Catastrophic stop at flip bar open + stall-triggered MA protection
(causal MA at trigger bar, tighten-only). Uses Safe Exit Replay
Framework — no phantom fills.

Population: NQ RTH 2025-01-01 to 2025-06-30 (1,622 V_A trades).

24 primary variants:
  stall_bars {2, 3, 4, 5} × ma_type {SMA, EMA} × ma_len {9, 13, 21}

3 baselines:
  BASELINE_regime         — V_A regime-exit only (existing)
  BASELINE_cat_only       — V_A + flip-bar-open catastrophic stop, no MA
  BASELINE_cat_only_skip  — V_A + cat stop, skip if cat invalid at entry
                            (diagnostic)

Outputs:
  studies/v_a_exit_recon/results/stall_ma_protection_h1_2025/
    trades_<variant>.parquet
    grid_summary.parquet
    audit_summary.parquet
    STALL_MA_REPORT.md

Hard-fail on any impossible fill (audit). Diagnostic sensitivity
(skip_update_and_hold + worst_in_bar) reported on 3 representative
variants only.
"""

from __future__ import annotations
import os, sys, time, json, math
from pathlib import Path
import numpy as np
import pandas as pd
import pytz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from utils.safe_replay import (
    NQ_TICK, NQ_MULT, validate_stop_at_arm,
    round_protect_to_tick, is_on_tick_grid,
)
from utils.audit_replay_fills import audit_trades, AuditConfig

CT = pytz.timezone("America/Chicago")
PORT = Path("collectors/collector_v2/results/with_tape")
CATALOG_PATH = "./data/catalog/NQ_2025"
OUT = Path(
    "studies/v_a_exit_recon/results/stall_ma_protection_h1_2025")
OUT.mkdir(parents=True, exist_ok=True)

COST_RT = 10.0
NS_PER_MIN = 60_000_000_000
NS_PER_SEC = 1_000_000_000

H1_START_UTC = pd.Timestamp("2025-01-01", tz="UTC").value
H1_END_UTC = pd.Timestamp("2025-07-01", tz="UTC").value


# -------- Format helpers --------
def fmt_d(v):
    if v is None or (isinstance(v, float)
                       and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{100*v:.1f}%"


def fmt_pf(v):
    if v is None or (isinstance(v, float)
                       and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"{v:.2f}"


def max_dd(series):
    arr = pd.Series(series).cumsum().values
    if not len(arr): return 0.0
    peak = np.maximum.accumulate(arr)
    return float((arr - peak).min())


def stats(pnl):
    s = pd.Series(pnl).dropna()
    n = len(s)
    if n == 0:
        return {"n": 0}
    wins = s[s > 0]; losses = s[s < 0]
    pf = (wins.sum() / abs(losses.sum())
            if len(losses) and losses.sum() != 0
            else float("inf"))
    return {
        "n": n, "wr": float((s > 0).mean()),
        "mean": float(s.mean()), "median": float(s.median()),
        "sum": float(s.sum()), "pf": float(pf),
        "max_dd": max_dd(s),
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
    }


# -------- Data loading --------
def load_h1_2025_trades_tape():
    print("Loading 2025 H1 RTH trades + tape...")
    trades = pd.read_parquet(PORT / "NQ_2025/trades.parquet")
    tape = pd.read_parquet(PORT / "NQ_2025/trade_tape.parquet")
    rth = trades[(trades["session"] == "RTH")
                 & (trades["entry_ts"] >= H1_START_UTC)
                 & (trades["entry_ts"] < H1_END_UTC)].copy()
    rth["trade_id"] = rth["decision_event_id"]
    rth["baseline_net_pnl"] = rth["net_pnl"]
    ids = set(rth["decision_event_id"])
    tape_rth = tape[
        tape["decision_event_id"].isin(ids)].copy()
    tape_rth["trade_id"] = tape_rth["decision_event_id"]
    tape_rth = tape_rth.sort_values(
        ["trade_id", "ts_init"]).reset_index(drop=True)
    print(f"  trades={len(rth):,}, tape rows={len(tape_rth):,}")
    return rth, tape_rth


def load_1m_bars():
    print("Loading 1m bars from catalog (Dec 2024 - Jul 2025)...")
    from nautilus_trader.persistence.catalog import (
        ParquetDataCatalog,
    )
    cat = ParquetDataCatalog(CATALOG_PATH)
    # Include 1 month before H1 to warm up MA(21) for early Jan trades
    start = pd.Timestamp("2024-12-01", tz="UTC")
    end = pd.Timestamp("2025-07-01", tz="UTC")
    bars = cat.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=start, end=end)
    rows = []
    for b in bars:
        rows.append((int(b.ts_init), float(b.open),
                       float(b.high), float(b.low),
                       float(b.close)))
    df = pd.DataFrame(rows, columns=[
        "ts_init", "open", "high", "low", "close"])
    df = df.sort_values("ts_init").reset_index(drop=True)
    print(f"  1m bars: {len(df):,}")
    return df


def compute_mas(bars: pd.DataFrame) -> dict:
    print("Computing 6 MAs (SMA/EMA × 9/13/21)...")
    bars = bars.copy()
    series = {}
    for n in (9, 13, 21):
        bars[f"sma_{n}"] = (bars["close"]
            .rolling(n, min_periods=n).mean())
        bars[f"ema_{n}"] = (bars["close"]
            .ewm(span=n, adjust=False, min_periods=n).mean())
        series[("SMA", n)] = dict(
            zip(bars["ts_init"], bars[f"sma_{n}"]))
        series[("EMA", n)] = dict(
            zip(bars["ts_init"], bars[f"ema_{n}"]))
    return series


def build_1m_lookup(bars: pd.DataFrame) -> dict:
    return {int(r["ts_init"]):
              (float(r["open"]), float(r["high"]),
               float(r["low"]), float(r["close"]))
              for _, r in bars.iterrows()}


# -------- Replay core --------
def first_eligible_1m_ts_init(entry_ts: int) -> int:
    """First post-entry 1m bar's ts_init.
    A bar 'fully after entry' has ts_event >= entry_ts.
    ts_event = ts_init - 60s, so ts_init >= entry_ts + 60s.
    """
    if entry_ts % NS_PER_MIN == 0:
        first_ts_event = entry_ts
    else:
        first_ts_event = ((entry_ts // NS_PER_MIN) + 1) * NS_PER_MIN
    return first_ts_event + NS_PER_MIN


def flip_bar_ts_init(decision_ts: int) -> int:
    """The 1m bar where the regime flipped.

    Per collector_v2/strategy.py: decision_ts = bar+1's ts_init + 1s
    lag (bar+1 = the CONFIRMATION bar where HH/LL + momentum is
    checked). The flip bar closed 60s BEFORE bar+1 closed.

    Sequence:
      bar N (flip bar)         closes at flip_bar.ts_init
      bar N+1 (confirmation)   closes at flip_bar.ts_init + 60s = decision_ts - 1s
      decision_ts ≈ bar N+1's close + 1s
      entry fills at decision_ts + 30s

    Therefore: flip_bar.ts_init = floor(decision_ts to 60s) - 60s.
    """
    bar1_ts_init = (decision_ts // NS_PER_MIN) * NS_PER_MIN
    return bar1_ts_init - NS_PER_MIN


def fill_at_or_worse_close(direction: int, stop_px: float,
                                   bar_close: float) -> float:
    """conservative_ohlc + at_or_worse_close convention."""
    if direction == 1:
        return min(stop_px, bar_close)
    return max(stop_px, bar_close)


def fill_worst_in_bar(direction: int, stop_px: float,
                         bar_h: float, bar_l: float) -> float:
    """worst_in_bar convention (diagnostic)."""
    if direction == 1:
        return min(stop_px, bar_l)
    return max(stop_px, bar_h)


def replay_one_trade(
    trade, tape_g, bars_1m_lookup, ma_lookup,
    stall_bars, ohlc_convention="at_or_worse_close",
    invalid_stop_policy="market_exit_now",
    use_cat_stop=True,
):
    """Replay one trade with stall-MA protection.

    Returns: dict with trade record + extra fields.
    """
    entry_ts = int(trade["entry_ts"])
    decision_ts = int(trade["decision_ts"])
    d = int(trade["direction"])
    fill_price = float(trade["fill_price"])
    atr = float(trade["atr_at_signal"])
    baseline_exit_px = float(trade["exit_price"])
    baseline_exit_ts = int(trade["exit_ts"])
    baseline_pnl = float(trade["net_pnl"])

    # Catastrophic stop = flip bar open
    flip_ts = flip_bar_ts_init(decision_ts)
    flip_bar = bars_1m_lookup.get(flip_ts)
    cat_stop = None
    cat_invalid_at_entry = False
    if use_cat_stop and flip_bar is not None:
        cat_stop_raw = flip_bar[0]  # open
        cat_valid, _ = validate_stop_at_arm(d, fill_price,
                                                    cat_stop_raw)
        if not cat_valid:
            cat_invalid_at_entry = True
            # Don't use cat stop; rely on regime/MA exit
            cat_stop = None
        else:
            cat_stop = round_protect_to_tick(
                cat_stop_raw, d, NQ_TICK)

    first_1m_ts = first_eligible_1m_ts_init(entry_ts)

    # Stall state
    armed = False
    protect_px = None
    running_extreme = fill_price  # init at entry price
    stall_count = 0
    n_arms = 0
    n_updates = 0
    n_invalid_at_update = 0

    # Walk tape
    last_ts = None
    for row in tape_g.itertuples():
        ts = int(row.ts_init)
        if ts == last_ts:
            continue  # dedupe
        last_ts = ts
        h = float(row.h); l = float(row.l); c = float(row.c)

        # Skip rows on or before fill (defensive)
        if ts < entry_ts:
            continue

        # 1. Catastrophic stop hit?
        if cat_stop is not None:
            if (d == 1 and l <= cat_stop) or (
                    d == -1 and h >= cat_stop):
                if ohlc_convention == "worst_in_bar":
                    fill_px = fill_worst_in_bar(d, cat_stop, h, l)
                else:
                    fill_px = fill_at_or_worse_close(
                        d, cat_stop, c)
                # round to tick
                fill_px = round_protect_to_tick(
                    fill_px, d, NQ_TICK)
                # impossible-fill safeguard: clamp into bar OHLC
                if fill_px < l: fill_px = l
                if fill_px > h: fill_px = h
                return _finalize_safe(
                    trade, fill_px, ts, "catastrophic",
                    fired_rule=True,
                    extra={
                        "cat_stop": cat_stop,
                        "cat_invalid_at_entry": (
                            cat_invalid_at_entry),
                        "ma_armed": armed,
                        "protect_px": protect_px,
                        "n_arms": n_arms,
                        "n_updates": n_updates,
                        "n_invalid_at_update": n_invalid_at_update,
                    })

        # 2. MA protection hit?
        if armed:
            if (d == 1 and l <= protect_px) or (
                    d == -1 and h >= protect_px):
                if ohlc_convention == "worst_in_bar":
                    fill_px = fill_worst_in_bar(d, protect_px, h, l)
                else:
                    fill_px = fill_at_or_worse_close(
                        d, protect_px, c)
                fill_px = round_protect_to_tick(
                    fill_px, d, NQ_TICK)
                if fill_px < l: fill_px = l
                if fill_px > h: fill_px = h
                return _finalize_safe(
                    trade, fill_px, ts, "ma_protect",
                    fired_rule=True,
                    extra={
                        "cat_stop": cat_stop,
                        "cat_invalid_at_entry": (
                            cat_invalid_at_entry),
                        "ma_armed": armed,
                        "protect_px": protect_px,
                        "n_arms": n_arms,
                        "n_updates": n_updates,
                        "n_invalid_at_update": n_invalid_at_update,
                    })

        # 3. 1m bar boundary detection (post-entry only)
        if ts in bars_1m_lookup and ts >= first_1m_ts:
            bar = bars_1m_lookup[ts]
            o1, h1, l1, c1 = bar
            # Update running extreme + stall counter
            if d == 1:
                if h1 > running_extreme:
                    running_extreme = h1
                    stall_count = 0
                else:
                    stall_count += 1
            else:
                if l1 < running_extreme:
                    running_extreme = l1
                    stall_count = 0
                else:
                    stall_count += 1

            if stall_count >= stall_bars:
                # Compute MA at this bar
                ma_value = ma_lookup.get(ts)
                if ma_value is not None and not pd.isna(ma_value):
                    new_protect_raw = float(ma_value)
                    new_protect = round_protect_to_tick(
                        new_protect_raw, d, NQ_TICK)
                    # Validate vs current bar close (price snapshot
                    # at trigger time)
                    valid, _ = validate_stop_at_arm(
                        d, c1, new_protect)
                    if not valid:
                        n_invalid_at_update += 1
                        if invalid_stop_policy == (
                                "market_exit_now"):
                            return _finalize_safe(
                                trade, c1, ts,
                                "ma_invalid_market_exit",
                                fired_rule=True,
                                extra={
                                    "cat_stop": cat_stop,
                                    "cat_invalid_at_entry": (
                                        cat_invalid_at_entry),
                                    "ma_armed": armed,
                                    "protect_px": protect_px,
                                    "n_arms": n_arms,
                                    "n_updates": n_updates,
                                    "n_invalid_at_update": (
                                        n_invalid_at_update),
                                })
                        # else skip_update_and_hold:
                        # don't update, reset counter
                        stall_count = 0
                    else:
                        if armed:
                            tighter = (
                                (d == 1 and new_protect
                                  > protect_px)
                                or (d == -1 and new_protect
                                      < protect_px))
                            if tighter:
                                protect_px = new_protect
                                n_updates += 1
                            # else keep existing
                        else:
                            protect_px = new_protect
                            armed = True
                            n_arms += 1
                        stall_count = 0
                else:
                    # MA not available (warmup etc.) — reset
                    # counter but don't arm
                    stall_count = 0

    # Loop ended without hit → use baseline regime exit
    return _finalize_safe(
        trade, baseline_exit_px, baseline_exit_ts, "regime",
        fired_rule=False,
        extra={
            "cat_stop": cat_stop,
            "cat_invalid_at_entry": cat_invalid_at_entry,
            "ma_armed": armed,
            "protect_px": protect_px,
            "n_arms": n_arms,
            "n_updates": n_updates,
            "n_invalid_at_update": n_invalid_at_update,
        })


def _finalize_safe(t, exit_px, exit_ts, reason, fired_rule, extra):
    d = int(t["direction"])
    ep = float(t["fill_price"])
    gross = (exit_px - ep) * d * NQ_MULT
    net = gross - COST_RT
    base = {
        "trade_id": int(t["decision_event_id"]),
        "decision_event_id": int(t["decision_event_id"]),
        "entry_ts": int(t["entry_ts"]),
        "decision_ts": int(t["decision_ts"]),
        "exit_ts": int(exit_ts),
        "fill_price": float(ep),
        "exit_price": float(exit_px),
        "direction": d,
        "atr_at_signal": float(t["atr_at_signal"]),
        "gross_pnl": float(gross),
        "net_pnl": float(net),
        "hold_s": (int(exit_ts) - int(t["entry_ts"])) / 1e9,
        "exit_reason": reason,
        "fired_rule": bool(fired_rule),
        "baseline_net_pnl": float(t["net_pnl"]),
    }
    base.update(extra)
    return base


def replay_variant(trades, tape, bars_1m_lookup, ma_lookup,
                       stall_bars, ohlc_convention="at_or_worse_close",
                       invalid_stop_policy="market_exit_now",
                       use_cat_stop=True):
    out = []
    tape_groups = tape.groupby("trade_id", sort=False)
    for _, t in trades.iterrows():
        # Look up tape by trade_id (multi-year safe — trade_id may
        # be year-prefixed to avoid decision_event_id collisions
        # across years; falls back to decision_event_id if not set)
        ev = int(t.get("trade_id", t["decision_event_id"]))
        if ev not in tape_groups.groups:
            # No tape — fall back to regime exit
            out.append(_finalize_safe(
                t, float(t["exit_price"]), int(t["exit_ts"]),
                "regime_no_tape", fired_rule=False,
                extra={"cat_stop": None,
                          "cat_invalid_at_entry": False,
                          "ma_armed": False, "protect_px": None,
                          "n_arms": 0, "n_updates": 0,
                          "n_invalid_at_update": 0}))
            continue
        g = tape_groups.get_group(ev)
        out.append(replay_one_trade(
            t, g, bars_1m_lookup, ma_lookup, stall_bars,
            ohlc_convention=ohlc_convention,
            invalid_stop_policy=invalid_stop_policy,
            use_cat_stop=use_cat_stop))
    return pd.DataFrame(out)


# -------- Summary --------
def variant_summary(name: str, df: pd.DataFrame) -> dict:
    s = stats(df["net_pnl"])
    out = {"variant": name, **{f"all_{k}": v for k, v in s.items()}}
    # Reason breakdown
    rcounts = df["exit_reason"].value_counts()
    n = len(df)
    out["pct_cat"] = float(
        rcounts.get("catastrophic", 0)) / max(n, 1)
    out["pct_ma_protect"] = float(
        rcounts.get("ma_protect", 0)) / max(n, 1)
    out["pct_ma_invalid_market"] = float(
        rcounts.get("ma_invalid_market_exit", 0)) / max(n, 1)
    out["pct_regime"] = float(
        rcounts.get("regime", 0) + rcounts.get(
            "regime_no_tape", 0)) / max(n, 1)
    out["pct_cat_invalid_at_entry"] = float(
        df["cat_invalid_at_entry"].fillna(
            False).astype(bool).sum() / max(n, 1))
    out["med_hold_s"] = float(df["hold_s"].median())
    out["avg_n_arms"] = float(df["n_arms"].fillna(0).mean())
    out["avg_n_updates"] = float(df["n_updates"].fillna(0).mean())
    out["avg_n_invalid_at_update"] = float(
        df["n_invalid_at_update"].fillna(0).mean())
    # Top-1% share
    sn = df["net_pnl"].sort_values(ascending=False)
    top1 = sn.head(max(1, int(len(sn) * 0.01))).sum()
    total = sn.sum()
    out["top1_share"] = (
        float(top1 / total) if total != 0 else float("nan"))
    # vs baseline
    out["all_vs_base_total"] = float(
        df["net_pnl"].sum() - df["baseline_net_pnl"].sum())
    out["all_vs_base_mean"] = float(
        (df["net_pnl"] - df["baseline_net_pnl"]).mean())
    return out


# -------- Audit helper --------
def build_bars_lookup_fn(bars_1m_lookup, tape):
    """Audit needs OHLC at exit_ts. Combine 1m bar OHLC and 1s
    tape OHLC for full coverage.
    """
    tape_ohlc = (tape[["ts_init", "h", "l", "c"]]
                  .drop_duplicates(subset="ts_init", keep="first")
                  .set_index("ts_init"))

    def lookup(ts_ns: int):
        # Prefer 1m bar (canonical)
        if ts_ns in bars_1m_lookup:
            o, h, l, c = bars_1m_lookup[ts_ns]
            return (o, h, l, c)
        # Else try tape (1s bar)
        if ts_ns in tape_ohlc.index:
            row = tape_ohlc.loc[ts_ns]
            return (float(row["c"]), float(row["h"]),
                      float(row["l"]), float(row["c"]))
        return None
    return lookup


# -------- Main --------
def main():
    t_start = time.time()
    print("=" * 70)
    print("V_A Stall-to-MA Protection Study v1 — H1 2025 RTH")
    print("=" * 70)

    # Step 1: load data
    trades, tape = load_h1_2025_trades_tape()
    bars_1m = load_1m_bars()
    ma_series = compute_mas(bars_1m)
    bars_1m_lookup = build_1m_lookup(bars_1m)
    bars_lookup_fn = build_bars_lookup_fn(bars_1m_lookup, tape)

    # Step 2: baselines
    print("\nRunning baselines...")
    summaries = []
    audits = []
    audit_failed = []

    # B1: V_A regime-only (no rule, no cat stop)
    b1_rows = []
    for _, t in trades.iterrows():
        b1_rows.append(_finalize_safe(
            t, float(t["exit_price"]), int(t["exit_ts"]),
            "regime", fired_rule=False,
            extra={"cat_stop": None,
                      "cat_invalid_at_entry": False,
                      "ma_armed": False, "protect_px": None,
                      "n_arms": 0, "n_updates": 0,
                      "n_invalid_at_update": 0}))
    base_df = pd.DataFrame(b1_rows)
    base_df.to_parquet(
        OUT / "trades_BASELINE_regime.parquet", index=False)
    summaries.append(variant_summary("BASELINE_regime", base_df))
    print(f"  BASELINE_regime: total "
          f"{fmt_d(summaries[-1]['all_sum'])}, mean "
          f"{fmt_d(summaries[-1]['all_mean'])}")

    # B2: cat stop only (no MA), at_or_worse_close, market_exit_now
    # Use stall_bars=999 to never arm MA (cat-only behavior)
    cat_only_df = replay_variant(
        trades, tape, bars_1m_lookup,
        ma_lookup={}, stall_bars=999,
        use_cat_stop=True)
    cat_only_df.to_parquet(
        OUT / "trades_BASELINE_cat_only.parquet", index=False)
    summaries.append(variant_summary(
        "BASELINE_cat_only", cat_only_df))
    print(f"  BASELINE_cat_only: total "
          f"{fmt_d(summaries[-1]['all_sum'])}, mean "
          f"{fmt_d(summaries[-1]['all_mean'])}, "
          f"cat-exits {fmt_p(summaries[-1]['pct_cat'])}, "
          f"cat-invalid-at-entry "
          f"{fmt_p(summaries[-1]['pct_cat_invalid_at_entry'])}")

    # Audit cat-only
    ar = audit_trades(cat_only_df, bars_lookup_fn,
                            AuditConfig(
                                hard_fail_on_impossible=False))
    audits.append({"variant": "BASELINE_cat_only",
                       "impossible": ar.impossible_fills_n,
                       "impossible_pnl": ar.impossible_fills_pnl})
    if ar.has_impossible_fills:
        audit_failed.append("BASELINE_cat_only")

    # Step 3: 24-variant grid
    print("\nRunning 24-variant grid (stall × MA type × MA len)...")
    STALL_BARS = [2, 3, 4, 5]
    MA_TYPES = ["SMA", "EMA"]
    MA_LENS = [9, 13, 21]

    grid = []
    for sb in STALL_BARS:
        for mt in MA_TYPES:
            for ml in MA_LENS:
                grid.append((sb, mt, ml))

    for i, (sb, mt, ml) in enumerate(grid, 1):
        t0 = time.time()
        name = f"S{sb}_{mt}{ml}"
        ma_lookup = ma_series[(mt, ml)]
        df = replay_variant(
            trades, tape, bars_1m_lookup, ma_lookup,
            stall_bars=sb,
            ohlc_convention="at_or_worse_close",
            invalid_stop_policy="market_exit_now",
            use_cat_stop=True)
        df.to_parquet(
            OUT / f"trades_{name}.parquet", index=False)
        # Audit
        ar = audit_trades(df, bars_lookup_fn,
                                AuditConfig(
                                    hard_fail_on_impossible=False))
        audits.append({"variant": name,
                            "impossible": ar.impossible_fills_n,
                            "impossible_pnl": (
                                ar.impossible_fills_pnl)})
        if ar.has_impossible_fills:
            audit_failed.append(name)
        # Summary
        summ = variant_summary(name, df)
        summaries.append(summ)
        elapsed = time.time() - t0
        print(f"  [{i:2d}/24] {name:<14} "
              f"total {fmt_d(summ['all_sum'])} "
              f"mean {fmt_d(summ['all_mean'])} "
              f"cat={fmt_p(summ['pct_cat'])} "
              f"ma={fmt_p(summ['pct_ma_protect'])} "
              f"reg={fmt_p(summ['pct_regime'])} "
              f"imposs={ar.impossible_fills_n} ({elapsed:.1f}s)")

    # Step 4: diagnostic sensitivity (3 representative)
    print("\nDiagnostic sensitivity (skip + worst_in_bar) on 3 reps...")
    sens_variants = [
        ("S3_SMA21", 3, "SMA", 21),
        ("S4_EMA13", 4, "EMA", 13),
        ("S2_EMA9",  2, "EMA", 9),
    ]
    sens_rows = []
    for name, sb, mt, ml in sens_variants:
        ma_lookup = ma_series[(mt, ml)]
        for label, kw in [
            ("worst_in_bar", {
                "ohlc_convention": "worst_in_bar",
                "invalid_stop_policy": "market_exit_now"}),
            ("skip_update_and_hold", {
                "ohlc_convention": "at_or_worse_close",
                "invalid_stop_policy": "skip_update_and_hold"}),
        ]:
            df = replay_variant(
                trades, tape, bars_1m_lookup, ma_lookup,
                stall_bars=sb, use_cat_stop=True, **kw)
            df.to_parquet(
                OUT / f"sens_{name}_{label}.parquet",
                index=False)
            s = variant_summary(f"{name}__{label}", df)
            sens_rows.append(s)
            print(f"  {name} [{label:<22}] total "
                  f"{fmt_d(s['all_sum'])}, mean "
                  f"{fmt_d(s['all_mean'])}/trade")
    sens_df = pd.DataFrame(sens_rows)
    sens_df.to_parquet(OUT / "sensitivity_summary.parquet",
                              index=False)

    # Step 5: save summaries
    summ_df = pd.DataFrame(summaries)
    summ_df.to_parquet(OUT / "grid_summary.parquet", index=False)
    audit_df = pd.DataFrame(audits)
    audit_df.to_parquet(OUT / "audit_summary.parquet",
                              index=False)

    # Step 6: report
    print("\nWriting STALL_MA_REPORT.md...")
    write_report(summaries, audits, sens_df, audit_failed)

    elapsed_total = (time.time() - t_start) / 60
    print(f"\nDone. Total: {elapsed_total:.1f} min")
    return 0 if not audit_failed else 1


def write_report(summaries, audits, sens_df, audit_failed):
    base_regime = next(s for s in summaries
                          if s["variant"] == "BASELINE_regime")
    base_total = base_regime["all_sum"]
    base_mean = base_regime["all_mean"]
    base_pf = base_regime["all_pf"]
    base_wr = base_regime["all_wr"]

    cat_only = next(s for s in summaries
                       if s["variant"] == "BASELINE_cat_only")

    lines = []
    lines.append("# V_A Stall-to-MA Protection Study v1")
    lines.append("")
    lines.append(f"Run: {pd.Timestamp.now(tz='UTC').isoformat()}")
    lines.append("")
    lines.append("Strategy-class feasibility test. NQ RTH "
                  "2025-01-01 to 2025-06-30. Catastrophic stop at "
                  "flip-bar open + stall-triggered MA protection "
                  "(causal MA at trigger bar, tighten-only).")
    lines.append("")
    lines.append("## Configuration")
    lines.append("")
    lines.append("- Span: 2025 H1 RTH")
    lines.append(f"- Population: {base_regime['all_n']:,} V_A "
                  "trades")
    lines.append("- Cost: $10 RT")
    lines.append("- Framework: `utils/safe_replay`")
    lines.append("- Primary mode: conservative_ohlc / "
                  "at_or_worse_close / market_exit_now")
    lines.append("- 24 variants: stall {2,3,4,5} × {SMA,EMA} × "
                  "{9,13,21}")
    lines.append("")

    lines.append("## Audit verdict")
    lines.append("")
    if audit_failed:
        lines.append(f"- **FAIL** — {len(audit_failed)} variants "
                      f"with impossible fills:")
        for n in audit_failed:
            lines.append(f"  - `{n}`")
    else:
        lines.append("- **PASS** — 0 impossible fills across all "
                      "variants")
    lines.append("")

    lines.append("## Baselines")
    lines.append("")
    lines.append(f"- **BASELINE_regime** (no rule): n="
                  f"{base_regime['all_n']:,}, total "
                  f"{fmt_d(base_total)}, mean {fmt_d(base_mean)}, "
                  f"PF {fmt_pf(base_pf)}, WR {fmt_p(base_wr)}")
    lines.append(f"- **BASELINE_cat_only** (cat stop only, no MA): "
                  f"total {fmt_d(cat_only['all_sum'])}, mean "
                  f"{fmt_d(cat_only['all_mean'])}, "
                  f"cat-exits {fmt_p(cat_only['pct_cat'])}, "
                  f"cat-invalid-at-entry "
                  f"{fmt_p(cat_only['pct_cat_invalid_at_entry'])}, "
                  f"vs base "
                  f"{fmt_d(cat_only['all_vs_base_total'])}")
    lines.append("")

    # Survivors
    surviving = [s for s in summaries
                    if s["variant"].startswith("S")
                    and s["all_sum"] is not None
                    and s["all_sum"] > base_total]
    lines.append("## Survivors (beat BASELINE_regime)")
    lines.append("")
    if not surviving:
        lines.append("**No variant beats BASELINE_regime "
                      f"({fmt_d(base_total)}).**")
    else:
        lines.append(f"{len(surviving)} variants beat baseline:")
        lines.append("")
        lines.append("| Variant | Total | vs Base | Mean | PF | "
                     "WR | Med hold | %cat | %ma | %reg |")
        lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
        for s in sorted(surviving, key=lambda x: -x["all_sum"]):
            lines.append(
                f"| `{s['variant']}` | "
                f"{fmt_d(s['all_sum'])} | "
                f"+{fmt_d(s['all_vs_base_total'])} | "
                f"{fmt_d(s['all_mean'])} | "
                f"{fmt_pf(s['all_pf'])} | "
                f"{fmt_p(s['all_wr'])} | "
                f"{s['med_hold_s']:.0f}s | "
                f"{fmt_p(s['pct_cat'])} | "
                f"{fmt_p(s['pct_ma_protect'])} | "
                f"{fmt_p(s['pct_regime'])} |")
    lines.append("")

    # Full scoreboard
    lines.append("## Full scoreboard")
    lines.append("")
    lines.append("| Variant | n | Total | vs Base | Mean | "
                 "Median | PF | WR | DD | AvgWin | AvgLoss | "
                 "MedHold | %cat | %ma | %reg | %inv@upd | "
                 "avg arms | top-1% |")
    lines.append("|" + "|".join(["---"] * 18) + "|")
    for s in summaries:
        is_base = s["variant"].startswith("BASELINE")
        delta = s.get("all_vs_base_total", 0.0)
        sign = "+" if delta >= 0 else ""
        delta_str = ("(base)" if s["variant"]
                       == "BASELINE_regime"
                       else f"{sign}{fmt_d(delta)}")
        prefix = "**" if is_base else ""
        suffix = "**" if is_base else ""
        lines.append(
            f"| {prefix}`{s['variant']}`{suffix} | "
            f"{s['all_n']:,} | "
            f"{fmt_d(s.get('all_sum'))} | "
            f"{delta_str} | "
            f"{fmt_d(s.get('all_mean'))} | "
            f"{fmt_d(s.get('all_median'))} | "
            f"{fmt_pf(s.get('all_pf'))} | "
            f"{fmt_p(s.get('all_wr'))} | "
            f"{fmt_d(s.get('all_max_dd'))} | "
            f"{fmt_d(s.get('all_avg_win'))} | "
            f"{fmt_d(s.get('all_avg_loss'))} | "
            f"{s.get('med_hold_s', 0):.0f}s | "
            f"{fmt_p(s.get('pct_cat', 0))} | "
            f"{fmt_p(s.get('pct_ma_protect', 0))} | "
            f"{fmt_p(s.get('pct_regime', 0))} | "
            f"{s.get('avg_n_invalid_at_update', 0):.2f} | "
            f"{s.get('avg_n_arms', 0):.2f} | "
            f"{fmt_p(s.get('top1_share', 0))} |")
    lines.append("")

    # Sensitivity
    lines.append("## Diagnostic sensitivity")
    lines.append("")
    lines.append("Bounds on result under alternative settings.")
    lines.append("")
    lines.append("| Variant | Mode | Total | Mean | PF | WR | "
                 "%cat | %ma | %reg |")
    lines.append("|---|---|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in sens_df.iterrows():
        var, mode = r["variant"].split("__", 1)
        lines.append(
            f"| `{var}` | {mode} | "
            f"{fmt_d(r['all_sum'])} | "
            f"{fmt_d(r['all_mean'])} | "
            f"{fmt_pf(r['all_pf'])} | "
            f"{fmt_p(r['all_wr'])} | "
            f"{fmt_p(r['pct_cat'])} | "
            f"{fmt_p(r['pct_ma_protect'])} | "
            f"{fmt_p(r['pct_regime'])} |")
    lines.append("")

    # Audit detail
    lines.append("## Audit detail")
    lines.append("")
    lines.append("| Variant | impossible | impossible_pnl |")
    lines.append("|---|--:|--:|")
    for a in audits:
        lines.append(
            f"| `{a['variant']}` | {a['impossible']} | "
            f"{fmt_d(a['impossible_pnl'])} |")
    lines.append("")

    # Conclusion
    lines.append("## Conclusion")
    lines.append("")
    if not surviving:
        lines.append("- **No variant beat baseline regime exit on "
                      "H1 2025 RTH.** The stall-to-MA protection "
                      "concept is not viable on V_A as tested. No "
                      "expansion to OOS warranted.")
    else:
        lines.append(f"- {len(surviving)} variant(s) beat "
                      "baseline. Recommend full-year IS + OOS "
                      "expansion for top candidates.")
    lines.append("")
    lines.append("**Main question answered:** "
                  + ("Yes — at least one stall-MA variant "
                       "produces real edge under safe replay." if
                     surviving else
                     "No — stall-based MA protection on V_A does "
                     "not improve net of regime exit, even before "
                     "considering robustness."))
    lines.append("")

    (OUT / "STALL_MA_REPORT.md").write_text(
        "\n".join(lines), encoding="utf-8")
    print(f"  Report: {OUT / 'STALL_MA_REPORT.md'}")


if __name__ == "__main__":
    sys.exit(main())
