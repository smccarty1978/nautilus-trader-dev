"""Generate per-run indicators.parquet (KNN health time-series) for the hC visualizer.

For each backtests/combined_arch/<run>/ that has a trades.parquet with regime_start_ts,
join the central per-bar hC mapping and emit a long-format companion:

    timestamp (int ns) | indicator (str) | value (float)

indicators: hc, hc_slope (dhC), hc_state (Healthy=3/SoftStall=2/HardStall=1/DETER=0), hc_dd.
Timestamp of post-flip bar k = regime_start_ts + k*60s (the 1m close where hC was actionable).
"""
from __future__ import annotations
import glob
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MAPPING = ROOT / "collectors/collector_v2/results/combined_arch/hc_perbar_mapping.parquet"
RUNS_GLOB = str(ROOT / "backtests/combined_arch/*/trades.parquet")
NS_MIN = 60 * 1_000_000_000
STATE_CODE = {"Healthy": 3, "SoftStall": 2, "HardStall": 1, "DETER": 0}


def main():
    m = pd.read_parquet(MAPPING)
    m["ts"] = m.regime_start_ts.astype("int64") + m.k.astype("int64") * NS_MIN
    m["state_code"] = m.state.map(STATE_CODE).astype(float)
    by_rst = {rst: g for rst, g in m.groupby("regime_start_ts")}

    n_runs = 0; n_rows = 0; no_map = []
    for tp in sorted(glob.glob(RUNS_GLOB)):
        run = Path(tp).parent
        df = pd.read_parquet(tp, columns=["regime_start_ts"]) if "regime_start_ts" in \
            pd.read_parquet(tp).columns else pd.DataFrame()
        if df.empty:
            no_map.append(run.name); continue
        rsts = pd.unique(df.regime_start_ts.astype("int64"))
        sub = pd.concat([by_rst[r] for r in rsts if r in by_rst], ignore_index=True) \
            if any(r in by_rst for r in rsts) else pd.DataFrame()
        rows = []
        if len(sub):
            for col, name in [("hC", "hc"), ("dhC", "hc_slope"),
                              ("state_code", "hc_state"), ("dd", "hc_dd")]:
                s = sub[["ts", col]].dropna()
                # clip dd display (unbounded when peak-hC≈0; cap for readability)
                vals = s[col].clip(-2, 5) if name == "hc_dd" else s[col]
                rows.append(pd.DataFrame({"timestamp": s.ts.astype("int64"),
                                          "indicator": name, "value": vals.astype(float)}))
        out = pd.concat(rows, ignore_index=True) if rows else \
            pd.DataFrame(columns=["timestamp", "indicator", "value"])
        out.to_parquet(run / "indicators.parquet", index=False)
        n_runs += 1; n_rows += len(out)
    print(f"wrote indicators.parquet for {n_runs} runs, {n_rows:,} total rows")
    if no_map:
        print(f"runs without regime_start_ts (empty indicators): {no_map}")


if __name__ == "__main__":
    main()
