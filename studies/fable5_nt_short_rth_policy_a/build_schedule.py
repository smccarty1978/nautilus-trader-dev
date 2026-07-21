"""Extract the frozen short-RTH W4 entry schedule for Phase 1 parity input.

Phase 1 feeds NT the frozen entry signals (short fades, RTH, one per regime)
and validates Policy A management + fill semantics independent of live signal
generation. The strategy uses ONLY: decision_ts (entry signal), entry target
fill ts, direction, and causal atr_at_checkpoint. confirm_flip_ns and the
offline exit fields are carried for RECONCILIATION ONLY and are never read by
the strategy's decision logic.
"""
from __future__ import annotations

import argparse

import pandas as pd

import common as C


def build(year: int) -> pd.DataFrame:
    d = pd.read_parquet(C.frozen_trade_path(year))
    s = d[(d.entry_direction == -1) & (d.session == "RTH")].copy()
    s = s.sort_values("entry_fill_ts").reset_index(drop=True)
    keep = {
        "regime_start_ns": s.regime_start_ns.astype("int64"),
        "signal_decision_ts": s.decision_ts.astype("int64"),
        "target_fill_ts": s.entry_fill_ts.astype("int64"),
        "offline_entry_open": s.entry_fill_open.astype(float),
        "entry_direction": s.entry_direction.astype("int64"),
        "atr_at_checkpoint": s.atr_at_checkpoint.astype(float),
        # reconciliation-only (NOT used by the strategy):
        "recon_confirm_flip_ns": s.confirm_flip_ns.astype("int64"),
        "recon_scheduled_exit_ts": s.scheduled_exit_decision_ts.astype("int64"),
        "year": s.year.astype("int64"),
    }
    out = pd.DataFrame(keep)
    expected = {2025: 604, 2026: 203}[year]
    if len(out) != expected:
        raise RuntimeError(f"{year} short-RTH schedule count {len(out)} != {expected}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, choices=(2025, 2026), required=True)
    args = ap.parse_args()
    out = build(args.year)
    out.to_parquet(C.schedule_path(args.year), index=False)
    print(f"{args.year}: {len(out)} short-RTH entries -> {C.schedule_path(args.year)}")


if __name__ == "__main__":
    main()
