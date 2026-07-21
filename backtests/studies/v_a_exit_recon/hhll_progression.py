"""V_A HH/LL Progression Exit Study v1.

Replay structural exit rules using the existing trade tape:
  Family A: exit when no new favorable HH/LL for X bars
            (after pnl > 0 and MFE >= 0.50 ATR)
  Family B: move-to-BE after no new HH/LL for X bars
            (after MFE >= 0.50 ATR)
  Family C: lock partial MFE after no new HH/LL for X bars
            (after MFE >= 1.0 ATR), at 25%/50%/BE of MFE

Granularities: 1s, 5s (aggregated causally from tape), 30s.

Inputs: trade tape from with_tape/NQ_<year>/. No new NT runs.

Outputs:
  - HHLL_PROGRESSION_REPORT.md
  - per-rule per-trade parquets
  - stall-distribution diagnostics
"""

from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

CT = pytz.timezone("America/Chicago")
PORT = Path("collectors/collector_v2/results/with_tape")
OUT = Path("studies/v_a_exit_recon/results")
OUT.mkdir(parents=True, exist_ok=True)

NQ_MULT = 20.0
COST_RT = 10.0
YEARS = [2024, 2025, 2026]


# ---------------- Format helpers ----------------
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


def max_dd(s):
    if len(s) == 0: return 0.0
    cum = pd.Series(s).cumsum().values
    peak = np.maximum.accumulate(cum)
    return float((cum - peak).min())


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


# ---------------- Tape loading + progression compute ----------------
def load_3_years() -> tuple[pd.DataFrame, pd.DataFrame]:
    all_trades = []; all_tape = []
    for yr in YEARS:
        d = PORT / f"NQ_{yr}"
        trades = pd.read_parquet(d / "trades.parquet")
        tape = pd.read_parquet(d / "trade_tape.parquet")
        rth = trades[trades["session"] == "RTH"].copy()
        rth_ids = set(rth["decision_event_id"])
        tape_rth = tape[
            tape["decision_event_id"].isin(rth_ids)].copy()
        OFFSET = yr * 1_000_000
        rth["trade_id"] = rth["decision_event_id"] + OFFSET
        tape_rth["trade_id"] = (
            tape_rth["decision_event_id"] + OFFSET)
        rth["baseline_net_pnl"] = rth["net_pnl"]
        all_trades.append(rth)
        all_tape.append(tape_rth)
        print(f"  NQ {yr}: {len(rth):,} RTH trades, "
              f"{len(tape_rth):,} tape rows")
    trades = pd.concat(all_trades, ignore_index=True)
    tape = pd.concat(all_tape, ignore_index=True)
    return trades, tape


def precompute_progression(tape: pd.DataFrame) -> pd.DataFrame:
    """Per trade, compute:
      - bars_since_new_1s_extreme  (1s row count since mfe last increased)
      - 5s aggregation: per-tape-row bars_since_new_5s_extreme
        based on completed 5s buckets [0..B-1] when row is in bucket B
      - 30s aggregation: same with 30s buckets

    Note for 5s/30s: a "bar" is a completed bucket. The metric at
    row in bucket B reflects how many completed buckets B-1, B-2,
    ... have NOT made a new favorable extreme since the last one
    that did.
    """
    tape = tape.sort_values(
        ["trade_id", "ts_init"]).reset_index(drop=True)

    # 1s: bars since new MFE
    # mfe_pts is monotone non-decreasing per trade. New extreme
    # iff mfe diff > 0.
    tape["mfe_diff"] = (tape.groupby("trade_id",
                                          sort=False)["mfe_pts"]
                          .diff().fillna(tape["mfe_pts"]))
    is_new_1s = (tape["mfe_diff"] > 0).astype(int)
    # bars since new 1s extreme: 0 on the row that made it,
    # increment otherwise within the trade group
    # group-cumsum of (1 - is_new) but reset at each True
    def bars_since(g):
        # g is bool array (1 = new extreme)
        # output: bars since most recent True (0 on True itself)
        out = np.empty(len(g), dtype=np.int32)
        cnt = -1
        for i, b in enumerate(g):
            if b:
                cnt = 0
            else:
                cnt = cnt + 1 if cnt >= 0 else 0
            out[i] = cnt
        return out
    bs1 = (
        is_new_1s.groupby(tape["trade_id"], sort=False)
        .transform(bars_since))
    tape["bars_since_new_1s"] = bs1.values

    # 5s and 30s: bucket-based progression
    for tf in (5, 30):
        bucket_col = f"bucket_{tf}s"
        tape[bucket_col] = (tape["elapsed_s"] // tf).astype(int)

        # Per (trade_id, bucket): compute bucket extreme
        # For long: bucket_extreme = max(h); for short: min(l).
        # Use direction column.
        d = tape["direction"].values
        h = tape["h"].values; l = tape["l"].values
        # For each row use h if direction==1 else l (then max or
        # min determined by direction)
        tape["_fav_price"] = np.where(d == 1, h, l)

        # Per-bucket extreme price: groupby (trade_id, bucket)
        grp = tape.groupby(["trade_id", bucket_col], sort=False)
        # For longs we want max, for shorts min. Since direction
        # is constant per trade, we can split — but simpler to
        # use signed price and take max.
        signed = tape["_fav_price"] * d
        tape["_signed_fav"] = signed
        bucket_max_signed = grp["_signed_fav"].transform("max")
        # Convert back to actual extreme price
        tape["bucket_extreme_signed"] = bucket_max_signed
        # Now for each (trade, bucket), reduce to one row to
        # compute bars_since_new bucket-level metric
        bucket_df = (
            tape.groupby(["trade_id", bucket_col], sort=False)
            .agg(bucket_extreme_signed=(
                "bucket_extreme_signed", "max"),
                 bucket_close_ts=("ts_init", "max"),
                 direction=("direction", "first"),
                 atr_at_signal=("atr_at_signal", "first"))
            .reset_index())
        # Per trade, expanding max of bucket_extreme_signed
        bucket_df = bucket_df.sort_values(
            ["trade_id", bucket_col]).reset_index(drop=True)
        bucket_df["bucket_cummax"] = (
            bucket_df.groupby("trade_id", sort=False)
            ["bucket_extreme_signed"].cummax())
        # is_new bucket extreme = bucket extreme > prior cummax
        bucket_df["prev_cummax"] = (
            bucket_df.groupby("trade_id", sort=False)
            ["bucket_cummax"].shift(1))
        bucket_df["is_new_bucket_extreme"] = (
            bucket_df["bucket_extreme_signed"]
            > bucket_df["prev_cummax"].fillna(-np.inf)).astype(int)
        # bars_since_new for buckets
        bs_buckets = (
            bucket_df["is_new_bucket_extreme"]
            .groupby(bucket_df["trade_id"], sort=False)
            .transform(bars_since))
        bucket_df[f"bars_since_new_{tf}s_buckets"] = bs_buckets.values

        # Now for each tape row in bucket B, the structural
        # state (using completed buckets) is from bucket B-1.
        # Build a lookup: (trade_id, bucket B) -> bars_since at B-1
        bucket_df["next_bucket"] = bucket_df[bucket_col] + 1
        lookup = bucket_df[
            ["trade_id", "next_bucket",
             f"bars_since_new_{tf}s_buckets"]].rename(
                 columns={"next_bucket": bucket_col})
        tape = tape.merge(
            lookup, on=["trade_id", bucket_col], how="left")
        tape[f"bars_since_new_{tf}s_buckets"] = (
            tape[f"bars_since_new_{tf}s_buckets"]
            .fillna(-1).astype(int))
        # -1 = no completed bucket yet (in first bucket B=0)

    # Cleanup helper cols
    tape = tape.drop(columns=["_fav_price", "_signed_fav",
                                  "mfe_diff",
                                  "bucket_extreme_signed"],
                       errors="ignore")
    return tape


# ---------------- Replay rule families ----------------
def _finalize(t, exit_px, exit_ts, reason, fired_rule):
    d = int(t["direction"])
    ep = float(t["fill_price"])
    gross = (exit_px - ep) * d * NQ_MULT
    net = gross - COST_RT
    return {
        "trade_id": int(t.get("trade_id",
                                  t.get("decision_event_id", -1))),
        "year": int(pd.Timestamp(int(t["entry_ts"]),
                                       tz="UTC").tz_convert(CT).year),
        "entry_ts": int(t["entry_ts"]),
        "exit_ts": int(exit_ts),
        "fill_price": float(ep),
        "exit_price": float(exit_px),
        "direction": d,
        "atr_at_signal": float(t["atr_at_signal"]),
        "gross_pnl": float(gross),
        "net_pnl": float(net),
        "hold_s": (exit_ts - int(t["entry_ts"])) / 1e9,
        "exit_reason": reason,
        "fired_rule": bool(fired_rule),
        "baseline_net_pnl": float(t["baseline_net_pnl"]),
    }


def _use_original(t):
    return _finalize(t, float(t["exit_price"]),
                       int(t["exit_ts"]), "regime",
                       fired_rule=False)


def replay_family_a(trades, tape, granularity_col: str,
                       stall_bars: int,
                       min_mfe_atr: float = 0.5) -> pd.DataFrame:
    """Family A: exit when pnl > 0 AND MFE >= min_mfe_atr * atr
    AND stall counter >= stall_bars. Otherwise regime exit."""
    out = []
    tape_groups = tape.groupby("trade_id", sort=False)
    for _, t in trades.iterrows():
        ev = int(t["trade_id"])
        if ev not in tape_groups.groups:
            out.append(_use_original(t))
            continue
        g = tape_groups.get_group(ev)
        atr = float(t["atr_at_signal"])
        min_mfe_pts = min_mfe_atr * atr
        # Find first row where conditions trigger
        cond = ((g["pnl_pts"] > 0)
                & (g["mfe_pts"] >= min_mfe_pts)
                & (g[granularity_col] >= stall_bars))
        if not cond.any():
            out.append(_use_original(t)); continue
        row = g[cond].iloc[0]
        out.append(_finalize(t, float(row["c"]),
                                  int(row["ts_init"]),
                                  f"A_stall_{granularity_col}_{stall_bars}",
                                  fired_rule=True))
    return pd.DataFrame(out)


def replay_family_b(trades, tape, granularity_col: str,
                       stall_bars: int,
                       min_mfe_atr: float = 0.5) -> pd.DataFrame:
    """Family B: after MFE >= min_mfe_atr * atr AND stall >= bars,
    arm BE stop. Exit at entry price if price retraces to entry.
    Otherwise regime exit."""
    out = []
    tape_groups = tape.groupby("trade_id", sort=False)
    for _, t in trades.iterrows():
        ev = int(t["trade_id"])
        if ev not in tape_groups.groups:
            out.append(_use_original(t)); continue
        g = tape_groups.get_group(ev)
        ep = float(t["fill_price"])
        d = int(t["direction"])
        atr = float(t["atr_at_signal"])
        min_mfe_pts = min_mfe_atr * atr
        # Arm condition
        arm_cond = ((g["mfe_pts"] >= min_mfe_pts)
                    & (g[granularity_col] >= stall_bars))
        if not arm_cond.any():
            out.append(_use_original(t)); continue
        arm_idx = g.index[arm_cond.values][0]
        # After arm, exit if low (long) <= ep or high (short) >= ep
        post = g.loc[arm_idx:]
        if d == 1:
            hit = post["l"] <= ep
        else:
            hit = post["h"] >= ep
        if not hit.any():
            out.append(_use_original(t)); continue
        hit_row = post[hit].iloc[0]
        out.append(_finalize(t, float(ep),
                                  int(hit_row["ts_init"]),
                                  f"B_be_{granularity_col}_{stall_bars}",
                                  fired_rule=True))
    return pd.DataFrame(out)


def replay_family_c(trades, tape, granularity_col: str,
                       stall_bars: int, lock_pct: float,
                       min_mfe_atr: float = 1.0) -> pd.DataFrame:
    """DEPRECATED — IDEALIZED, NON-EXECUTABLE replay. Credits fills
    at protect_px regardless of whether protect_px was within the
    bar's OHLC at exit_ts. This produces phantom edge.

    See `replay_family_c_safe` (uses utils/safe_replay framework).

    Retained ONLY for diagnostic comparison vs the safe version.
    Do NOT report results from this function as tradable economics.
    """
    import warnings
    warnings.warn(
        "replay_family_c is IDEALIZED — fills at protect_px even "
        "when not in bar OHLC. Use replay_family_c_safe for "
        "tradable economics.",
        DeprecationWarning, stacklevel=2)
    out = []
    tape_groups = tape.groupby("trade_id", sort=False)
    for _, t in trades.iterrows():
        ev = int(t["trade_id"])
        if ev not in tape_groups.groups:
            out.append(_use_original(t)); continue
        g = tape_groups.get_group(ev)
        ep = float(t["fill_price"])
        d = int(t["direction"])
        atr = float(t["atr_at_signal"])
        min_mfe_pts = min_mfe_atr * atr
        arm_cond = ((g["mfe_pts"] >= min_mfe_pts)
                    & (g[granularity_col] >= stall_bars))
        if not arm_cond.any():
            out.append(_use_original(t)); continue
        arm_idx = g.index[arm_cond.values][0]
        mfe_at_arm = float(g.loc[arm_idx, "mfe_pts"])
        protect_offset = lock_pct * mfe_at_arm
        if d == 1:
            protect_px = ep + protect_offset
            post = g.loc[arm_idx:]
            hit = post["l"] <= protect_px
        else:
            protect_px = ep - protect_offset
            post = g.loc[arm_idx:]
            hit = post["h"] >= protect_px
        if not hit.any():
            out.append(_use_original(t)); continue
        hit_row = post[hit].iloc[0]
        out.append(_finalize(t, float(protect_px),
                                  int(hit_row["ts_init"]),
                                  (f"C_lock{int(lock_pct*100)}"
                                   f"_{granularity_col}_{stall_bars}_IDEALIZED"),
                                  fired_rule=True))
    return pd.DataFrame(out)


# ============================================================
# SAFE replay variants — use utils/safe_replay framework
# ============================================================

def _import_safe_replay():
    """Lazy import to avoid circular at module load."""
    import sys
    from pathlib import Path
    project_root = Path(__file__).parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from utils.safe_replay import (
        SafeReplayConfig, FillModel, OHLCConvention,
        InvalidStopPolicy, safe_stop_replay_armed,
        compute_protect_px_from_mfe,
    )
    return (SafeReplayConfig, FillModel, OHLCConvention,
              InvalidStopPolicy, safe_stop_replay_armed,
              compute_protect_px_from_mfe)


def _finalize_safe(t, exit_px, exit_ts, reason, fired_rule,
                       extra: dict = None):
    """Like _finalize but supports extra audit fields."""
    base = _finalize(t, exit_px, exit_ts, reason, fired_rule)
    if extra:
        base.update(extra)
    return base


def replay_family_c_safe(
    trades, tape, granularity_col: str,
    stall_bars: int, lock_pct: float,
    min_mfe_atr: float = 1.0,
    fill_model: str = "conservative_ohlc",
    ohlc_convention: str = "at_or_worse_close",
    invalid_stop_policy: str = "market_exit_now",
) -> pd.DataFrame:
    """Family C with safe replay. After MFE >= min_mfe_atr*ATR AND
    stall >= bars: arm at lock_pct * MFE_at_arm protect level. The
    framework validates the stop at arm time AND checks each bar's
    OHLC for fill feasibility.

    Defaults:
      fill_model = conservative_ohlc
      ohlc_convention = at_or_worse_close
      invalid_stop_policy = market_exit_now (live-realistic)

    For trades where stop is invalid at arm, default policy issues
    a MARKET exit at the arm bar's close (matches what a real
    broker would do).
    """
    (SafeReplayConfig, FillModel, OHLCConvention,
       InvalidStopPolicy, safe_stop_replay_armed,
       compute_protect_px_from_mfe) = _import_safe_replay()

    cfg = SafeReplayConfig(
        fill_model=fill_model,
        ohlc_convention=ohlc_convention,
        invalid_stop_policy=invalid_stop_policy)

    out = []
    tape_groups = tape.groupby("trade_id", sort=False)
    for _, t in trades.iterrows():
        ev = int(t["trade_id"])
        if ev not in tape_groups.groups:
            out.append(_use_original(t)); continue
        g = tape_groups.get_group(ev).reset_index(drop=True)
        ep = float(t["fill_price"])
        d = int(t["direction"])
        atr = float(t["atr_at_signal"])
        min_mfe_pts = min_mfe_atr * atr
        arm_cond = ((g["mfe_pts"] >= min_mfe_pts)
                    & (g[granularity_col] >= stall_bars))
        if not arm_cond.any():
            out.append(_use_original(t)); continue
        arm_idx = int(arm_cond.idxmax())
        arm_row = g.loc[arm_idx]
        mfe_at_arm = float(arm_row["mfe_pts"])
        # Compute protect_px (raw + tick-rounded)
        _, protect_px = compute_protect_px_from_mfe(
            entry_price=ep, direction=d,
            mfe_pts=mfe_at_arm, lock_pct=lock_pct)
        # Build bars_after_arm list
        bars_after = []
        for i in range(arm_idx + 1, len(g)):
            r = g.loc[i]
            bars_after.append({
                "ts_init": int(r["ts_init"]),
                "h": float(r["h"]),
                "l": float(r["l"]),
                "c": float(r["c"]),
            })
        outcome = safe_stop_replay_armed(
            direction=d, stop_px=protect_px,
            arm_ts=int(arm_row["ts_init"]),
            arm_bar_high=float(arm_row["h"]),
            arm_bar_low=float(arm_row["l"]),
            arm_bar_close=float(arm_row["c"]),
            bars_after_arm=bars_after,
            config=cfg)
        # Translate outcome → trade record
        if not outcome.fired:
            # Either skipped (skip policy) or never crossed (regime
            # fallback) — use original regime exit
            extra = {
                "hhll_arm_ts_replay": int(arm_row["ts_init"]),
                "hhll_protect_px_replay": float(protect_px),
                "hhll_mfe_at_arm_replay": float(mfe_at_arm),
                "hhll_stop_invalid_at_arm": (
                    bool(outcome.stop_invalid_at_arm)),
                "hhll_invalid_reason": outcome.invalid_reason,
                "hhll_safe_fired_via": outcome.fired_via,
            }
            row = _finalize_safe(
                t, float(t["exit_price"]),
                int(t["exit_ts"]),
                f"C_safe_lock{int(lock_pct*100)}_"
                f"{granularity_col}_{stall_bars}_regime",
                fired_rule=False, extra=extra)
            out.append(row); continue
        # Fired
        reason_tag = (
            f"C_safe_lock{int(lock_pct*100)}_"
            f"{granularity_col}_{stall_bars}_"
            f"{outcome.fired_via}")
        extra = {
            "hhll_arm_ts_replay": int(arm_row["ts_init"]),
            "hhll_protect_px_replay": float(protect_px),
            "hhll_mfe_at_arm_replay": float(mfe_at_arm),
            "hhll_stop_invalid_at_arm": (
                bool(outcome.stop_invalid_at_arm)),
            "hhll_invalid_reason": outcome.invalid_reason,
            "hhll_safe_fired_via": outcome.fired_via,
            "hhll_fill_outside_arm_bar_ohlc": (
                bool(outcome.fill_outside_arm_bar_ohlc)),
        }
        row = _finalize_safe(
            t, outcome.fill_px, outcome.fill_ts,
            reason_tag, fired_rule=True, extra=extra)
        out.append(row)
    return pd.DataFrame(out)


def replay_family_b_safe(
    trades, tape, granularity_col: str,
    stall_bars: int, min_mfe_atr: float = 0.5,
    fill_model: str = "conservative_ohlc",
    ohlc_convention: str = "at_or_worse_close",
    invalid_stop_policy: str = "market_exit_now",
) -> pd.DataFrame:
    """Family B with safe replay. Move stop to BE (entry price)
    after stall conditions met. Same safe-replay treatment as
    family_c_safe (validates BE level at arm; if price has already
    retraced past entry, stop is invalid → market exit by default)."""
    (SafeReplayConfig, FillModel, OHLCConvention,
       InvalidStopPolicy, safe_stop_replay_armed,
       compute_protect_px_from_mfe) = _import_safe_replay()

    cfg = SafeReplayConfig(
        fill_model=fill_model,
        ohlc_convention=ohlc_convention,
        invalid_stop_policy=invalid_stop_policy)

    out = []
    tape_groups = tape.groupby("trade_id", sort=False)
    for _, t in trades.iterrows():
        ev = int(t["trade_id"])
        if ev not in tape_groups.groups:
            out.append(_use_original(t)); continue
        g = tape_groups.get_group(ev).reset_index(drop=True)
        ep = float(t["fill_price"])
        d = int(t["direction"])
        atr = float(t["atr_at_signal"])
        min_mfe_pts = min_mfe_atr * atr
        arm_cond = ((g["mfe_pts"] >= min_mfe_pts)
                    & (g[granularity_col] >= stall_bars))
        if not arm_cond.any():
            out.append(_use_original(t)); continue
        arm_idx = int(arm_cond.idxmax())
        arm_row = g.loc[arm_idx]
        # Stop is at break-even = entry price
        protect_px = ep
        bars_after = []
        for i in range(arm_idx + 1, len(g)):
            r = g.loc[i]
            bars_after.append({
                "ts_init": int(r["ts_init"]),
                "h": float(r["h"]),
                "l": float(r["l"]),
                "c": float(r["c"]),
            })
        outcome = safe_stop_replay_armed(
            direction=d, stop_px=protect_px,
            arm_ts=int(arm_row["ts_init"]),
            arm_bar_high=float(arm_row["h"]),
            arm_bar_low=float(arm_row["l"]),
            arm_bar_close=float(arm_row["c"]),
            bars_after_arm=bars_after,
            config=cfg)
        extra = {
            "hhll_arm_ts_replay": int(arm_row["ts_init"]),
            "hhll_protect_px_replay": float(protect_px),
            "hhll_stop_invalid_at_arm": (
                bool(outcome.stop_invalid_at_arm)),
            "hhll_invalid_reason": outcome.invalid_reason,
            "hhll_safe_fired_via": outcome.fired_via,
        }
        if not outcome.fired:
            row = _finalize_safe(
                t, float(t["exit_price"]), int(t["exit_ts"]),
                f"B_safe_be_{granularity_col}_{stall_bars}_regime",
                fired_rule=False, extra=extra)
        else:
            row = _finalize_safe(
                t, outcome.fill_px, outcome.fill_ts,
                f"B_safe_be_{granularity_col}_{stall_bars}_"
                f"{outcome.fired_via}",
                fired_rule=True, extra=extra)
        out.append(row)
    return pd.DataFrame(out)


# ---------------- Diagnostics ----------------
def stall_distribution_per_trade(tape: pd.DataFrame,
                                       granularity_col: str
                                       ) -> pd.DataFrame:
    """Per trade: max stall, stall at exit (last row), and a
    handful of percentiles."""
    g = tape.groupby("trade_id", sort=False)
    rows = []
    for tid, sub in g:
        s = sub[granularity_col]
        rows.append({
            "trade_id": int(tid),
            f"max_stall_{granularity_col}": int(s.max()),
            f"final_stall_{granularity_col}": int(s.iloc[-1]),
            f"p90_stall_{granularity_col}": float(s.quantile(0.9)),
        })
    return pd.DataFrame(rows)


def mfe_capture_ratio(rule_df: pd.DataFrame,
                          tape: pd.DataFrame) -> float:
    """Per trade: rule_pnl_pts / max_mfe_pts. Average across
    trades that had MFE > 0."""
    # Use mfe_pts max per trade from tape
    max_mfe = (tape.groupby("trade_id", sort=False)
                 ["mfe_pts"].max()).to_dict()
    ratios = []
    for _, r in rule_df.iterrows():
        m = max_mfe.get(int(r["trade_id"]), 0.0)
        if m <= 0: continue
        d = int(r["direction"])
        atr = float(r["atr_at_signal"])
        # rule pnl in points
        rule_pnl_pts = (
            float(r["exit_price"]) - float(r["fill_price"])) * d
        ratios.append(rule_pnl_pts / m)
    if not ratios: return float("nan")
    return float(np.mean(ratios))


def per_year_summary(rule: str, df: pd.DataFrame,
                          tape: pd.DataFrame) -> dict:
    out = {"rule": rule}
    for yr in YEARS:
        sub = df[df["year"] == yr]
        s = stats(sub["net_pnl"])
        out[f"y{yr}_n"] = s.get("n", 0)
        out[f"y{yr}_mean"] = s.get("mean")
        out[f"y{yr}_pf"] = s.get("pf")
        out[f"y{yr}_total"] = s.get("sum")
        out[f"y{yr}_dd"] = s.get("max_dd")
        out[f"y{yr}_wr"] = s.get("wr")
        out[f"y{yr}_avg_win"] = s.get("avg_win")
        out[f"y{yr}_avg_loss"] = s.get("avg_loss")
    s_all = stats(df["net_pnl"])
    out["all_n"] = s_all.get("n", 0)
    out["all_mean"] = s_all.get("mean")
    out["all_pf"] = s_all.get("pf")
    out["all_total"] = s_all.get("sum")
    out["all_dd"] = s_all.get("max_dd")
    out["all_wr"] = s_all.get("wr")
    out["med_hold_s"] = float(df["hold_s"].median())
    out["pct_fired"] = float(df["fired_rule"].mean())
    # Damage / improvement
    diff = df["net_pnl"] - df["baseline_net_pnl"]
    bw = df["baseline_net_pnl"] > 0
    bl = df["baseline_net_pnl"] < 0
    out["pct_baseline_winners_cut"] = float(
        ((diff < 0) & bw).sum() / max(bw.sum(), 1))
    out["pct_baseline_losers_improved"] = float(
        ((diff > 0) & bl).sum() / max(bl.sum(), 1))
    # MFE capture ratio
    out["mfe_capture_ratio"] = mfe_capture_ratio(df, tape)
    # Top-1% share
    s = df["net_pnl"].sort_values(ascending=False)
    top1 = s.head(max(1, int(len(s) * 0.01))).sum()
    total = s.sum()
    out["top1_share"] = (
        float(top1 / total) if total != 0 else float("nan"))
    return out


def main():
    print("Loading 3 years of trades + tape...")
    trades, tape = load_3_years()
    print(f"Total: {len(trades):,} trades, {len(tape):,} tape rows")

    print("\nPre-computing structural progression "
          "(1s/5s/30s)...")
    tape = precompute_progression(tape)
    print(f"Tape now has {len(tape.columns)} columns")

    # ---- Build summaries ----
    rules_summary = []

    # Baseline reference
    baseline_rows = [
        _use_original(t) for _, t in trades.iterrows()
    ]
    base_df = pd.DataFrame(baseline_rows)
    rules_summary.append(per_year_summary("BASELINE_regime",
                                                base_df, tape))
    print("  BASELINE done")

    # E_ltf reference (load existing)
    ref_p = OUT / "trades_E_ltf_deterioration_T600.parquet"
    if ref_p.exists():
        ref = pd.read_parquet(ref_p)
        ts_to_baseline = (
            trades.set_index("entry_ts")["baseline_net_pnl"]
            .to_dict())
        ref["baseline_net_pnl"] = ref["entry_ts"].map(
            ts_to_baseline)
        if "trade_id" not in ref.columns:
            yr_to_offset = {y: y * 1_000_000 for y in YEARS}
            ref["trade_id"] = (
                ref["decision_event_id"]
                + ref["year"].map(yr_to_offset))
        ref["fired_rule"] = (ref["exit_reason"]
                                .str.startswith("E_"))
        rules_summary.append(per_year_summary(
            "REF_E_ltf_deterioration_T600", ref, tape))
        print("  REF E_ltf loaded")

    # Family A, B, C
    granularities = [
        ("bars_since_new_1s", "1s"),
        ("bars_since_new_5s_buckets", "5s"),
        ("bars_since_new_30s_buckets", "30s"),
    ]

    a_stalls = [5, 10, 20, 30]
    b_stalls = {"5s": [5, 10, 20], "30s": [2, 3, 5]}
    c_stalls = {"5s": [5, 10, 20], "30s": [2, 3, 5]}
    c_lock_pcts = [0.0, 0.25, 0.50]

    # Family A: all 3 granularities × 4 stalls = 12 variants
    print("\nReplaying Family A (no-new-HHLL exit)...")
    for col, label in granularities:
        for stall in a_stalls:
            name = f"A_stall_{label}_{stall}"
            df = replay_family_a(trades, tape, col, stall)
            df.to_parquet(OUT / f"trades_{name}.parquet",
                            index=False)
            rules_summary.append(per_year_summary(
                name, df, tape))
            print(f"  {name}: fired {df['fired_rule'].sum():,}")

    # Family B: 5s and 30s × 3 stalls each = 6 variants
    print("\nReplaying Family B (move to BE after stall)...")
    for col, label in granularities[1:]:
        for stall in b_stalls[label]:
            name = f"B_be_{label}_{stall}"
            df = replay_family_b(trades, tape, col, stall)
            df.to_parquet(OUT / f"trades_{name}.parquet",
                            index=False)
            rules_summary.append(per_year_summary(
                name, df, tape))
            print(f"  {name}: fired {df['fired_rule'].sum():,}")

    # Family C: 5s and 30s × 3 stalls × 3 lock_pct = 18 variants
    print("\nReplaying Family C (lock partial MFE after stall)...")
    for col, label in granularities[1:]:
        for stall in c_stalls[label]:
            for lock in c_lock_pcts:
                name = f"C_lock{int(lock*100)}_{label}_{stall}"
                df = replay_family_c(trades, tape, col, stall,
                                            lock)
                df.to_parquet(OUT / f"trades_{name}.parquet",
                                index=False)
                rules_summary.append(per_year_summary(
                    name, df, tape))
                print(f"  {name}: fired {df['fired_rule'].sum():,}")

    summ = pd.DataFrame(rules_summary)
    summ.to_parquet(OUT / "hhll_progression_summary.parquet",
                       index=False)

    # Stall distribution diagnostics
    print("\nComputing stall distribution diagnostics...")
    diag_rows = []
    base_pnl = trades.set_index("trade_id")[
        "baseline_net_pnl"].to_dict()
    for col, label in granularities:
        # Per-trade max stall and final stall
        sd = (tape.groupby("trade_id", sort=False)
                  .agg(max_stall=(col, "max"),
                       final_stall=(col, "last"))
                  .reset_index())
        sd["baseline_net_pnl"] = sd["trade_id"].map(base_pnl)
        sd["winner"] = sd["baseline_net_pnl"] > 0
        sd["year"] = sd["trade_id"] // 1_000_000
        for yr in YEARS:
            sub = sd[sd["year"] == yr]
            for win_label, mask in [
                ("winner", sub["winner"]),
                ("loser", ~sub["winner"]),
            ]:
                sub_w = sub[mask]
                if not len(sub_w): continue
                diag_rows.append({
                    "granularity": label,
                    "year": int(yr),
                    "cohort": win_label,
                    "n": len(sub_w),
                    "median_max_stall": float(
                        sub_w["max_stall"].median()),
                    "p75_max_stall": float(
                        sub_w["max_stall"].quantile(0.75)),
                    "p90_max_stall": float(
                        sub_w["max_stall"].quantile(0.90)),
                    "median_final_stall": float(
                        sub_w["final_stall"].median()),
                })
    diag_df = pd.DataFrame(diag_rows)
    diag_df.to_parquet(OUT / "stall_distributions.parquet",
                          index=False)

    # ---------------- Markdown report ----------------
    lines = []
    lines.append("# V_A HH/LL Progression Exit Study v1")
    lines.append("")
    lines.append("Tests 3 mechanical exit families using "
                 "structural HH/LL progression at 1s/5s/30s "
                 "granularities. All replayed from the existing "
                 "trade tape — no new NT runs.")
    lines.append("")
    lines.append(f"- Population: {len(trades):,} unfiltered V_A "
                  "trades (NQ 2024+2025+2026 RTH)")
    lines.append(f"- Tape: {len(tape):,} per-1s-bar rows")
    lines.append("- Cost: $5 commission + $5 tick = $10 RT")
    lines.append("- Each rule re-uses the SAME entry. Only exit "
                  "logic changes.")
    lines.append("")

    # ---- Rule scoreboard ----
    lines.append("## Rule scoreboard — full per-year stats")
    lines.append("")
    lines.append("| Rule | %fired | Med Hold s | "
                 "2024 mean / total / WR | "
                 "2025 mean / total / WR | "
                 "2026 mean / total / WR | "
                 "All mean | All total | All PF | "
                 "%base-W cut | %base-L improved | "
                 "MFE capt | Top-1% share |")
    lines.append("|" + "|".join(["---"] * 13) + "|")
    for r in rules_summary:
        lines.append(
            f"| {r['rule']} | {fmt_p(r.get('pct_fired', 0))} | "
            f"{r['med_hold_s']:.0f} | "
            f"{fmt_d(r.get('y2024_mean'))} / "
            f"{fmt_d(r.get('y2024_total'))} / "
            f"{fmt_p(r.get('y2024_wr'))} | "
            f"{fmt_d(r.get('y2025_mean'))} / "
            f"{fmt_d(r.get('y2025_total'))} / "
            f"{fmt_p(r.get('y2025_wr'))} | "
            f"{fmt_d(r.get('y2026_mean'))} / "
            f"{fmt_d(r.get('y2026_total'))} / "
            f"{fmt_p(r.get('y2026_wr'))} | "
            f"{fmt_d(r['all_mean'])} | "
            f"{fmt_d(r['all_total'])} | "
            f"{fmt_pf(r['all_pf'])} | "
            f"{fmt_p(r.get('pct_baseline_winners_cut', 0))} | "
            f"{fmt_p(r.get('pct_baseline_losers_improved', 0))} | "
            f"{fmt_pf(r.get('mfe_capture_ratio'))} | "
            f"{fmt_p(r.get('top1_share', 0))} |")
    lines.append("")

    # ---- Δ vs baseline ----
    base = next(r for r in rules_summary
                  if r["rule"] == "BASELINE_regime")
    lines.append("## Δ vs baseline regime exit")
    lines.append("")
    lines.append("| Rule | Δ 2024 | Δ 2025 | Δ 2026 | "
                 "Δ All mean | Δ All total |")
    lines.append("|---|--:|--:|--:|--:|--:|")
    for r in rules_summary:
        if r["rule"] == "BASELINE_regime": continue
        d24 = r["y2024_mean"] - base["y2024_mean"]
        d25 = r["y2025_mean"] - base["y2025_mean"]
        d26 = r["y2026_mean"] - base["y2026_mean"]
        dall = r["all_mean"] - base["all_mean"]
        dtot = r["all_total"] - base["all_total"]
        lines.append(
            f"| {r['rule']} | {fmt_d(d24)} | {fmt_d(d25)} | "
            f"{fmt_d(d26)} | {fmt_d(dall)} | {fmt_d(dtot)} |")
    lines.append("")

    # ---- Years positive ----
    lines.append("## Years positive per rule")
    lines.append("")
    lines.append("| Rule | Yrs +mean | 2024 ✓? | 2025 ✓? | 2026 ✓? |")
    lines.append("|---|--:|---|---|---|")
    for r in rules_summary:
        yrs_pos = sum(1 for yr in YEARS
                          if r.get(f"y{yr}_mean") is not None
                          and r[f"y{yr}_mean"] > 0)
        marks = ["✅" if r.get(f"y{yr}_mean", 0) > 0 else "❌"
                  for yr in YEARS]
        lines.append(f"| {r['rule']} | {yrs_pos}/3 | "
                      + " | ".join(marks) + " |")
    lines.append("")

    # ---- Stall distribution diagnostics ----
    lines.append("## Stall-distribution diagnostics — winners "
                 "vs losers")
    lines.append("")
    lines.append("| Granularity | Year | Cohort | n | "
                 "Med max stall | p75 | p90 | Med final stall |")
    lines.append("|---|--:|---|--:|--:|--:|--:|--:|")
    for _, r in diag_df.iterrows():
        lines.append(
            f"| {r['granularity']} | {r['year']} | "
            f"{r['cohort']} | {r['n']:,} | "
            f"{r['median_max_stall']:.0f} | "
            f"{r['p75_max_stall']:.0f} | "
            f"{r['p90_max_stall']:.0f} | "
            f"{r['median_final_stall']:.0f} |")
    lines.append("")

    out_p = OUT / "HHLL_PROGRESSION_REPORT.md"
    out_p.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_p}")


if __name__ == "__main__":
    main()
