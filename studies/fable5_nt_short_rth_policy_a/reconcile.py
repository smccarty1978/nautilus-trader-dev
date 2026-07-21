"""Reconciliation + parity gate for NT event-driven W4 short-RTH Policy A.

Addresses the pre-execution CRITICAL: the live RegimeEngine that drives every
Policy A exit is fed from the catalog, while the frozen entry schedule and the
offline benchmark were built from raw. This module fail-fast verifies that the
live NT 1m flip stream matches the offline raw-fed canonical regime timeline
(the same builder the offline study used), and reconciles each NT trade's live
alignment timestamp against the frozen recon_confirm_flip_ns. It then produces
the trade-level reconciliation, exit-reason distribution, both drawdown types,
monthly breakdown, and the benchmark comparison.

Quarterly-roll windows (memory: NQ catalog vs raw can diverge 100-250pt at
rolls) are annotated; a flip mismatch OUTSIDE a roll window is BLOCKING.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import common as C

_ROOT = C.ROOT
for p in (_ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair",
          _ROOT / "studies" / "regime_sequence_chop_context"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from CODEX_5_X_common import RAW_1S  # noqa: E402
from CODEX_5_X_run_established_fade import canonical_regime_timeline  # noqa: E402

ISOLATION = (_ROOT / "studies" / "codex_5_w4_fade_confirmation_clock_isolation"
             / "results" / "isolation_trade_diffs.parquet")
POLICY_A_ID = "POLICY_A_COMBINED_1P25_300S"
NS = C.NS_PER_S

# NT exit reason -> offline Policy A exit reason
REASON_MAP = {
    "stop_before_flip": "preflip_policy_stop",
    "stop_after_flip": "original_stop_after_aligned_flip",
    "confirmation_timeout": "confirmation_timeout_exit",
    "opposite_flip": "original_opposing_flip_exit",
}


def roll_windows(year: int) -> list[tuple[int, int]]:
    """+/-3 calendar days around the 3rd Friday of Mar/Jun/Sep/Dec."""
    out = []
    for month in (3, 6, 9, 12):
        first = pd.Timestamp(f"{year}-{month:02d}-01", tz="UTC")
        # 3rd Friday
        fridays = [first + pd.Timedelta(days=d) for d in range(31)
                   if (first + pd.Timedelta(days=d)).weekday() == 4
                   and (first + pd.Timedelta(days=d)).month == month]
        third = fridays[2]
        out.append(((third - pd.Timedelta(days=3)).value,
                    (third + pd.Timedelta(days=3)).value))
    return out


def in_roll_window(ts: int, windows: list[tuple[int, int]]) -> bool:
    return any(a <= ts <= b for a, b in windows)


def flip_parity(year: int, nt_flips: pd.DataFrame) -> dict:
    """Fail-fast: live NT catalog flips must match offline raw canonical flips."""
    raw = pd.read_parquet(RAW_1S[year],
                          columns=["open", "high", "low", "close", "volume"])
    timeline = canonical_regime_timeline(year, raw)
    off = timeline[["regime_start_ns", "direction"]].copy()
    off = off.rename(columns={"regime_start_ns": "flip_ts"})
    # canonical_regime_timeline already excludes the warmup-born (0->x)
    # transition via its `previous != 0` filter, and the live NT strategy
    # likewise only logs flip-born transitions (prev!=0 & new!=0). So both
    # streams are flip-born only; do NOT drop any row here.
    off = off.sort_values("flip_ts").reset_index(drop=True)

    lo = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    hi = C.LOAD_WINDOWS[year][1].value
    off = off[(off.flip_ts >= lo) & (off.flip_ts <= hi)]
    nt = nt_flips[(nt_flips.flip_ts >= lo) & (nt_flips.flip_ts <= hi)] \
        if len(nt_flips) else nt_flips

    off_set = set(zip(off.flip_ts.astype("int64"), off.direction.astype(int)))
    nt_set = (set(zip(nt.flip_ts.astype("int64"), nt.direction.astype(int)))
              if len(nt) else set())
    windows = roll_windows(year)
    only_off = off_set - nt_set
    only_nt = nt_set - off_set
    blocking = [(ts, d) for ts, d in (only_off | only_nt)
                if not in_roll_window(ts, windows)]
    return {"year": year, "offline_flips": len(off_set), "nt_flips": len(nt_set),
            "matched": len(off_set & nt_set), "only_offline": len(only_off),
            "only_nt": len(only_nt),
            "mismatch_in_roll_window": len(only_off | only_nt) - len(blocking),
            "blocking_mismatches": len(blocking),
            "blocking_examples": [
                {"flip_ts": int(ts), "direction": int(d),
                 "utc": str(pd.Timestamp(ts, tz="UTC"))}
                for ts, d in sorted(blocking)[:10]]}


def load_nt(year: int) -> pd.DataFrame:
    d = pd.read_parquet(C.WORK / "nt_runs" / str(year) / "trades.parquet")
    return d


def load_offline_short_rth(year: int) -> pd.DataFrame:
    d = pd.read_parquet(ISOLATION)
    d = d[(d.policy_id == POLICY_A_ID) & (d.year == year)
          & (d.trade_direction == "short_fade") & (d.session == "RTH")].copy()
    return d.sort_values("entry_fill_ts").reset_index(drop=True)


def reconcile_trades(year: int, nt: pd.DataFrame,
                     off: pd.DataFrame) -> pd.DataFrame:
    off_by_entry = off.set_index("entry_fill_ts")
    rows = []
    for t in nt.itertuples(index=False):
        entry = int(t.target_fill_ts)
        o = off_by_entry.loc[entry] if entry in off_by_entry.index else None
        has_align = pd.notna(t.align_ts)
        align_delta = (int(t.align_ts) - int(t.recon_confirm_flip_ns)
                       if has_align
                       and int(t.recon_confirm_flip_ns) > 0 else np.nan)
        nt_reason_mapped = REASON_MAP.get(t.exit_reason, t.exit_reason)
        row = {
            "year": year, "nt_trade_id": t.trade_id,
            "entry_fill_ts": entry, "regime_start_ns": int(t.regime_start_ns),
            "nt_entry_px": float(t.entry_px),
            "offline_entry_open": float(t.offline_entry_open),
            "entry_px_delta": float(t.entry_px) - float(t.offline_entry_open),
            "nt_atr": float(t.atr),
            "nt_aligned": bool(t.aligned),
            "nt_align_ts": int(t.align_ts) if has_align else pd.NA,
            "recon_confirm_flip_ns": int(t.recon_confirm_flip_ns),
            "align_ts_delta_ns": align_delta,
            "nt_exit_reason": t.exit_reason,
            "nt_exit_reason_mapped": nt_reason_mapped,
            "nt_exit_ts": int(t.exit_ts) if pd.notna(t.exit_ts) else pd.NA,
            "nt_exit_px": float(t.exit_px) if pd.notna(t.exit_px) else np.nan,
            "nt_net_pnl": float(t.net_pnl) if pd.notna(t.net_pnl) else np.nan,
            "matched_offline": o is not None,
        }
        if o is not None:
            row.update({
                "off_exit_reason": o.new_exit_reason,
                "off_exit_ts": int(o.new_exit_fill_ts),
                "off_exit_px": float(o.new_exit_fill_px),
                "off_net_pnl": float(o.new_net_pnl_usd),
                "off_reached_align": bool(o.reached_aligning_flip),
                "exit_ts_delta_ns": (int(t.exit_ts) - int(o.new_exit_fill_ts)
                                     if pd.notna(t.exit_ts) else np.nan),
                "exit_px_delta": (float(t.exit_px) - float(o.new_exit_fill_px)
                                  if pd.notna(t.exit_px) else np.nan),
                "pnl_delta": (float(t.net_pnl) - float(o.new_net_pnl_usd)
                              if pd.notna(t.net_pnl) else np.nan),
                "reason_match": nt_reason_mapped == o.new_exit_reason,
                "align_match": bool(t.aligned) == bool(o.reached_aligning_flip),
            })
            row["mismatch_bucket"] = classify(row, t, o)
        rows.append(row)
    return pd.DataFrame(rows)


def classify(row: dict, t, o) -> str:
    if abs(row.get("entry_px_delta", 0.0)) > 1e-9:
        base = "entry_fill_mismatch"
    elif not row.get("align_match", True):
        base = "alignment_timing_mismatch"
    elif not row.get("reason_match", True):
        base = "exit_reason_mismatch"
    elif abs(row.get("pnl_delta", 0.0) or 0.0) > 1e-6:
        base = "exit_fill_mismatch"
    else:
        base = "match"
    return base


def drawdowns(pnl: pd.Series) -> float:
    equity = np.concatenate(([0.0], pnl.cumsum().to_numpy(float)))
    return float(np.max(np.maximum.accumulate(equity) - equity))


def econ(nt: pd.DataFrame) -> dict:
    p = nt[nt.net_pnl.notna()]
    pnl = p.net_pnl.astype(float)
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    return {
        "trades": int(len(p)),
        "total_net_pnl": float(pnl.sum()),
        "mean_net_pnl": float(pnl.mean()) if len(pnl) else np.nan,
        "gross_profit": float(wins.sum()), "gross_loss": float(losses.sum()),
        "profit_factor": float(wins.sum() / -losses.sum())
        if losses.sum() < 0 else np.nan,
        "win_rate": float((pnl > 0).mean()) if len(pnl) else np.nan,
        "avg_winner": float(wins.mean()) if len(wins) else np.nan,
        "avg_loser": float(losses.mean()) if len(losses) else np.nan,
        "max_closed_trade_dd": drawdowns(
            p.sort_values("exit_ts").net_pnl.astype(float)),
        "median_hold_s": float(p.hold_s.median()) if "hold_s" in p else np.nan,
        "mean_hold_s": float(p.hold_s.mean()) if "hold_s" in p else np.nan,
        "median_time_to_align_s": float(
            p.time_to_align_s.dropna().median())
        if "time_to_align_s" in p and p.time_to_align_s.notna().any() else np.nan,
        "preflip_stop_rate": float((p.exit_reason == "stop_before_flip").mean()),
        "timeout_rate": float((p.exit_reason == "confirmation_timeout").mean()),
        "postflip_stop_rate": float((p.exit_reason == "stop_after_flip").mean()),
        "opposing_flip_rate": float((p.exit_reason == "opposite_flip").mean()),
        "exit_reason_counts": p.exit_reason.value_counts().to_dict(),
        "exit_reason_pnl": {r: float(g.net_pnl.sum())
                            for r, g in p.groupby("exit_reason")},
    }


def monthly(nt: pd.DataFrame) -> pd.DataFrame:
    p = nt[nt.net_pnl.notna()].copy()
    p["month"] = pd.to_datetime(p.entry_ts, unit="ns", utc=True).dt.to_period("M").astype(str)
    return p.groupby("month").agg(
        trades=("net_pnl", "size"), net_pnl=("net_pnl", "sum")).reset_index()


def tie_detection(nt: pd.DataFrame, preflip_atr: float = C.PREFLIP_STOP_ATR,
                  postflip_atr: float = C.POSTFLIP_STOP_ATR) -> dict:
    """WARNING (event-ordering): a stop touch preempted by a same-boundary
    flip/timeout exit. Measured directly from the intrabar adverse excursion
    (mae_atr, tracked per 1s bar) vs the stop level that was ACTIVE when the
    trade exited, covering BOTH races:

      - post-stop race: an aligned trade exits opposite_flip although its max
        adverse excursion reached the 1.50-ATR post stop (the resting stop
        should normally have filled first);
      - pre-stop race: a not-yet-aligned trade exits confirmation_timeout
        although its max adverse excursion reached the 1.25-ATR pre stop.

    A near-zero count confirms the same-ts_init tie is immaterial. Non-zero
    counts are reported with PnL so the residual is quantified, not hidden.
    """
    p = nt[nt.net_pnl.notna()].copy()
    if not len(p):
        return {"trades": 0, "post_stop_race_flags": 0, "pre_stop_race_flags": 0}
    eps = 1e-9
    post_race = ((p.exit_reason == "opposite_flip") & p.aligned
                 & (p.mae_atr >= postflip_atr - eps))
    pre_race = ((p.exit_reason == "confirmation_timeout") & ~p.aligned
                & (p.mae_atr >= preflip_atr - eps))
    # third sub-case: pre stop breached (>=1.25 ATR) BEFORE alignment, yet the
    # trade aligned instead of stopping out (measured from the alignment-time
    # snapshot, which isolates pre-alignment excursion from the whole-trade max)
    maa = pd.to_numeric(p.get("mae_atr_at_align"), errors="coerce")
    pre_align_race = p.aligned & maa.notna() & (maa >= preflip_atr - eps)
    return {
        "trades": int(len(p)),
        "post_stop_race_flags": int(post_race.sum()),
        "post_stop_race_pnl": float(p.loc[post_race, "net_pnl"].sum()),
        "pre_stop_race_flags": int(pre_race.sum()),
        "pre_stop_race_pnl": float(p.loc[pre_race, "net_pnl"].sum()),
        "pre_align_race_flags": int(pre_align_race.sum()),
        "pre_align_race_pnl": float(p.loc[pre_align_race, "net_pnl"].sum()),
        "max_mae_atr_opposite_flip": float(
            p.loc[p.exit_reason == "opposite_flip", "mae_atr"].max())
        if (p.exit_reason == "opposite_flip").any() else np.nan,
        "max_mae_atr_timeout": float(
            p.loc[p.exit_reason == "confirmation_timeout", "mae_atr"].max())
        if (p.exit_reason == "confirmation_timeout").any() else np.nan,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.parse_args()
    all_recon, all_nt, parity, tie = [], [], {}, {}
    summary = {}
    for year in (2025, 2026):
        nt = load_nt(year)
        flips = pd.read_parquet(C.WORK / "nt_runs" / str(year) / "flips.parquet")
        parity[year] = flip_parity(year, flips)
        off = load_offline_short_rth(year)
        recon = reconcile_trades(year, nt, off)
        all_recon.append(recon)
        all_nt.append(nt)
        tie[year] = tie_detection(nt)
        summary[year] = {"nt": econ(nt),
                         "benchmark": C.BENCHMARK[year],
                         "offline_short_rth_trades": int(len(off))}
        monthly(nt).to_csv(
            C.RESULTS / f"nt_short_rth_policy_a_monthly_{year}.csv", index=False)

    blocking = sum(parity[y]["blocking_mismatches"] for y in (2025, 2026))
    recon_all = pd.concat(all_recon, ignore_index=True)
    nt_all = pd.concat(all_nt, ignore_index=True)
    recon_all.to_parquet(
        C.RESULTS / "nt_short_rth_policy_a_trade_reconciliation.parquet",
        index=False)
    nt_all.to_parquet(C.RESULTS / "nt_short_rth_policy_a_results.parquet",
                      index=False)
    combined = econ(nt_all)
    summary["combined"] = {"nt": combined, "benchmark": C.BENCHMARK["combined"]}
    summary["parity"] = {str(y): parity[y] for y in (2025, 2026)}
    summary["parity"]["blocking_total"] = blocking
    summary["ties"] = {str(y): tie[y] for y in (2025, 2026)}
    summary["mismatch_buckets"] = (
        recon_all.mismatch_bucket.value_counts().to_dict()
        if "mismatch_bucket" in recon_all else {})
    (C.RESULTS / "reconciliation_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")

    print(json.dumps({"parity_blocking": blocking,
                      "combined_trades": combined["trades"],
                      "combined_net_pnl": combined["total_net_pnl"],
                      "combined_pf": combined["profit_factor"],
                      "mismatch_buckets": summary["mismatch_buckets"]}, indent=2))
    if blocking > 0:
        raise SystemExit(
            f"PARITY GATE FAILED: {blocking} live-vs-offline flip mismatches "
            f"outside roll windows. Results not trustworthy — investigate "
            f"catalog/raw divergence before reporting.")


if __name__ == "__main__":
    main()
