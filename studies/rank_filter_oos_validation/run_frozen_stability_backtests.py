"""Frozen-policy stability audit: run the EXISTING, UNCHANGED R0/R2/R4
NautilusTrader implementation (same frozen score threshold 0.12855426455573915,
same R2/R4 exemption expressions, same 30s entry delay, same E0 exit) across
8 retrospective blocks. No retraining, no retuning, no threshold/exemption
changes -- this only runs the frozen policies over more historical windows to
see whether R4's apparent value is broadly distributed or concentrated.

2025H2 and 2026 (Jan-Apr 29) already have real NT runs from the prior
validation pass (studies/rank_filter_oos_validation/nt_runs/{r0,r2,r4}_{2025H2,2026});
those are reused as-is, not rerun.

Catalog note (documented, not fixed here -- diagnostic only, not a capital
decision): 2021-2024 have no bug-fixed per-year catalog available (only
NQ_v0_2020_2026 exists for that range, which has a known ~1-second look-ahead
in its separately-published 1-MINUTE bar type from an un-fixed closed='right'
resample -- see backtests/studies/level_momentum_continuation/build_v0_2025_catalog_fixed.py
for the documented bug and its 2025/2026 fix). CollectorV2Strategy's own
regime-flip DETECTION is built causally from the 1-SECOND bar stream via its
own TimeframeAggregator (unaffected by this bug), but the bar+1 HH/LL
CONFIRMATION check reads self._latest_1m_bar_data, which IS sourced from the
catalog's separately-published 1m bar type -- so 2021-2024 confirmation
checks inherit up to ~1s of look-ahead in the confirmation bar's H/L/O/C.
2025 (all three blocks) and 2026 use the bug-fixed NQ_v0_2025_fixed /
NQ_v0_2026_fixed catalogs and are NOT affected. Reported as a caveat on the
2021-2024 blocks in final_report.md, consistent with this audit's explicit
"retrospective robustness diagnostic, not new OOS evidence" scope.
"""
from __future__ import annotations
import os, sys, time, json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from collectors.collector_v2.strategy import CollectorV2Strategy, CollectorV2Config

sys.path.insert(0, str(PROJECT_ROOT / "studies/rank_filter_oos_validation"))
from common import OUT as RESEARCH_OUT, load_atlas, repair_f2_window, load_frozen_config

ENTRY_DELAY_NS = 30_000_000_000

BLOCKS = {
    "2021": {"catalog": "data/catalog/NQ_v0_2020_2026", "start": "2021-01-01", "end": "2021-12-31",
              "catalog_bug_caveat": True},
    "2022": {"catalog": "data/catalog/NQ_v0_2020_2026", "start": "2022-01-01", "end": "2022-12-31",
              "catalog_bug_caveat": True},
    "2023": {"catalog": "data/catalog/NQ_v0_2020_2026", "start": "2023-01-01", "end": "2023-12-31",
              "catalog_bug_caveat": True},
    "2024": {"catalog": "data/catalog/NQ_v0_2020_2026", "start": "2024-01-01", "end": "2024-12-31",
              "catalog_bug_caveat": True},
    "2025_JanFeb": {"catalog": "data/catalog/NQ_v0_2025_fixed", "start": "2025-01-01", "end": "2025-02-28",
                     "catalog_bug_caveat": False},
    "2025_MarMay": {"catalog": "data/catalog/NQ_v0_2025_fixed", "start": "2025-03-01", "end": "2025-05-31",
                     "catalog_bug_caveat": False},
    # Already run in the prior validation pass; reused, not rerun:
    "2025_JunDec": {"catalog": "data/catalog/NQ_v0_2025_fixed", "start": "2025-06-01", "end": "2025-12-31",
                     "catalog_bug_caveat": False, "reuse_run_key": "2025H2"},
    "2026_JanApr29": {"catalog": "data/catalog/NQ_v0_2026_fixed", "start": "2026-01-01", "end": "2026-04-29",
                       "catalog_bug_caveat": False, "reuse_run_key": "2026"},
}

NT_RUNS = PROJECT_ROOT / "studies/rank_filter_oos_validation/nt_runs"
AUDIT_RUNS = PROJECT_ROOT / "studies/rank_filter_oos_validation/results/frozen_stability_audit/nt_runs"
AUDIT_RUNS.mkdir(parents=True, exist_ok=True)


def load_skip_set(policy: str, block: dict) -> tuple[int, ...]:
    """Identical frozen rule to run_nt_validation.py::load_skip_set -- same
    threshold, same exemption expressions, evaluated fresh over this block's
    date range via repair_f2_window (no retrain, no new features)."""
    if policy == "r0":
        return ()
    df_atlas = load_atlas()
    signals, _ = repair_f2_window(df_atlas, block["start"], block["end"])
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


def run_backtest(policy: str, block_key: str) -> dict:
    block = BLOCKS[block_key]
    out_dir = AUDIT_RUNS / f"{policy}_{block_key}"
    out_dir.mkdir(parents=True, exist_ok=True)

    load_start = pd.Timestamp(block["start"], tz="UTC") - pd.Timedelta(days=5)
    load_end = pd.Timestamp(block["end"] + " 23:59:59", tz="UTC")

    print(f"[{policy}/{block_key}] loading catalog {block['catalog']} {load_start} -> {load_end}...", flush=True)
    t0 = time.time()
    catalog = ParquetDataCatalog(block["catalog"])
    bars_1s = catalog.bars(bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"], start=load_start, end=load_end)
    bars_1m = catalog.bars(bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"], start=load_start, end=load_end)
    print(f"  {len(bars_1s):,} 1s + {len(bars_1m):,} 1m bars loaded ({time.time()-t0:.0f}s)", flush=True)

    skip_set = load_skip_set(policy, block)
    print(f"  policy={policy} skip_set_size={len(skip_set)}", flush=True)

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=f"FSA-{policy.upper()}-{block_key}"[:20],
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
        rth_only=False,
        position_size=1,
        require_5m_aligned=False,
        entry_delay_ns=ENTRY_DELAY_NS,
        skip_decision_ts=skip_set,
        output_dir=str(out_dir),
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

    print(f"  [{policy}/{block_key}] done in {elapsed:.0f}s. diag={diag}", flush=True)

    with open(out_dir / "run_meta.json", "w") as f:
        json.dump({"policy": policy, "block_key": block_key, "block": block,
                    "elapsed_s": elapsed, "diag": diag, "skip_set_size": len(skip_set)}, f, indent=2, default=str)

    win_start = pd.Timestamp(block["start"], tz="UTC").value
    win_end = pd.Timestamp(block["end"] + " 23:59:59", tz="UTC").value
    for fname in ("trades.parquet", "policy_skips.parquet", "pending_cancellations.parquet"):
        p = out_dir / fname
        if p.exists():
            df = pd.read_parquet(p)
            ts_col = "decision_ts" if "decision_ts" in df.columns else None
            if ts_col:
                df = df[(df[ts_col] >= win_start) & (df[ts_col] <= win_end)]
                df.to_parquet(p, index=False)

    return {"policy": policy, "block_key": block_key, "elapsed_s": elapsed, "diag": diag}


def link_reused_run(policy: str, block_key: str):
    """For blocks that reuse an already-completed run from nt_runs/, copy the
    relevant output files into results/frozen_stability_audit/nt_runs/ so
    the aggregation step can treat every block uniformly."""
    import shutil
    block = BLOCKS[block_key]
    reuse_key = block["reuse_run_key"]
    src = NT_RUNS / f"{policy}_{reuse_key}"
    dst = AUDIT_RUNS / f"{policy}_{block_key}"
    dst.mkdir(parents=True, exist_ok=True)
    for fname in ("trades.parquet", "policy_skips.parquet", "pending_cancellations.parquet", "run_meta.json"):
        p = src / fname
        if p.exists():
            shutil.copy(p, dst / fname)
    print(f"[{policy}/{block_key}] reused existing run from nt_runs/{policy}_{reuse_key}/")


def main():
    results = []
    for block_key, block in BLOCKS.items():
        for policy in ("r0", "r2", "r4"):
            if "reuse_run_key" in block:
                link_reused_run(policy, block_key)
            else:
                r = run_backtest(policy, block_key)
                results.append(r)
    with open(AUDIT_RUNS / "run_summary.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("ALL FROZEN STABILITY AUDIT RUNS COMPLETE")
    return results


if __name__ == "__main__":
    main()
