"""
Contextual Runner Exit v2 — shared infrastructure.

Central design decisions (documented conservative assumptions):

  * The 5-second decision spine is the EXISTING repaired exit atlas
    (`exit_atlas_checkpoints.parquet`). Each row is a completed-5s observation
    at `observation_time` for a runner trade already 180s into a 1m regime flip.
    Reusing it guarantees identical entry/stop/fill/terminal mechanics as the
    repaired sim_v2 stack (the non-negotiable execution rule).

  * Execution economics come from `exit_optimal_stopping/repair/sim_v2.py`:
      - discretionary exit fills at the NEXT 1s bar open after the checkpoint,
      - the catastrophic stop is monitored on every 1s bar,
      - episodes truncate at the first terminal event (stop / opposing flip /
        max duration), so no post-terminal ("ghost") rows survive,
      - E0 = hold-to-regime-terminal PnL.

  * All multi-timeframe context is computed CAUSALLY from 1s bars using only
    data at/ before each checkpoint's `observation_time`, via O(1) prefix-sum
    evaluation (no look-ahead, no future window).

  * Higher-timeframe structural bars are resampled from 1s with closed='left'
    (per the catalog_1m_resample_bug lesson) and only bars whose CLOSE time is
    <= checkpoint time are used.

Splits (frozen, from the atlas `period` column, which matches the spec):
    train = 2024-01-01 .. 2024-12-31
    val   = 2025-01-01 .. 2025-02-28
    test  = 2025-03-01 .. 2025-05-31   (DEVELOPMENT TEST — previously inspected)
"""

from __future__ import annotations
import sys
import json
from pathlib import Path
import numpy as np
import pandas as pd

# ── Paths ───────────────────────────────────────────────────────────────────
REPO = Path("C:/Users/Scott McCarty/Projects/Nautilus Trader")
EOS = REPO / "studies/rl_regime_feasibility/exit_optimal_stopping"
EOS_RESULTS = EOS / "results"
V2 = REPO / "studies/rl_regime_feasibility/contextual_runner_exit_v2"
RESULTS = V2 / "results"
RESULTS.mkdir(parents=True, exist_ok=True)
CACHE = V2 / "cache"
CACHE.mkdir(parents=True, exist_ok=True)

ATLAS_CHK = EOS_RESULTS / "exit_atlas_checkpoints.parquet"
ATLAS_TRADES = EOS_RESULTS / "exit_atlas_trades.parquet"

# reuse the repaired execution stack
sys.path.insert(0, str(EOS / "repair"))
import sim_v2  # noqa: E402  (load_1s_bars, detect_stop_hit, next_1s_open, resolve_terminal_events, ...)

# ── Constants (mirror sim_v2) ───────────────────────────────────────────────
NQ_MULT = 20.0
COMMISSION = 5.0
STOP_ATR = 1.5          # catastrophic stop distance (atlas convention)
MIN_ELIG_S = 30         # minimum seconds in trade before an exit may fire
NQ_TICK = 0.25

# Bar coverage for MTF context + fills. Extend before train start by the
# longest horizon (900s) and past test end for fill lookups.
BAR_LO = int(pd.Timestamp("2023-12-30", tz="UTC").value)
BAR_HI = int(pd.Timestamp("2025-06-05", tz="UTC").value)

HORIZONS = {  # label -> seconds (== bar count on the 1s series)
    "30s": 30,
    "60s": 60,
    "180s": 180,
    "300s": 300,
    "900s": 900,
}
HTF = {"1m": 60, "3m": 180, "5m": 300, "15m": 900}  # seconds per higher-tf bar

# RTH: 8:30–15:00 America/Chicago == 13:30–20:00 UTC (CST) / 14:30–21:00 (CDT).
# The atlas already carries minutes_since_rth_open; we derive is_rth from it.


# ── 1s bar loading (open/low/high/close/volume) ─────────────────────────────
def load_1s_full(ts_lo: int = BAR_LO, ts_hi: int = BAR_HI) -> np.ndarray:
    """Load 1s bars [ts_lo, ts_hi): columns [ts, open, low, high, close, volume].

    Extends sim_v2.load_1s_bars (which returns ts/open/low/high) with close and
    volume needed for MTF context. Uses the same row-group metadata search.
    """
    import pyarrow.parquet as pq
    import pyarrow as pa
    import time as _t
    t0 = _t.time()
    pf = pq.ParquetFile(sim_v2.BAR_FILE)
    first_rg, last_rg = sim_v2._find_rg_range(pf, ts_lo, ts_hi)
    if first_rg > last_rg:
        return np.empty((0, 6), dtype=np.float64)
    tables = [pf.read_row_group(rg, columns=["ts_event", "open", "low", "high", "close", "volume"])
              for rg in range(first_rg, last_rg + 1)]
    df = pa.concat_tables(tables).to_pandas()

    def dec(series):
        return np.frombuffer(b"".join(series.values), dtype="<i8").astype(np.float64) / 1e9

    vol = df["volume"].values
    vol = vol.astype(np.float64) if np.issubdtype(vol.dtype, np.number) else \
        np.frombuffer(b"".join(df["volume"].values), dtype="<i8").astype(np.float64)
    arr = np.column_stack([
        df["ts_event"].values.astype(np.float64),
        dec(df["open"]), dec(df["low"]), dec(df["high"]), dec(df["close"]), vol,
    ])
    mask = (arr[:, 0] >= ts_lo) & (arr[:, 0] < ts_hi)
    arr = arr[mask]
    order = np.argsort(arr[:, 0], kind="mergesort")
    arr = arr[order]
    print(f"  [load_1s_full] {len(arr):,} bars in {_t.time()-t0:.1f}s "
          f"[{pd.Timestamp(ts_lo,unit='ns')} .. {pd.Timestamp(ts_hi,unit='ns')}]")
    return arr


def bars_ohlc4(arr: np.ndarray) -> np.ndarray:
    """ts array and OHLC columns for convenience."""
    return arr


# ── Higher-timeframe resample (closed='left', causal close times) ───────────
def build_htf(arr: np.ndarray, seconds: int) -> pd.DataFrame:
    """Resample 1s bars -> HTF bars. Returns df indexed 0..M with columns
    [close_ts, open, high, low, close, volume]. close_ts is the bar CLOSE time
    (= bucket start + `seconds`), i.e. the earliest wall time at which the bar
    is fully known — safe to use as a causal <= key.
    """
    ts = arr[:, 0].astype(np.int64)
    step = seconds * 1_000_000_000
    bucket = (ts // step) * step               # bucket START (== open ts, closed='left')
    df = pd.DataFrame({
        "bucket": bucket,
        "open": arr[:, 1], "low": arr[:, 2], "high": arr[:, 3],
        "close": arr[:, 4], "volume": arr[:, 5],
    })
    g = df.groupby("bucket", sort=True)
    out = pd.DataFrame({
        "open": g["open"].first(),
        "high": g["high"].max(),
        "low": g["low"].min(),
        "close": g["close"].last(),
        "volume": g["volume"].sum(),
    }).reset_index()
    out["close_ts"] = out["bucket"] + step     # fully known at bucket end
    return out[["close_ts", "open", "high", "low", "close", "volume"]]


# ── Session / RTH ───────────────────────────────────────────────────────────
def is_rth_from_atlas(chk: pd.DataFrame) -> np.ndarray:
    """RTH flag from the atlas minutes_since_rth_open field (0..390 == in RTH)."""
    m = chk["minutes_since_rth_open"].values
    return ((m >= 0) & (m <= 390)).astype(int)


# ── Paired bootstrap CI ─────────────────────────────────────────────────────
def paired_bootstrap_ci(deltas: np.ndarray, n_boot: int = 5000, seed: int = 42):
    """Percentile bootstrap 95% CI on the mean of paired deltas."""
    d = np.asarray(deltas, dtype=np.float64)
    d = d[~np.isnan(d)]
    if len(d) < 5:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    n = len(d)
    idx = rng.integers(0, n, size=(n_boot, n))
    means = d[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def load_atlas():
    chk = pd.read_parquet(ATLAS_CHK)
    chk = chk.sort_values(["episode_id", "seconds_since_entry"]).reset_index(drop=True)
    trades = pd.read_parquet(ATLAS_TRADES)
    return chk, trades


def savej(obj, path: Path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)
    print(f"  wrote {path.name}")
