"""Population-agnostic NT BacktestEngine runner.

Runs ONE strategy class + config over ONE year of NQ.v.0 catalog data,
mirroring the already-established per-year convention in
collectors/collector_v2/run_v_a_year_v0_nodelay.py (5-day warmup
buffer before Jan 1, full continuous 1s+1m bars for the year, fresh
engine per year). Population-specific behavior (which strategy class,
which config) is supplied entirely by the caller -- this module knows
nothing about F2 or all-flips.
"""
from __future__ import annotations
import sys, time
from pathlib import Path

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

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

CATALOG_PATH = "data/catalog/NQ_v0_2020_2026"
INSTRUMENT_ID = "NQ.XCME"
BAR_TYPE_1M = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
BAR_TYPE_1S = "NQ.XCME-1-SECOND-LAST-EXTERNAL"


def create_nq():
    t = TestInstrumentProvider.future(
        symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2026-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["multiplier"], d["price_increment"] = "20", "0.25"
    return FuturesContract.from_dict(d)


def run_period(
    strategy_cls, config_cls, config_kwargs: dict,
    load_start: pd.Timestamp, load_end: pd.Timestamp,
    out_dir: Path, catalog_path: str = CATALOG_PATH,
    trader_id: str = "EXITMGMT-001", strategy_post_init=None,
):
    """Run strategy_cls(config_cls(**config_kwargs, output_dir=out_dir))
    over [load_start, load_end] via NT BacktestEngine. Returns
    (elapsed_seconds, diag_dict)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    catalog = ParquetDataCatalog(catalog_path)
    bars_1s = catalog.bars(bar_types=[BAR_TYPE_1S],
                               start=load_start, end=load_end)
    bars_1m = catalog.bars(bar_types=[BAR_TYPE_1M],
                               start=load_start, end=load_end)
    load_elapsed = time.time() - t0

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=trader_id,
        logging=LoggingConfig(log_level="WARNING",
                                  log_directory=str(out_dir / "logs")),
    ))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
        bar_execution=True)
    engine.add_instrument(create_nq())
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)

    cfg = config_cls(
        instrument_id=INSTRUMENT_ID,
        bar_type_1m=BAR_TYPE_1M,
        bar_type_1s=BAR_TYPE_1S,
        output_dir=str(out_dir),
        **config_kwargs,
    )
    strat = strategy_cls(cfg)
    if strategy_post_init is not None:
        strategy_post_init(strat)  # e.g. attach a frozen policy_engine/policy_cfg
    engine.add_strategy(strat)
    t1 = time.time()
    engine.run()
    run_elapsed = time.time() - t1
    diag = dict(strat._diag)
    engine.dispose()
    return {
        "n_bars_1s": len(bars_1s), "n_bars_1m": len(bars_1m),
        "load_elapsed_s": load_elapsed, "run_elapsed_s": run_elapsed,
        "diag": diag,
    }


def run_year(strategy_cls, config_cls, config_kwargs: dict, year: int,
                out_dir: Path, catalog_path: str = CATALOG_PATH,
                warmup_days: int = 5, trader_id: str = "EXITMGMT-001",
                strategy_post_init=None):
    load_start = (pd.Timestamp(f"{year}-01-01", tz="UTC")
                     - pd.Timedelta(days=warmup_days))
    load_end = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC")
    return run_period(strategy_cls, config_cls, config_kwargs,
                          load_start, load_end, out_dir, catalog_path,
                          trader_id, strategy_post_init=strategy_post_init)


def run_period_chunked(
    strategy_cls, config_cls, config_kwargs: dict,
    load_start: pd.Timestamp, load_end: pd.Timestamp,
    out_dir: Path, catalog_path: str = CATALOG_PATH,
    trader_id: str = "EXITMGMT-001", strategy_post_init=None,
    chunk_months: int = 2, warmup_days: int = 5,
):
    """Split [load_start, load_end] into ~chunk_months-long sub-periods,
    each run as its own independent NT backtest (own warmup, own fresh
    engine/strategy instance), then concatenate the resulting
    trades.parquet files into out_dir/trades.parquet.

    Exists ONLY to work around a background-process wall-clock limit
    in this environment that kills long-running single-invocation
    backtests (~50-70 min policy-year runs observed being killed
    before writing any output; run_period alone cannot avoid this).
    Each chunk completes well under that limit; per-chunk output is
    cached in out_dir/_chunks/<i>/ so a killed run resumes at the
    chunk level (not from year 0) on retry.

    KNOWN LIMITATION (documented, not a systematic bias): a trade open
    exactly at a chunk boundary is not carried over -- the chunk it
    was opened in ends without a matching exit (silently absent from
    that chunk's trades.parquet, since only fully-finalized trades are
    written), and the next chunk's fresh regime engine only enters on
    the NEXT causal flip after its own warmup, not the already-in-
    -progress regime. This affects a small, bounded number of trades
    per chunk boundary (order of 1 per boundary), not a directional
    distortion of the results.
    """
    chunks_root = out_dir / "_chunks"
    chunks_root.mkdir(parents=True, exist_ok=True)

    bounds = []
    cur = load_start  # load_start IS the true period start (no warmup
                       # adjustment here -- warmup is applied per-chunk
                       # below, via warmup_start = chunk_start - warmup_days)
    i = 0
    while cur < load_end:
        chunk_end = min(cur + pd.DateOffset(months=chunk_months), load_end)
        bounds.append((i, cur, chunk_end))
        cur = chunk_end
        i += 1

    all_diags = []
    for i, chunk_start, chunk_end in bounds:
        chunk_dir = chunks_root / str(i)
        if (chunk_dir / "trades.parquet").exists() or (
                chunk_dir / "_empty.marker").exists():
            continue  # already done (possibly with zero trades)
        warmup_start = chunk_start - pd.Timedelta(days=warmup_days)
        res = run_period(
            strategy_cls, config_cls, config_kwargs,
            warmup_start, chunk_end - pd.Timedelta(seconds=1), chunk_dir,
            catalog_path, trader_id, strategy_post_init=strategy_post_init)
        all_diags.append(res["diag"])
        # Each chunk's own warmup window (chunk_start - warmup_days,
        # chunk_start) OVERLAPS the PREVIOUS chunk's true trading
        # period -- a real bug caught by testing before trusting this:
        # a chunk's NT run causally generates entries during its own
        # warmup too (it has no concept of "warmup vs real" beyond
        # ATR/regime priming), so without filtering, adjacent chunks
        # both emit trades for the shared overlap window, duplicating
        # them. Keep only entries with entry_ts in [chunk_start,
        # chunk_end) -- ATR/regime state from the warmup still
        # correctly primes the FIRST real entry in this window; the
        # bars themselves are never re-used across chunks, only the
        # entries are de-duplicated by this filter.
        trades_p = chunk_dir / "trades.parquet"
        if trades_p.exists():
            df = pd.read_parquet(trades_p)
            mask = ((df["entry_ts"] >= chunk_start.value)
                        & (df["entry_ts"] < chunk_end.value))
            df = df[mask]
            if len(df):
                df.to_parquet(trades_p, index=False)
            else:
                trades_p.unlink()
        if not (chunk_dir / "trades.parquet").exists():
            (chunk_dir / "_empty.marker").write_text("no trades this chunk")

    # Concatenate all chunk outputs (whatever exists on disk now --
    # supports resuming after a kill mid-way through the chunk loop).
    trade_frames = []
    for i, _, _ in bounds:
        p = chunks_root / str(i) / "trades.parquet"
        if p.exists():
            trade_frames.append(pd.read_parquet(p))
    if not all((chunks_root / str(i) / "trades.parquet").exists()
                  or (chunks_root / str(i) / "_empty.marker").exists()
                  for i, _, _ in bounds):
        raise RuntimeError(
            f"run_period_chunked: not all {len(bounds)} chunks finished "
            f"for {out_dir} -- re-run to continue from where it left off")

    combined = (pd.concat(trade_frames, ignore_index=True)
                   if trade_frames else pd.DataFrame())
    # Reassign a globally-unique trade_id across chunks (each chunk's
    # strategy instance restarts its own counter from 1) and sort by
    # entry_ts so downstream chronological assumptions hold.
    if len(combined):
        combined = combined.sort_values("entry_ts").reset_index(drop=True)
        combined["trade_id"] = range(1, len(combined) + 1)
    combined.to_parquet(out_dir / "trades.parquet", index=False)

    merged_diag = {}
    for d in all_diags:
        for k, v in d.items():
            if isinstance(v, (int, float)):
                merged_diag[k] = merged_diag.get(k, 0) + v
    return {"diag": merged_diag, "n_chunks": len(bounds),
               "n_trades": len(combined)}
