"""Drive a real BacktestEngine over Feb-warmup + March-2025 and emit the live
ledgers for Phases 1-5.

Layer A (default): threshold-free. Candidate population, features, and scores
only -- no triggers, no orders. Layer B is enabled with --threshold and must be
labelled PROVISIONAL_PARITY_HARNESS_ONLY.
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]                       # repo root
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import nautilus_trader  # noqa: E402
from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig  # noqa: E402
from nautilus_trader.backtest.models import FillModel  # noqa: E402
from nautilus_trader.config import LoggingConfig, RiskEngineConfig  # noqa: E402
from nautilus_trader.model.currencies import USD  # noqa: E402
from nautilus_trader.model.enums import AccountType, OmsType  # noqa: E402
from nautilus_trader.model.identifiers import Venue  # noqa: E402
from nautilus_trader.model.instruments import FuturesContract  # noqa: E402
from nautilus_trader.model.objects import Money  # noqa: E402
from nautilus_trader.persistence.catalog import ParquetDataCatalog  # noqa: E402
from nautilus_trader.test_kit.providers import TestInstrumentProvider  # noqa: E402

import common as C  # noqa: E402
from strategy import LongParityConfig, LongParityStrategy  # noqa: E402

_LOG_GUARD = None


def create_instrument():
    """NQ futures contract, same construction as backtests/baseline_flip_parity
    (multiplier 20, 0.25 tick) so fills/prices are comparable across studies."""
    t = TestInstrumentProvider.future(symbol="NQ", underlying="NQ",
                                      venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2019-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2027-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2019-01-01", tz="UTC").value
    d["multiplier"] = "20"          # FuturesContract.from_dict expects str here
    d["price_increment"] = "0.25"
    return FuturesContract.from_dict(d)


def add_bars_causal_order(engine, bars_1s, bars_1m) -> None:
    """The ONLY safe way to load coincident 1s+1m data. add_data()'s tie-break
    at equal ts_init is decided purely by call order -- finer timeframe first.
    (Verbatim contract from nt_live_scoring_infra_prereqs.)"""
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warmup-start", default=C.WARMUP_START_UTC)
    ap.add_argument("--threshold", type=float, default=-1.0,
                    help="Layer B only; <0 keeps the run threshold-free (Layer A)")
    ap.add_argument("--tag", default="layerA")
    ap.add_argument("--emit-end", default=None,
                    help="override the emit-window end (Chicago) - smoke runs only; "
                         "the full study MUST use the full March window")
    args = ap.parse_args()

    t0 = time.time()
    emit_start = pd.Timestamp(C.MARCH_START_CHI, tz=C.SESSION_TZ)
    emit_end = pd.Timestamp(args.emit_end or C.MARCH_END_CHI, tz=C.SESSION_TZ)
    load_start = pd.Timestamp(args.warmup_start)
    load_end = emit_end.tz_convert("UTC")

    catalog = ParquetDataCatalog(str(C.CATALOG_PATH))
    bars_1s = catalog.bars(bar_types=[C.BAR_1S], start=load_start, end=load_end)
    bars_1m = catalog.bars(bar_types=[C.BAR_1M], start=load_start, end=load_end)
    if not bars_1s or not bars_1m:
        raise SystemExit("catalog returned no bars for the requested window")
    print(f"loaded 1s={len(bars_1s):,} 1m={len(bars_1m):,} "
          f"[{load_start} -> {load_end}]")

    global _LOG_GUARD
    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id="LONG-TOP25-PARITY",
        logging=LoggingConfig(log_level="ERROR", bypass_logging=True),
        risk_engine=RiskEngineConfig(bypass=True)))
    venue = Venue("XCME")
    engine.add_venue(venue=venue, oms_type=OmsType.NETTING,
                     account_type=AccountType.MARGIN, base_currency=USD,
                     starting_balances=[Money(5_000_000, USD)],
                     fill_model=FillModel(prob_fill_on_limit=1.0, prob_slippage=0.0))
    instrument = create_instrument()
    engine.add_instrument(instrument)
    add_bars_causal_order(engine, bars_1s, bars_1m)

    strat = LongParityStrategy(LongParityConfig(
        instrument_id=str(instrument.id),
        emit_start_ns=int(emit_start.value), emit_end_ns=int(emit_end.value),
        trigger_threshold=args.threshold))
    engine.add_strategy(strat)
    engine.run(start=load_start)

    cand = pd.DataFrame(strat.candidates)
    trig = pd.DataFrame(strat.triggers)
    trades = pd.DataFrame(strat.trades)
    tag = args.tag
    cand.to_parquet(C.WORK / f"candidate_ledger_live_{tag}.parquet", index=False)
    if len(trig):
        trig.to_csv(C.RESULTS / f"trigger_ledger_live_{tag}.csv", index=False)
    if len(trades):
        trades.to_csv(C.RESULTS / f"trade_ledger_live_{tag}.csv", index=False)

    wf = pd.DataFrame([{"stage": k, "side": "live", "count": v}
                       for k, v in strat.waterfall.items()])
    wf.to_csv(C.RESULTS / f"population_waterfall_live_{tag}.csv", index=False)

    manifest = {
        "tag": tag,
        "git_commit": git_commit(),
        "model_id": C.MODEL_ID,
        "model_sha256": C.sha256_file(C.MODEL_PATH),
        "feature_order_sha256": C.EXPECTED_FEATURE_ORDER_SHA256,
        "coefficients_sha256": C.sha256_file(C.COEFFICIENTS_PATH),
        "intercept_sha256": C.sha256_file(C.INTERCEPT_PATH),
        "data_range_loaded_utc": [str(load_start), str(load_end)],
        "emit_window_chicago": [str(emit_start), str(emit_end)],
        "emit_window_utc": [str(emit_start.tz_convert('UTC')),
                            str(emit_end.tz_convert('UTC'))],
        "session_timezone": C.SESSION_TZ,
        "rth_rule_chicago": "08:30:00-15:15:00",
        "bar_counts": {"1s": len(bars_1s), "1m": len(bars_1m)},
        "bars_processed": {"1s": strat.bars_1s, "1m": strat.bars_1m},
        "nt_version": nautilus_trader.__version__,
        "python_version": platform.python_version(),
        "pandas_version": pd.__version__,
        "random_seeds": {"model": 42},
        "tolerances": {"feature": C.TOL_FEATURE, "logit": C.TOL_LOGIT,
                       "probability": C.TOL_PROBA},
        "threshold": args.threshold,
        "threshold_label": ("PROVISIONAL_PARITY_HARNESS_ONLY" if args.threshold >= 0
                            else "NONE_LAYER_A_THRESHOLD_FREE"),
        "stop_atr_mult": C.STOP_ATR_MULT,
        "management_contract": "fixed 1.25xATR stop frozen at regime flip, never "
                               "reset/trailed; exit = stop OR opposing regime flip; "
                               "no timeout, no PT, no trailing",
        "waterfall_live": strat.waterfall,
        "n_candidate_rows_in_window": int(len(cand)),
        "n_eligible_in_window": int(cand["final_candidate_eligible"].sum()) if len(cand) else 0,
        "n_triggers": int(len(trig)), "n_trades": int(len(trades)),
        "runtime_s": round(time.time() - t0, 1),
    }
    (C.RESULTS / f"run_manifest_{tag}.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in
                      ("waterfall_live", "n_candidate_rows_in_window",
                       "n_eligible_in_window", "n_triggers", "n_trades", "runtime_s")},
                     indent=2))
    engine.dispose()


if __name__ == "__main__":
    main()
