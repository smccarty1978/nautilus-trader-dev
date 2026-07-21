from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import RESULTS, WORK, year_catalog
from strategy import PreFlipD10Config, PreFlipD10Strategy
from studies._shared_exit_mgmt.nt_runner import run_period


def load_events(year: int, start: pd.Timestamp, end: pd.Timestamp, placebo: bool = False) -> tuple[tuple, ...]:
    path = WORK / ("placebo_events.parquet" if placebo else "causal_scores.parquet")
    d = pd.read_parquet(path)
    ts = pd.to_datetime(d.observation_time, unit="ns", utc=True)
    # Only official-window events enter the lookup. Warmup is solely for the NT
    # regime/ATR state and may begin inside a regime whose start predates the
    # loaded stream, so warmup score events must never hit fail-fast identity.
    d = d[(ts + pd.Timedelta(seconds=1) >= start)
          & (ts + pd.Timedelta(seconds=1) <= end - pd.Timedelta(seconds=1))].copy()
    if not placebo:
        frozen = json.loads((WORK / "frozen_threshold.json").read_text())
        thr = frozen["threshold"]
        d = d[d.score_valid].sort_values("observation_time")
        d["above"] = d.score >= thr
        d["prev"] = d.groupby("regime_id").above.shift(fill_value=False)
        d = d[d.above & ~d.prev]
        d["threshold"] = thr
    # Score from a 1s bar at observation_time becomes causal at ts_init +1s.
    return tuple((int(r.observation_time) + 1_000_000_000, int(r.direction),
                  int(r.regime_start_time), float(r.score), float(r.threshold))
                 for r in d.itertuples())


def run_one(year: int, policy: str, stop: float) -> dict:
    out = WORK / "nt_runs" / f"{year}_{policy}_{stop:.2f}"
    start = pd.Timestamp("2025-03-01", tz="UTC") if year == 2025 else pd.Timestamp("2026-01-01", tz="UTC")
    end = pd.Timestamp("2026-04-29 23:59:59", tz="UTC") if year == 2026 else pd.Timestamp("2025-12-31 23:59:59", tz="UTC")
    cfg = {
        "policy": policy, "stop_atr_mult": stop,
        "official_start_ns": int(start.value), "official_end_ns": int(end.value - 1_000_000_000),
        "rth_only": False, "position_size": 1, "entry_delay_ns": 0,
        "d10_events": load_events(year, start, end, False),
        "placebo_events": load_events(year, start, end, True) if policy.startswith("P4") else (),
    }
    result = run_period(
        PreFlipD10Strategy, PreFlipD10Config, cfg,
        start - pd.Timedelta(days=5), end, out,
        catalog_path=str(year_catalog(year)), trader_id=f"D10-{year}-{policy}-{stop}"[:20],
    )
    result.update({"year": year, "policy": policy, "stop_atr_mult": stop, "out": str(out)})
    return result


def main():
    runs = []
    for year in (2025, 2026):
        for policy, stops in (("P0", [1.0]), ("P2", [1.0]),
                              ("P1", [.5,1.,1.5]), ("P3", [.5,1.,1.5]),
                              ("P4A", [.5,1.,1.5]), ("P4B", [.5,1.,1.5])):
            for stop in stops:
                print(f"RUN {year} {policy} {stop}", flush=True)
                runs.append(run_one(year, policy, stop))
    (WORK / "nt_runs" / "run_summary.json").write_text(json.dumps(runs, indent=2, default=str))


if __name__ == "__main__":
    main()
