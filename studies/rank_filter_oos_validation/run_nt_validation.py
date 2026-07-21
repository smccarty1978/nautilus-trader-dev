"""Phase 2: genuine NautilusTrader BacktestEngine event-driven validation of
R0/R2/R4 -- NOT a post-hoc pandas replay.

Reuses collectors/collector_v2/strategy.py (CollectorV2Strategy), which
already implements the canonical mechanics: causal 1m regime engine,
bar+1 HH/LL + directional-close confirmation, opposite-flip pending-entry
cancellation, and E0 (regime-only) exit. Two small, backward-compatible
additions were made to that shared strategy (default-preserving for every
other caller):
  - entry_delay_ns (default 0): canonical 30s delayed-activation mechanic
  - skip_decision_ts (default ()): a frozen, precomputed pass-through skip
    gate for R2/R4 -- the score/exemption decision is taken from the
    already-frozen research table (studies/regime_sequence_signal_audit),
    NOT recomputed inside the NT event loop (no retraining, no new
    features), applied at the exact instant it's available (confirmation
    close = decision_ts).

Runs R0 (empty skip set), R2, and R4 separately for two NON-POOLED periods:
  - 2025-06-01 to 2025-12-31 (primary, clean OOS)
  - 2026 available range (forward evaluation, labeled contaminated/
    previously-inspected, not clean OOS -- see final_report.md)
"""
from __future__ import annotations
import os, sys, time, json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from collectors.collector_v2.strategy import CollectorV2Strategy, CollectorV2Config

sys.path.insert(0, str(PROJECT_ROOT / "studies/rank_filter_oos_validation"))
from common import OUT

ENTRY_DELAY_NS = 30_000_000_000

PERIODS = {
    "2025H2": {
        "catalog": "data/catalog/NQ_v0_2025_fixed",
        "start": "2025-06-01",
        "end": "2025-12-31",
        "label": "primary_clean_oos",
    },
    "2026": {
        "catalog": "data/catalog/NQ_v0_2026_fixed",
        "start": "2026-01-01",
        "end": "2026-04-29",  # catalog coverage end
        "label": "forward_eval_previously_inspected_contaminated",
    },
}

NT_OUT_ROOT = PROJECT_ROOT / "studies/rank_filter_oos_validation/nt_runs"


def load_skip_set(policy: str, period_key: str) -> tuple[int, ...]:
    """Build the frozen decision_ts skip set for the given period.

    For 2025H2 this reuses the already-corrected, already-frozen research
    table (Phase 1 output) directly. For 2026, no Phase-1 corrected table
    was built (Phase 1's scope was the 2025H2 primary window only), so the
    same frozen threshold/exemption logic is applied fresh to 2026's
    confirmed signals via repair_f2_window + the identical rule from
    build_episodes.py -- NOT a retrain, NOT a new feature: same frozen
    score threshold (0.12855426455573915) and same exemption expressions,
    just evaluated over a different date range. Bug fix: the first version
    of this script always used the 2025H2 skip set regardless of
    period_key, so 2026's R2/R4 runs silently filtered nothing (identical
    to R0) -- caught by comparing entries_filled across policies for 2026
    (3957/3957/3957, bit-identical net_pnl) before trusting results."""
    if policy == "r0":
        return ()
    if period_key == "2025H2":
        ep = pd.read_parquet(OUT / "corrected_episode_results.parquet")
        skip_col = f"{policy}_skip"
        skipped = ep.loc[ep[skip_col], "confirmation_ts"].astype("int64").values
        return tuple(int(x) for x in skipped)

    from common import load_atlas, repair_f2_window, load_frozen_config
    df_atlas = load_atlas()
    period = PERIODS[period_key]
    signals, _ = repair_f2_window(df_atlas, period["start"], period["end"])
    frozen = load_frozen_config()
    thr = frozen["score_thresholds_test"]["R1"]
    score_skip = signals["ridge_log_fail_prob"] >= thr
    if policy == "r2":
        exempt = signals["seq_5r_center_migration_slope_atr"] > 0.005
    elif policy == "r4":
        exempt = signals["seq_5r_asym_duration"] > 1.5
    else:
        raise ValueError(policy)
    skip = score_skip & ~exempt
    skipped = signals.loc[skip, "confirmation_ts"].astype("int64").values
    return tuple(int(x) for x in skipped)


def run_backtest(policy: str, period_key: str) -> dict:
    period = PERIODS[period_key]
    out_dir = NT_OUT_ROOT / f"{policy}_{period_key}"
    out_dir.mkdir(parents=True, exist_ok=True)

    load_start = pd.Timestamp(period["start"], tz="UTC") - pd.Timedelta(days=5)
    load_end = pd.Timestamp(period["end"] + " 23:59:59", tz="UTC")

    print(f"[{policy}/{period_key}] loading catalog {period['catalog']} "
          f"{load_start} -> {load_end}...", flush=True)
    t0 = time.time()
    catalog = ParquetDataCatalog(period["catalog"])
    bars_1s = catalog.bars(bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"], start=load_start, end=load_end)
    bars_1m = catalog.bars(bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"], start=load_start, end=load_end)
    print(f"  {len(bars_1s):,} 1s + {len(bars_1m):,} 1m bars loaded ({time.time()-t0:.0f}s)", flush=True)

    skip_set = load_skip_set(policy, period_key)
    print(f"  policy={policy} skip_set_size={len(skip_set)}", flush=True)

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=f"NTV-{policy.upper()}-{period_key}"[:20],
        logging=LoggingConfig(log_level="WARNING", log_directory=str(out_dir / "logs")),
    ))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
        bar_execution=True,
    )
    engine.add_instrument(catalog.instruments()[0])
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)

    cfg = CollectorV2Config(
        instrument_id="NQ.XCME",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        mode="trading",
        rth_only=False,          # trade both RTH and ETH, matching the corrected research population
        position_size=1,
        require_5m_aligned=False,
        entry_delay_ns=ENTRY_DELAY_NS,
        skip_decision_ts=skip_set,
        output_dir=str(out_dir),
        # explicit, defaults anyway: clean E0-only exit, no overlays
        enable_hhll_exit=False,
        force_flat_at_min_ct=0,
        no_entry_after_min_ct=0,
    )
    strat = CollectorV2Strategy(cfg)
    engine.add_strategy(strat)

    t0 = time.time()
    engine.run()
    elapsed = time.time() - t0
    diag = dict(strat._diag)
    engine.dispose()

    print(f"  [{policy}/{period_key}] done in {elapsed:.0f}s. diag={diag}", flush=True)

    with open(out_dir / "run_meta.json", "w") as f:
        json.dump({"policy": policy, "period_key": period_key, "period": period,
                    "elapsed_s": elapsed, "diag": diag, "skip_set_size": len(skip_set)}, f, indent=2, default=str)

    # Trim entries loaded from the 5-day warmup buffer that fall before the
    # official window start (buffer is for regime-engine warmup only).
    win_start = pd.Timestamp(period["start"], tz="UTC").value
    win_end = pd.Timestamp(period["end"] + " 23:59:59", tz="UTC").value
    for fname in ("trades.parquet", "policy_skips.parquet", "pending_cancellations.parquet"):
        p = out_dir / fname
        if p.exists():
            df = pd.read_parquet(p)
            ts_col = "decision_ts" if "decision_ts" in df.columns else None
            if ts_col:
                df = df[(df[ts_col] >= win_start) & (df[ts_col] <= win_end)]
                df.to_parquet(p, index=False)

    return {"policy": policy, "period_key": period_key, "elapsed_s": elapsed, "diag": diag}


def main():
    results = []
    for period_key in ("2025H2", "2026"):
        for policy in ("r0", "r2", "r4"):
            r = run_backtest(policy, period_key)
            results.append(r)
    with open(NT_OUT_ROOT / "run_summary.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("ALL NT RUNS COMPLETE")
    return results


if __name__ == "__main__":
    main()
