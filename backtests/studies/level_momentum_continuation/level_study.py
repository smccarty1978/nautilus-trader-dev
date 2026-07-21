"""Level Momentum Continuation Study — Goldilocks Filter
==========================================================

Tests whether a 1m bar that closes BEYOND a "Goldilocks" level
(00/11/25/50/75/90 within each 100-pt handle), with a close in the
LOWER 50% of the move toward the next level, predicts continuation
to the next level (target = next level minus 10 ticks).

Mechanics
---------
- Levels per 100-pt handle: 00, 11, 25, 50, 75, 90.
- Sequence wraps across handles: ..., 75, 90, 00 (next), 11, ...
- Long trigger: prior_close < L AND new_close > L (level breached up)
- Short trigger: prior_close > L AND new_close < L (level breached down)
- Goldilocks filter (long L→Y where Y=next level above):
    target = Y - 2.5
    midpoint = (L + target) / 2
    valid: L < close < midpoint  (strict inequalities)
- Goldilocks filter (short L→Y where Y=next level below):
    target = Y + 2.5
    midpoint = (L + target) / 2
    valid: midpoint < close < L
- Multi-level breach in one bar: take the LATEST qualifying level
  (highest for long, lowest for short).
- Re-entry: every Goldilocks-qualifying close is an independent
  trigger.
- Entry: open of the bar AFTER the trigger (causal).
- Exit priority within a bar: stop-out beats target (conservative).
- Stop = level ONE PRIOR in sequence:
    long L→Y: stop is the level below L (e.g. long 50→75 stops at 25)
    short L→Y: stop is the level above L (e.g. short 50→25 stops at 75)
- Time limit: 120 bars (120 min). Mark to bar-120 close at expiry.

Sign of forward outcome
-----------------------
- "win" = target hit before stop, before time
- "loss" = stop hit before target (within time limit)
- "timed_out" = neither hit by bar 120; PnL marked to bar-120 close
"""
from __future__ import annotations

import os, sys
from dataclasses import dataclass, field
from datetime import time as dt_time, date
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)


# ---------------- Levels ----------------

LEVELS = (0.0, 11.0, 25.0, 50.0, 75.0, 90.0)
HANDLE = 100.0
TICK = 0.25
TARGET_BUFFER_TICKS = 10
TARGET_BUFFER_PTS = TARGET_BUFFER_TICKS * TICK  # = 2.5

NEXT_LEVEL_UP = {0.0: 11.0, 11.0: 25.0, 25.0: 50.0,
                       50.0: 75.0, 75.0: 90.0,
                       90.0: 100.0}  # 100 = 00 of next handle
NEXT_LEVEL_DN = {0.0: -10.0, 11.0: 0.0, 25.0: 11.0,
                       50.0: 25.0, 75.0: 50.0, 90.0: 75.0}
PRIOR_IN_SEQ_UP = {0.0: -10.0, 11.0: 0.0, 25.0: 11.0,
                          50.0: 25.0, 75.0: 50.0, 90.0: 75.0}
PRIOR_IN_SEQ_DN = {0.0: 11.0, 11.0: 25.0, 25.0: 50.0,
                          50.0: 75.0, 75.0: 90.0,
                          90.0: 100.0}


def absolute_levels_in_range(low: float, high: float) -> list[float]:
    """All absolute level prices within [low, high]."""
    h_lo = int(low // HANDLE)
    h_hi = int(high // HANDLE)
    out = []
    for h in range(h_lo, h_hi + 2):
        base = h * HANDLE
        for offset in LEVELS:
            p = base + offset
            if low <= p <= high:
                out.append(p)
    return out


def next_level_above(price: float) -> float:
    """Smallest absolute level strictly greater than price."""
    h = int(price // HANDLE)
    base = h * HANDLE
    for offset in LEVELS:
        if base + offset > price:
            return base + offset
    return (h + 1) * HANDLE  # 00 of next handle


def next_level_below(price: float) -> float:
    """Largest absolute level strictly less than price."""
    h = int(price // HANDLE)
    base = h * HANDLE
    for offset in reversed(LEVELS):
        if base + offset < price:
            return base + offset
    return h * HANDLE - (HANDLE - 90.0)  # 90 of prior handle


def prior_level_in_sequence_long(L: float) -> float:
    """Level one prior in UP sequence (used as stop for long L→Y)."""
    h = int(L // HANDLE)
    offset = L - h * HANDLE
    if offset == 0.0:
        return h * HANDLE - (HANDLE - 90.0)  # 90 of prior handle
    base = h * HANDLE
    for level in LEVELS:
        if base + level == L:
            idx = LEVELS.index(level)
            return base + LEVELS[idx - 1] if idx > 0 else (
                h * HANDLE - (HANDLE - 90.0))
    raise ValueError(f"L={L} not on level grid")


def prior_level_in_sequence_short(L: float) -> float:
    """Level one prior in DOWN sequence (used as stop for short L→Y).
    For shorts going down, "prior in sequence" means the level we'd
    return UP to if the trade fails.
    """
    h = int(L // HANDLE)
    offset = L - h * HANDLE
    if offset == 90.0:
        return (h + 1) * HANDLE  # 00 of next handle
    base = h * HANDLE
    for level in LEVELS:
        if base + level == L:
            idx = LEVELS.index(level)
            return base + LEVELS[idx + 1] if idx < len(LEVELS) - 1 else (
                (h + 1) * HANDLE)
    raise ValueError(f"L={L} not on level grid")


# ---------------- Data loading ----------------

def load_v0_1s(parquet_path: Path) -> pd.DataFrame:
    """Load Databento .v.0 ohlcv-1s parquet. Returns DataFrame
    indexed by close-time UTC with open/high/low/close/volume.

    Source has ts_event = OPEN time of 1s bar. We add 1s to get
    close time for indexing (matches NT 1m ts_init convention).
    """
    df = pd.read_parquet(parquet_path)
    df = df[["open", "high", "low", "close", "volume"]].copy()
    # Index is ts_event (open time); shift to close time
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index + pd.Timedelta(seconds=1)
    df.index.name = "ts_close"
    df = df.sort_index()
    return df


def resample_1s_to_1m(bars_1s: pd.DataFrame) -> pd.DataFrame:
    """Resample 1s -> 1m, label at right (close-time)."""
    out = bars_1s.resample(
        "1min", label="right", closed="right").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum"})
    out = out.dropna(subset=["open", "high", "low", "close"])
    return out


def annotate_sessions_ct(bars: pd.DataFrame) -> pd.DataFrame:
    """Add ts_ct, session ('RTH'/'ETH'), session_id, year columns."""
    out = bars.copy()
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    ts_ct = out.index.tz_convert("America/Chicago")
    rth_start = dt_time(8, 30, 0)
    rth_end = dt_time(15, 0, 0)
    times = ts_ct.time
    weekday = ts_ct.weekday
    is_weekday = weekday < 5
    is_rth = is_weekday & (times >= rth_start) & (times < rth_end)
    session = np.where(is_rth, "RTH", "ETH")

    eth_anchor = ts_ct.normalize()
    eth_anchor = np.where(
        ts_ct.hour >= 17,
        eth_anchor + pd.Timedelta(days=1), eth_anchor)
    eth_anchor = pd.DatetimeIndex(eth_anchor)
    rth_date = ts_ct.normalize()
    session_id = np.where(
        is_rth,
        rth_date.strftime("%Y-%m-%d") + "_RTH",
        eth_anchor.strftime("%Y-%m-%d") + "_ETH")

    out["ts_ct"] = ts_ct
    out["session"] = session
    out["session_id"] = session_id
    out["year"] = ts_ct.year
    out["hour_ct"] = ts_ct.hour
    return out


# ---------------- Roll filter ----------------

def quarterly_roll_dates(year: int) -> list[date]:
    """3rd Thursday of Mar/Jun/Sep/Dec for the given year."""
    rolls = []
    for month in (3, 6, 9, 12):
        first = date(year, month, 1)
        offset = (3 - first.weekday()) % 7
        rolls.append(date(year, month, 1 + offset + 14))
    return rolls


def filter_roll_window(bars: pd.DataFrame,
                            window_days: int) -> tuple[pd.DataFrame, int]:
    if window_days <= 0:
        return bars, 0
    years = sorted(set(bars["year"].values))
    drop_dates: set[date] = set()
    for yr in years:
        for rd in quarterly_roll_dates(int(yr)):
            for delta in range(-window_days, window_days + 1):
                drop_dates.add(rd + pd.Timedelta(days=delta).to_pytimedelta())
    ct_dates = bars["ts_ct"].dt.date
    keep = ~ct_dates.isin(drop_dates)
    return bars[keep].copy(), int((~keep).sum())


# ---------------- Goldilocks trigger detection ----------------

@dataclass
class Trigger:
    bar_idx: int
    direction: int            # +1 long, -1 short
    breach_level: float       # absolute price level that was breached
    next_level: float         # absolute next level in direction
    target: float
    stop: float
    midpoint: float           # used for filter check
    close_at_breach: float
    bar_ts_close: pd.Timestamp
    bar_session: str


def detect_triggers(bars: pd.DataFrame) -> list[Trigger]:
    """One pass over all bars to detect all Goldilocks-qualifying
    triggers. Multi-level breach in one bar: take the latest
    qualifying level (highest for long, lowest for short)."""
    bars = bars.reset_index(drop=False)
    closes = bars["close"].values
    sessions = bars["session"].values
    ts_closes = bars["ts_close"].values
    n = len(bars)
    out: list[Trigger] = []
    for i in range(1, n):
        prev_c = closes[i - 1]
        cur_c = closes[i]
        if cur_c == prev_c:
            continue
        # All levels strictly between (prev_c, cur_c) for long,
        # or (cur_c, prev_c) for short, that lie in [prev_c, cur_c]
        if cur_c > prev_c:
            d = 1
            lo, hi = prev_c, cur_c
        else:
            d = -1
            lo, hi = cur_c, prev_c
        levels = absolute_levels_in_range(lo, hi)
        if d == 1:
            breached = [L for L in levels
                          if prev_c < L and cur_c > L]
            if not breached: continue
            # Latest qualifying level: highest
            breached_sorted = sorted(breached, reverse=True)
        else:
            breached = [L for L in levels
                          if prev_c > L and cur_c < L]
            if not breached: continue
            # Latest qualifying level: lowest
            breached_sorted = sorted(breached)

        # Find the FIRST (latest in dir order) that passes Goldilocks
        for L in breached_sorted:
            if d == 1:
                Y = next_level_above(L + 1e-9)
                target = Y - TARGET_BUFFER_PTS
                midpoint = (L + target) / 2.0
                # Filter: L < cur_c < midpoint  (strict)
                if not (L < cur_c < midpoint):
                    continue
                stop = prior_level_in_sequence_long(L)
            else:
                Y = next_level_below(L - 1e-9)
                target = Y + TARGET_BUFFER_PTS
                midpoint = (L + target) / 2.0
                # Filter: midpoint < cur_c < L (strict)
                if not (midpoint < cur_c < L):
                    continue
                stop = prior_level_in_sequence_short(L)

            out.append(Trigger(
                bar_idx=i, direction=d, breach_level=L,
                next_level=Y, target=target, stop=stop,
                midpoint=midpoint, close_at_breach=cur_c,
                bar_ts_close=ts_closes[i],
                bar_session=sessions[i]))
            break  # only the latest qualifying level per bar
    return out


# ---------------- Forward simulation ----------------

@dataclass
class TradeOutcome:
    trigger: Trigger
    entry_idx: int
    entry_price: float
    entry_ts_close: pd.Timestamp
    entry_session: str
    exit_idx: int
    exit_price: float
    exit_ts_close: pd.Timestamp
    bars_held: int
    outcome: str             # "win" / "loss" / "timed_out"
    mae_pts: float           # max adverse excursion (absolute pts)
    pnl_pts: float           # signed: positive = MR favorable for trade dir


def simulate_trade(t: Trigger, bars: pd.DataFrame,
                       max_bars: int = 120) -> TradeOutcome | None:
    """Enter at open of bar (t.bar_idx + 1). Walk forward up to
    max_bars bars, checking stop-then-target priority within each
    bar. If neither hits by max_bars, mark to that bar's close.
    """
    n = len(bars)
    entry_idx = t.bar_idx + 1
    if entry_idx >= n:
        return None
    opens = bars["open"].values
    highs = bars["high"].values
    lows = bars["low"].values
    closes = bars["close"].values
    ts_closes = bars["ts_close"].values
    sessions = bars["session"].values

    entry_price = opens[entry_idx]
    entry_ts = ts_closes[entry_idx]
    entry_session = sessions[entry_idx]
    d = t.direction
    target = t.target
    stop = t.stop

    last_bar = min(entry_idx + max_bars - 1, n - 1)
    mae_pts = 0.0
    for i in range(entry_idx, last_bar + 1):
        h = highs[i]
        l = lows[i]
        c = closes[i]
        # MAE: how far against the trade did price go?
        if d == 1:
            adverse = entry_price - l
        else:
            adverse = h - entry_price
        if adverse > mae_pts:
            mae_pts = adverse
        # Check stop-then-target (conservative — stop wins ties)
        if d == 1:
            stop_hit = l <= stop
            target_hit = h >= target
        else:
            stop_hit = h >= stop
            target_hit = l <= target
        if stop_hit:
            exit_price = stop
            return TradeOutcome(
                trigger=t, entry_idx=entry_idx,
                entry_price=entry_price,
                entry_ts_close=entry_ts,
                entry_session=entry_session,
                exit_idx=i, exit_price=exit_price,
                exit_ts_close=ts_closes[i],
                bars_held=i - entry_idx + 1,
                outcome="loss", mae_pts=mae_pts,
                pnl_pts=(exit_price - entry_price) * d)
        if target_hit:
            exit_price = target
            return TradeOutcome(
                trigger=t, entry_idx=entry_idx,
                entry_price=entry_price,
                entry_ts_close=entry_ts,
                entry_session=entry_session,
                exit_idx=i, exit_price=exit_price,
                exit_ts_close=ts_closes[i],
                bars_held=i - entry_idx + 1,
                outcome="win", mae_pts=mae_pts,
                pnl_pts=(exit_price - entry_price) * d)
    # Time-out: mark to last_bar's close
    return TradeOutcome(
        trigger=t, entry_idx=entry_idx,
        entry_price=entry_price,
        entry_ts_close=entry_ts,
        entry_session=entry_session,
        exit_idx=last_bar, exit_price=closes[last_bar],
        exit_ts_close=ts_closes[last_bar],
        bars_held=last_bar - entry_idx + 1,
        outcome="timed_out", mae_pts=mae_pts,
        pnl_pts=(closes[last_bar] - entry_price) * d)


# ---------------- Aggregation ----------------

def trades_to_df(outcomes: list[TradeOutcome]) -> pd.DataFrame:
    rows = []
    for o in outcomes:
        t = o.trigger
        # Compute level-pair label (uses mod-100 offsets for readability)
        L_offset = t.breach_level - (int(t.breach_level // HANDLE) * HANDLE)
        Y_offset = t.next_level - (int(t.next_level // HANDLE) * HANDLE)
        # Y_offset of 100 means "00 of next handle"
        if Y_offset == 100.0: Y_offset = 0.0
        pair = (f"{int(L_offset):02d}->{int(Y_offset):02d}_"
                  f"{'long' if t.direction==1 else 'short'}")
        rows.append({
            "trigger_ts_close": pd.Timestamp(t.bar_ts_close),
            "trigger_session": t.bar_session,
            "direction": t.direction,
            "breach_level": t.breach_level,
            "next_level": t.next_level,
            "level_pair": pair,
            "target": t.target,
            "stop": t.stop,
            "midpoint": t.midpoint,
            "close_at_breach": t.close_at_breach,
            "entry_idx": o.entry_idx,
            "entry_price": o.entry_price,
            "entry_ts_close": pd.Timestamp(o.entry_ts_close),
            "entry_session": o.entry_session,
            "exit_idx": o.exit_idx,
            "exit_price": o.exit_price,
            "exit_ts_close": pd.Timestamp(o.exit_ts_close),
            "bars_held": o.bars_held,
            "outcome": o.outcome,
            "mae_pts": o.mae_pts,
            "pnl_pts": o.pnl_pts,
        })
    return pd.DataFrame(rows)


def aggregate_stats(trades: pd.DataFrame) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0}
    n_win = int((trades["outcome"] == "win").sum())
    n_loss = int((trades["outcome"] == "loss").sum())
    n_to = int((trades["outcome"] == "timed_out").sum())
    n_to_pos = int(((trades["outcome"] == "timed_out") &
                       (trades["pnl_pts"] > 0)).sum())
    n_to_neg = int(((trades["outcome"] == "timed_out") &
                       (trades["pnl_pts"] < 0)).sum())
    avg_time_to_target = (trades.loc[
        trades["outcome"] == "win", "bars_held"].mean()
        if n_win else float("nan"))
    return {
        "n": n,
        "win_rate": n_win / n,
        "loss_rate": n_loss / n,
        "timed_out_rate": n_to / n,
        "timed_out_positive": n_to_pos,
        "timed_out_negative": n_to_neg,
        "avg_time_to_target_min": avg_time_to_target,
        "mean_pnl_pts": float(trades["pnl_pts"].mean()),
        "median_pnl_pts": float(trades["pnl_pts"].median()),
        "mean_mae_pts_all": float(trades["mae_pts"].mean()),
        "mean_mae_pts_wins": float(
            trades.loc[trades["outcome"] == "win",
                          "mae_pts"].mean())
            if n_win else float("nan"),
        "mean_mae_pts_losses": float(
            trades.loc[trades["outcome"] == "loss",
                          "mae_pts"].mean())
            if n_loss else float("nan"),
    }


def by_pair(trades: pd.DataFrame) -> pd.DataFrame:
    out = []
    for pair, g in trades.groupby("level_pair"):
        s = aggregate_stats(g)
        s["level_pair"] = pair
        out.append(s)
    df = pd.DataFrame(out)
    cols = ["level_pair"] + [c for c in df.columns
                                       if c != "level_pair"]
    return df[cols].sort_values("level_pair")


def by_session(trades: pd.DataFrame) -> pd.DataFrame:
    out = []
    for sess, g in trades.groupby("entry_session"):
        s = aggregate_stats(g)
        s["entry_session"] = sess
        out.append(s)
    df = pd.DataFrame(out)
    cols = ["entry_session"] + [c for c in df.columns
                                          if c != "entry_session"]
    return df[cols]


def by_pair_and_session(trades: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (pair, sess), g in trades.groupby(
            ["level_pair", "entry_session"]):
        s = aggregate_stats(g)
        s["level_pair"] = pair
        s["entry_session"] = sess
        out.append(s)
    df = pd.DataFrame(out)
    cols = ["level_pair", "entry_session"] + [
        c for c in df.columns
        if c not in ("level_pair", "entry_session")]
    return df[cols].sort_values(["level_pair", "entry_session"])
