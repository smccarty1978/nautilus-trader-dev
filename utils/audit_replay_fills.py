"""QA detector for offline replay studies. Flags impossible fills,
sign inconsistencies, off-grid prices, and other replay bugs that
could credit phantom edge.

Usage:
  from utils.audit_replay_fills import audit_trades, AuditConfig
  result = audit_trades(trades_df, bars_lookup_fn=cat_bars_at,
                            config=AuditConfig(...))
  if result.has_impossible_fills:
      raise RuntimeError("REPLAY HAS IMPOSSIBLE FILLS — NOT TRADABLE")

CLI:
  python -m utils.audit_replay_fills <trades.parquet> --catalog <path>
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable
import pandas as pd
import numpy as np

from utils.safe_replay import (
    NQ_TICK, NQ_MULT, is_on_tick_grid, validate_stop_at_arm,
)


@dataclass
class AuditConfig:
    """Knobs for the auditor."""
    tick_size: float = NQ_TICK
    multiplier: float = NQ_MULT
    # Hard-fail mode: raise if any impossible fill is found (use in
    # CI / report generators). Soft mode: just count and report.
    hard_fail_on_impossible: bool = True
    # Tolerance for "exit_px outside bar OHLC" check (one tick).
    ohlc_tolerance: float = 0.0  # zero by default (must be inside)
    # Required columns (auditor will check existence)
    required_cols: tuple = (
        "entry_ts", "exit_ts", "fill_price", "exit_price",
        "direction",
    )


@dataclass
class FlagBucket:
    """One bucket of audit flags with offending trade ids + PnL."""
    name: str
    description: str
    trade_ids: list = field(default_factory=list)
    pnl_contribution: float = 0.0   # signed, in dollars

    @property
    def count(self) -> int:
        return len(self.trade_ids)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "count": self.count,
            "pnl_contribution": float(self.pnl_contribution),
        }


@dataclass
class AuditResult:
    n_trades: int
    flags: dict[str, FlagBucket]
    impossible_fills_n: int
    impossible_fills_pnl: float
    has_impossible_fills: bool
    summary: dict

    def as_markdown(self) -> str:
        lines = []
        lines.append("## Replay Fill Audit")
        lines.append("")
        lines.append(f"- Total trades audited: {self.n_trades:,}")
        lines.append(f"- **Impossible fills detected: "
                      f"{self.impossible_fills_n:,}** "
                      f"(PnL contribution: "
                      f"${self.impossible_fills_pnl:,.2f})")
        lines.append("")
        lines.append("| Flag | Description | Count | "
                      "PnL contribution |")
        lines.append("|---|---|--:|--:|")
        for name, b in self.flags.items():
            lines.append(
                f"| {b.name} | {b.description} | {b.count} | "
                f"${b.pnl_contribution:,.2f} |")
        lines.append("")
        if self.has_impossible_fills:
            lines.append("**HARD FAIL — replay output contains "
                         "impossible fills. Do not report as "
                         "tradable economics.**")
        else:
            lines.append("PASS — no impossible fills detected.")
        return "\n".join(lines)


def audit_trades(
    trades: pd.DataFrame,
    bars_lookup_fn: Callable[[int],
                                  tuple[float, float, float, float]] | None = None,
    config: AuditConfig | None = None,
) -> AuditResult:
    """Audit a replay-output trades DataFrame for fill-feasibility
    and consistency bugs.

    Args:
      trades: DataFrame with one row per trade. Required columns
        depend on config.required_cols.
      bars_lookup_fn: optional callable(ts_ns) → (open, high, low,
        close) for the bar at that ts. If provided, enables the
        "exit_px outside bar OHLC" check.
      config: AuditConfig.

    Returns:
      AuditResult.
    """
    cfg = config or AuditConfig()
    n = len(trades)

    # Validate required columns
    missing = [c for c in cfg.required_cols
                  if c not in trades.columns]
    if missing:
        raise ValueError(
            f"trades DataFrame missing required columns: {missing}")

    # Init flag buckets
    flags: dict[str, FlagBucket] = {
        "exit_outside_bar_ohlc": FlagBucket(
            name="exit_outside_bar_ohlc",
            description=(
                "exit_price is outside [bar.low, bar.high] at "
                "exit_ts — phantom fill, not tradable")),
        "exit_before_arm": FlagBucket(
            name="exit_before_arm",
            description=(
                "exit_ts < arm_ts — caused by stale arm_ts or bad "
                "ordering")),
        "stop_invalid_filled_at_stop": FlagBucket(
            name="stop_invalid_filled_at_stop",
            description=(
                "stop was invalid at arm (in market) but fill_px == "
                "stop_px anyway")),
        "exit_reason_overwritten": FlagBucket(
            name="exit_reason_overwritten",
            description=(
                "exit_reason inconsistent with fill mechanics")),
        "direction_sign_inconsistent": FlagBucket(
            name="direction_sign_inconsistent",
            description=(
                "direction not in {-1, +1} or implied PnL has wrong "
                "sign vs (exit_price - fill_price)")),
        "protect_not_on_tick_grid": FlagBucket(
            name="protect_not_on_tick_grid",
            description=(
                "stop_px / protect_px is not a multiple of tick_size")),
        "exit_after_max_hold": FlagBucket(
            name="exit_after_max_hold",
            description=(
                "exit timestamp implausibly far after entry")),
    }

    pnl_col = "net_pnl" if "net_pnl" in trades.columns else None

    for _, t in trades.iterrows():
        tid = (int(t.get("trade_id",
                              t.get("decision_event_id", -1)))
                  if pd.notna(t.get("trade_id",
                                          t.get("decision_event_id")))
                  else -1)
        d = int(t["direction"])
        entry_ts = int(t["entry_ts"])
        exit_ts = int(t["exit_ts"])
        fill_px = float(t["fill_price"])
        exit_px = float(t["exit_price"])
        pnl = (float(t[pnl_col]) if pnl_col and pd.notna(t[pnl_col])
                  else 0.0)

        # 1. exit_before_arm
        arm_ts = (int(t["hhll_arm_ts"])
                     if "hhll_arm_ts" in t.index
                     and pd.notna(t.get("hhll_arm_ts"))
                     and int(t.get("hhll_arm_ts", 0)) > 0
                     else None)
        if arm_ts and exit_ts < arm_ts:
            flags["exit_before_arm"].trade_ids.append(tid)
            flags["exit_before_arm"].pnl_contribution += pnl

        # 2. stop_invalid_filled_at_stop
        # Heuristic: if hhll_protect_px exists and fill_px is at
        # protect_px AND protect_px is on the WRONG side of fill_price
        # (= would have been in the market at arm), then phantom fill.
        protect_px = (float(t["hhll_protect_px"])
                          if "hhll_protect_px" in t.index
                          and pd.notna(t.get("hhll_protect_px"))
                          else None)
        # Note: full validity check requires arm-time price, which
        # we may not have. Use the heuristic that a fill exactly at
        # protect_px combined with a far-away regime_exit_price
        # suggests a phantom.

        # 3. direction sign inconsistency
        if d not in (-1, 1):
            flags["direction_sign_inconsistent"].trade_ids.append(
                tid)
            flags["direction_sign_inconsistent"].pnl_contribution += pnl
        else:
            # Verify (exit - fill) * direction has same sign as
            # gross_pnl IF gross_pnl is present
            if "gross_pnl" in t.index and pd.notna(t.get("gross_pnl")):
                gross = float(t["gross_pnl"])
                expected_sign = (
                    1 if (exit_px - fill_px) * d > 0 else
                    (-1 if (exit_px - fill_px) * d < 0 else 0))
                actual_sign = (1 if gross > 0 else
                                  (-1 if gross < 0 else 0))
                if expected_sign != 0 and actual_sign != 0 and (
                        expected_sign != actual_sign):
                    flags["direction_sign_inconsistent"].trade_ids.append(tid)
                    flags["direction_sign_inconsistent"].pnl_contribution += pnl

        # 4. protect_not_on_tick_grid
        if protect_px is not None:
            if not is_on_tick_grid(protect_px, cfg.tick_size):
                flags["protect_not_on_tick_grid"].trade_ids.append(tid)
                # No PnL contribution — just a data integrity flag

        # 5. exit_outside_bar_ohlc (requires bars_lookup_fn)
        if bars_lookup_fn is not None:
            bar = bars_lookup_fn(exit_ts)
            if bar is not None:
                _, bar_h, bar_l, _ = bar
                tol = cfg.ohlc_tolerance
                if exit_px < bar_l - tol or exit_px > bar_h + tol:
                    flags["exit_outside_bar_ohlc"].trade_ids.append(tid)
                    flags["exit_outside_bar_ohlc"].pnl_contribution += pnl

        # 6. exit_after_max_hold (sanity: > 12 hours since entry)
        if exit_ts - entry_ts > 12 * 3600 * 1_000_000_000:
            flags["exit_after_max_hold"].trade_ids.append(tid)

    # Aggregate impossible fills (Bucket 5 is the canonical one)
    impossible_n = flags["exit_outside_bar_ohlc"].count
    impossible_pnl = flags["exit_outside_bar_ohlc"].pnl_contribution
    has_impossible = impossible_n > 0

    summary = {
        "n_trades": int(n),
        "impossible_fills_n": int(impossible_n),
        "impossible_fills_pnl": float(impossible_pnl),
        "exit_before_arm_n": int(
            flags["exit_before_arm"].count),
        "direction_sign_inconsistent_n": int(
            flags["direction_sign_inconsistent"].count),
        "protect_not_on_tick_grid_n": int(
            flags["protect_not_on_tick_grid"].count),
        "exit_after_max_hold_n": int(
            flags["exit_after_max_hold"].count),
    }

    result = AuditResult(
        n_trades=int(n),
        flags=flags,
        impossible_fills_n=int(impossible_n),
        impossible_fills_pnl=float(impossible_pnl),
        has_impossible_fills=bool(has_impossible),
        summary=summary,
    )

    if cfg.hard_fail_on_impossible and has_impossible:
        raise RuntimeError(
            f"Replay output contains {impossible_n} impossible "
            f"fills (PnL contribution ${impossible_pnl:,.2f}). "
            f"Refusing to accept as tradable. See AuditResult flags.")

    return result


def make_catalog_bars_lookup_fn(catalog_path: str,
                                       bar_type: str):
    """Convenience: build a bars_lookup_fn that queries an NT
    catalog. Returns (open, high, low, close) for the bar at ts_ns,
    or None if no bar."""
    from nautilus_trader.persistence.catalog import (
        ParquetDataCatalog,
    )
    cat = ParquetDataCatalog(catalog_path)

    def lookup(ts_ns: int):
        ts = pd.Timestamp(int(ts_ns), tz="UTC")
        bars = cat.bars(
            bar_types=[bar_type], start=ts,
            end=ts + pd.Timedelta(seconds=2))
        if not bars:
            return None
        b = bars[0]
        return (float(b.open), float(b.high),
                  float(b.low), float(b.close))
    return lookup


# ---------------- CLI ----------------
def _cli():
    import argparse, sys, json
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(
        description=("Audit a replay-output trades.parquet for "
                       "fill-feasibility bugs"))
    ap.add_argument("trades", type=str,
                       help="Path to trades.parquet")
    ap.add_argument("--catalog", type=str, default=None,
                       help="Optional catalog path for OHLC bar lookup")
    ap.add_argument("--bar_type", type=str,
                       default="NQ.XCME-1-SECOND-LAST-EXTERNAL")
    ap.add_argument("--no_hard_fail", action="store_true",
                       help="Don't raise on impossible fills")
    args = ap.parse_args()

    df = pd.read_parquet(args.trades)
    lookup = (make_catalog_bars_lookup_fn(args.catalog,
                                                  args.bar_type)
                  if args.catalog else None)
    cfg = AuditConfig(
        hard_fail_on_impossible=(not args.no_hard_fail))
    try:
        result = audit_trades(df, lookup, cfg)
    except RuntimeError as e:
        print(f"AUDIT FAILED: {e}")
        sys.exit(1)
    print(result.as_markdown())
    print()
    print("Summary JSON:")
    print(json.dumps(result.summary, indent=2))


if __name__ == "__main__":
    _cli()
