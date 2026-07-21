"""Genuine NautilusTrader BacktestEngine execution for every policy in this
study: R0, static R2, static R4, and A1/A2/A4 x {3m,6m,12m}.

Reuses collectors/collector_v2/strategy.py (CollectorV2Strategy) exactly as
studies/rank_filter_oos_validation/run_nt_validation.py does -- same
entry_delay_ns (30s canonical delay), same skip_decision_ts pass-through gate
(a frozen, precomputed set of decision_ts values to skip; the score/exemption
decision is never recomputed inside the NT event loop), same E0-only exit
(enable_hhll_exit=False). The only thing that differs per policy is which
decision_ts values are in the skip set -- entry/exit mechanics are identical
for every policy, which is what makes "retained trades must be identical to
R0 on entry/exit timestamp/price" a meaningful, checkable claim rather than
an assumption.

Static R2/R4 use the frozen studies/regime_sequence_signal_audit threshold
(0.12855426455573915) and the frozen R2/R4 exemption formulas, evaluated
fresh over Jan 2025 - Apr 2026 (same rule as
rank_filter_oos_validation/run_nt_validation.py::load_skip_set, just a wider
date range so this study has a monthly baseline for the whole period, not
just 2025H2 onward).

Adaptive A1/A2/A4 skip sets come from train_adaptive_models.py's per-fold,
per-deployment-month decisions (studies/adaptive_rank_filter_walkforward/
_work/adaptive_skip_decisions.parquet), concatenated across all 16
deployment months into one skip set per (policy, window) -- one continuous
NT run per catalog-year still correctly reflects month-by-month retraining,
since the skip set is just a set of timestamps to skip regardless of which
fold produced each one.
"""
from __future__ import annotations
import sys
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
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

import awf_common as c

WORK_DIR = c.OUT.parent / "_work"

STATIC_POLICIES = ("r0", "static_r2", "static_r4")
ADAPTIVE_POLICIES = tuple(f"a{n}_{w}" for w in c.WINDOW_SIZES for n in (1, 2, 4))
ALL_POLICIES = STATIC_POLICIES + ADAPTIVE_POLICIES

PERIODS = {
    "2025": {"catalog": c.NT_CATALOGS[2025]["catalog"], "start": c.NT_CATALOGS[2025]["start"], "end": c.NT_CATALOGS[2025]["end"]},
    "2026": {"catalog": c.NT_CATALOGS[2026]["catalog"], "start": c.NT_CATALOGS[2026]["start"], "end": c.NT_CATALOGS[2026]["end"]},
}


def static_skip_set(f2: pd.DataFrame, policy: str) -> tuple[int, ...]:
    frozen = c.load_frozen_config()
    thr = frozen["score_thresholds_test"][c.STATIC_FROZEN_THRESHOLD_KEY]
    in_range = (f2["observation_time"] >= pd.Timestamp("2025-01-01", tz="UTC").value) & \
               (f2["observation_time"] <= pd.Timestamp("2026-04-29 23:59:59", tz="UTC").value)
    signals = f2[in_range]
    score_skip = signals["ridge_log_fail_prob"] >= thr
    if policy == "static_r2":
        exempt = signals[c.R2_EXEMPT_COL] > c.R2_EXEMPT_THR
    elif policy == "static_r4":
        exempt = signals[c.R4_EXEMPT_COL] > c.R4_EXEMPT_THR
    else:
        raise ValueError(policy)
    skip = score_skip & ~exempt
    return tuple(int(x) for x in signals.loc[skip, "confirmation_ts"].astype("int64").values)


def adaptive_skip_set(policy: str) -> tuple[int, ...]:
    a_num = policy[1]  # "1"/"2"/"4"
    window_name = policy.split("_", 1)[1]  # "3m"/"6m"/"12m"
    df = pd.read_parquet(WORK_DIR / "adaptive_skip_decisions.parquet")
    df = df[df["window_name"] == window_name]
    skip_col = f"a{a_num}_skip"
    skipped = df.loc[df[skip_col].astype(bool), "confirmation_ts"].astype("int64").values
    return tuple(int(x) for x in skipped)


def load_skip_set(f2: pd.DataFrame, policy: str) -> tuple[int, ...]:
    if policy == "r0":
        return ()
    if policy in ("static_r2", "static_r4"):
        return static_skip_set(f2, policy)
    return adaptive_skip_set(policy)


def run_backtest(f2: pd.DataFrame, policy: str, period_key: str) -> dict:
    period = PERIODS[period_key]
    out_dir = c.NT_OUT_ROOT / f"{policy}_{period_key}"
    out_dir.mkdir(parents=True, exist_ok=True)

    load_start = pd.Timestamp(period["start"], tz="UTC") - pd.Timedelta(days=5)
    load_end = pd.Timestamp(period["end"] + " 23:59:59", tz="UTC")

    print(f"[{policy}/{period_key}] loading catalog {period['catalog']} {load_start} -> {load_end}...", flush=True)
    t0 = time.time()
    catalog = ParquetDataCatalog(period["catalog"])
    bars_1s = catalog.bars(bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"], start=load_start, end=load_end)
    bars_1m = catalog.bars(bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"], start=load_start, end=load_end)
    print(f"  {len(bars_1s):,} 1s + {len(bars_1m):,} 1m bars loaded ({time.time()-t0:.0f}s)", flush=True)

    skip_set = load_skip_set(f2, policy)
    print(f"  policy={policy} skip_set_size={len(skip_set)}", flush=True)

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=f"AWF-{policy.upper()}-{period_key}".replace("_", "")[:20],
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
        entry_delay_ns=c.ENTRY_DELAY_NS,
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

    print(f"  [{policy}/{period_key}] done in {elapsed:.0f}s. diag={diag}", flush=True)

    with open(out_dir / "run_meta.json", "w") as f:
        json.dump({"policy": policy, "period_key": period_key, "period": period,
                    "elapsed_s": elapsed, "diag": diag, "skip_set_size": len(skip_set)}, f, indent=2, default=str)

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
    f2 = c.load_f2_atlas()
    results = []
    for period_key in ("2025", "2026"):
        for policy in ALL_POLICIES:
            r = run_backtest(f2, policy, period_key)
            results.append(r)
    with open(c.NT_OUT_ROOT / "run_summary.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("ALL NT RUNS COMPLETE")
    return results


if __name__ == "__main__":
    main()
