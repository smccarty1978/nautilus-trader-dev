"""Run NT BacktestEngine to collect 5s observations from regime-flip episodes.

Covers the full study window: 2024-01-01 through 2025-05-31.
Uses 14 days of lead-in before the study start for indicator warmup.

Outputs (in results/):
  feature_snapshots.parquet   all observations with 28 features + metadata
  execution_contract.json     cost model documentation
  feature_contract.json       feature list + description
"""
from __future__ import annotations

import json
import os
import sys
import time
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
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from studies.rl_regime_feasibility.collector import RLCollectorConfig, RLFeatureCollector
from studies.rl_regime_feasibility.execution import save_contract

CATALOG_PATH = "data/catalog/NQ_v0_2020_2026"
OUT_DIR      = Path("studies/rl_regime_feasibility/results")

LEAD_IN      = pd.Timedelta(days=14)
STUDY_START  = pd.Timestamp("2024-01-01", tz="UTC")
STUDY_END    = pd.Timestamp("2025-05-31 23:59:59", tz="UTC")

# Period labels for post-hoc analysis (applied to obs by date in run_study.py)
PERIODS = {
    "train": ("2024-01-01", "2024-12-31"),
    "val":   ("2025-01-01", "2025-02-28"),
    "test":  ("2025-03-01", "2025-05-31"),
}

# Chunked collection: each chunk fits in < 10 min by keeping bar count under ~13M.
# Chunks use 14-day lead-in for the first chunk, 2-day lead-in for subsequent ones.
CHUNKS = [
    # (chunk_study_start, chunk_study_end, lead_in_days, chunk_label)
    ("2024-01-01", "2024-05-31 23:59:59", 14, "chunk1"),   # ~6M bars
    ("2024-06-01", "2024-10-31 23:59:59",  2, "chunk2"),   # ~6M bars
    ("2024-11-01", "2025-05-31 23:59:59",  2, "chunk3"),   # ~7M bars
]


def _create_nq() -> FuturesContract:
    t = TestInstrumentProvider.future(
        symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2027-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["multiplier"]      = "20"
    d["price_increment"] = "0.25"
    return FuturesContract.from_dict(d)


def _save_feature_contract(out_dir: Path) -> None:
    contract = {
        "features": {
            "seconds_since_flip": "seconds elapsed since 1m regime flip",
            "current_progress_atr": "direction*(close-flip_close)/atr",
            "max_progress_atr": "peak direction progress in ATR since flip",
            "max_adverse_atr": "peak adverse excursion in ATR since flip",
            "pullback_from_peak_atr": "max_progress - current_progress",
            "seconds_since_peak": "seconds since max_progress was achieved",
            "progress_efficiency": "max_progress / max(1, minutes_since_flip)",
            "aligned_return_5s_atr": "direction*(close_now - close_prev_5s) / atr",
            "aligned_return_15s_atr": "direction*(close_now - close_15s_ago) / atr",
            "aligned_return_30s_atr": "direction*(close_now - close_30s_ago) / atr",
            "aligned_return_60s_atr": "direction*(close_now - close_60s_ago) / atr",
            "realized_vol_60s_atr": "std(60 1s close diffs) / atr",
            "range_5s_atr": "(5s_high - 5s_low) / atr",
            "volume_5s_zscore": "z-score of 5s bucket volume vs trailing 5-min history",
            "volume_30s_vs_5m": "30s volume rate / 5m volume rate",
            "bollinger_width_percentile_1m": "causal percentile of BB width (1m, n=20) in history",
            "bollinger_keltner_width_ratio_1m": "BB width / KC width (1m, n=20)",
            "kalman_velocity_atr_per_s": "Kalman price velocity / atr",
            "kalman_acceleration_atr_per_s2": "Kalman velocity change per second / atr",
            "kalman_innovation_zscore": "Kalman price innovation z-score (vs trailing 60s median)",
            "ema3_ema9_spread_30s_atr": "direction-aligned EMA3-EMA9 spread on 30s bars / atr",
            "regime_5s_aligned": "+1 if 5s regime == direction, -1 if opposite, 0 if neutral",
            "regime_30s_aligned": "+1 if 30s regime == direction, -1 if opposite, 0 if neutral",
            "regime_5m_aligned": "+1 if 5m regime == direction, -1 if opposite, 0 if neutral",
            "regime_age_1m_bars": "bars_in_regime from 1m engine (current regime bar count)",
            "adx14_1m": "Wilder ADX(14) on completed 1m bars (nan until 28 bars)",
            "position_in_trailing_1m_range": "(close - min_20bar_low) / (max_20bar_high - min_20bar_low)",
            "minutes_since_rth_open": "minutes since 13:30 UTC; nan outside RTH",
        },
        "observation_cadence": "every 5 seconds from regime flip through termination",
        "episode_start": "1m regime flip (direction change); first obs at flip close_ts",
        "episode_end": "opposing 1m flip OR 30-min timeout OR data end",
        "current_price_convention": "5s bucket.close (last 1s close in closed 5s bucket)",
        "entry_fill_convention": "next 1s bar open after observation_time (see labels.py)",
    }
    path = out_dir / "feature_contract.json"
    with open(path, "w") as f:
        json.dump(contract, f, indent=2)
    print(f"  wrote {path}")


def _run_chunk(
    chunk_start: pd.Timestamp,
    chunk_end: pd.Timestamp,
    lead_in_days: int,
    chunk_label: str,
    cat: "ParquetDataCatalog",
    nq,
) -> list[dict]:
    """Run one backtest chunk and return its observations."""
    load_start = chunk_start - pd.Timedelta(days=lead_in_days)
    print(f"\n  [{chunk_label}] Loading bars [{load_start.date()} → {chunk_end.date()}] ...")
    t0 = time.time()
    bars = cat.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=load_start,
        end=chunk_end,
    )
    print(f"  [{chunk_label}] {len(bars):,} bars in {time.time()-t0:.0f}s")

    engine_cfg = BacktestEngineConfig(
        trader_id=f"RL-COL-{chunk_label.upper()}",
        logging=LoggingConfig(
            log_level="WARNING",
            log_level_file="WARNING",
            log_directory=str(OUT_DIR / "logs"),
        ),
    )
    engine = BacktestEngine(config=engine_cfg)
    engine.add_venue(
        venue=Venue("XCME"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
        bar_execution=True,
    )
    engine.add_instrument(nq)
    engine.add_data(bars)

    strat = RLFeatureCollector(RLCollectorConfig(
        instrument_id="NQ.XCME",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
    ))
    engine.add_strategy(strat)

    t0 = time.time()
    engine.run()
    elapsed = time.time() - t0
    obs = list(strat.obs_log)
    engine.dispose()
    del bars  # free ~several GB of NT Bar objects before next chunk

    # Filter out lead-in observations
    obs_in_window = [
        r for r in obs
        if pd.Timestamp(r["observation_time"], unit="ns", tz="UTC") >= chunk_start
    ]
    print(f"  [{chunk_label}] done in {elapsed:.0f}s — "
          f"{len(obs_in_window):,} obs in window (of {len(obs):,} total)")
    return obs_in_window


def run() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Saving contracts ...")
    save_contract(OUT_DIR)
    _save_feature_contract(OUT_DIR)

    cat = ParquetDataCatalog(CATALOG_PATH)
    nq  = _create_nq()

    # Collect in chunks to stay within memory/time limits (~6M bars each)
    all_obs: list[dict] = []
    for (cs, ce, lead_days, label) in CHUNKS:
        chunk_obs = _run_chunk(
            chunk_start   = pd.Timestamp(cs, tz="UTC"),
            chunk_end     = pd.Timestamp(ce, tz="UTC"),
            lead_in_days  = lead_days,
            chunk_label   = label,
            cat           = cat,
            nq            = nq,
        )
        all_obs.extend(chunk_obs)

    print(f"\nTotal observations: {len(all_obs):,}")
    if not all_obs:
        print("ERROR: no observations collected — check data/config.")
        return

    df = pd.DataFrame(all_obs)

    # Tag period
    def _tag(row):
        ts = pd.Timestamp(row["observation_time"], unit="ns", tz="UTC")
        for name, (s, e) in PERIODS.items():
            if pd.Timestamp(s, tz="UTC") <= ts <= pd.Timestamp(e + " 23:59:59", tz="UTC"):
                return name
        return "other"

    df["period"] = df.apply(_tag, axis=1)
    df.sort_values("observation_time", inplace=True)

    path = OUT_DIR / "feature_snapshots.parquet"
    df.to_parquet(path, index=False)
    print(f"  saved {len(df):,} rows → {path}")

    # Summary
    for period, (s, e) in PERIODS.items():
        sub = df[df["period"] == period]
        ep_n = sub["episode_id"].nunique() if "episode_id" in sub.columns else 0
        print(f"  {period}: {len(sub):,} obs from {ep_n:,} episodes [{s} → {e}]")

    print("\nDone.")


if __name__ == "__main__":
    run()
