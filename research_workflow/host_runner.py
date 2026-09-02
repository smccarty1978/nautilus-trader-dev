"""Drivers for the host: pure-Python (fixtures/tests), NautilusTrader over synthetic bars,
and NautilusTrader over a governed catalog window.  The runner resolves datasets through
the machine-local roots and never stores a path in an artifact."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from research_workflow.host.interfaces import BarView
from research_workflow.host.strategy import HostCore


def sort_bars_causal(bars: Iterable[BarView], durations: Mapping[str, int]) -> List[BarView]:
    """Same tie rule as the NT loader order: at equal ts_init the shorter timeframe first.
    Bars of streams the plan does not declare are dropped (an unsubscribed stream)."""
    return sorted((b for b in bars if b.stream in durations), key=lambda b: (b.ts_init, durations[b.stream]))


def run_plan_on_bars(plan: Mapping[str, Any], bars: Iterable[BarView], *, session_table: Any,
                     primary_interval: Optional[Tuple[int, int]] = None, ledger: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    durations = {s["key"]: int(s["duration_ns"]) for s in plan["streams"]}
    core = HostCore(plan, session_table=session_table, primary_interval=primary_interval, ledger=ledger)
    t0 = time.perf_counter()
    for bar in sort_bars_causal(bars, durations):
        core.ingest(bar)
    candidates, observations = core.finalize()
    return {"candidates": candidates, "observations": observations, "stats": core.stats(),
            "elapsed_s": time.perf_counter() - t0, "core": core}


# --------------------------------------------------------------------------- #
# NautilusTrader drivers
# --------------------------------------------------------------------------- #
def _nt_bars_from_views(views: Sequence[BarView], plan: Mapping[str, Any], instruments: Mapping[str, Any]):
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.objects import Price, Quantity
    stream_info = {s["key"]: s for s in plan["streams"]}
    out = []
    for v in views:
        s = stream_info[v.stream]
        inst = instruments[s["instrument"]]
        bt = BarType.from_str(s["bar_type"])
        prec = inst.price_precision
        out.append(Bar(bt, Price(v.open, prec), Price(v.high, prec), Price(v.low, prec), Price(v.close, prec),
                       Quantity(v.volume, inst.size_precision), int(v.ts_event), int(v.ts_init)))
    return out


def run_plan_with_engine(plan: Mapping[str, Any], bars: Sequence[BarView], *, session_table_spec: Mapping[str, Any],
                         primary_interval: Optional[Tuple[int, int]] = None, log_level: str = "ERROR",
                         ledger: bool = False) -> Dict[str, Any]:
    """Synthetic-instrument NT run: builds an engine from the plan's instruments and the given bars."""
    import uuid
    import pandas as pd
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.enums import AccountType, OmsType
    from nautilus_trader.model.identifiers import Venue
    from nautilus_trader.model.instruments import FuturesContract
    from nautilus_trader.model.objects import Money
    from nautilus_trader.test_kit.providers import TestInstrumentProvider
    from research_workflow.host.strategy import GovernedHostStrategy, GovernedHostStrategyConfig

    engine = BacktestEngine(config=BacktestEngineConfig(trader_id=f"HOST-{uuid.uuid4().hex[:8]}", logging=LoggingConfig(log_level=log_level)))
    venues: Dict[str, Venue] = {}
    instruments: Dict[str, Any] = {}
    for sym, facts in plan["instruments"].items():
        venue_name = str(facts["venue"])
        if venue_name not in venues:
            venue = Venue(venue_name)
            engine.add_venue(venue=venue, oms_type=OmsType.NETTING, account_type=AccountType.MARGIN, base_currency=USD,
                             starting_balances=[Money(1_000_000, USD)])
            venues[venue_name] = venue
        t = TestInstrumentProvider.future(symbol=sym, underlying=sym, venue=venue_name, exchange=venue_name)
        d = t.to_dict(t)
        d["activation_ns"] = pd.Timestamp("2019-01-01", tz="UTC").value
        d["expiration_ns"] = pd.Timestamp("2035-12-31 23:59:59", tz="UTC").value
        d["ts_event"] = d["ts_init"] = d["activation_ns"]
        d["multiplier"] = str(facts.get("multiplier") or "1.0")
        pi = str(facts.get("price_increment") or "0.25")
        d["price_increment"] = pi
        d["price_precision"] = len(pi.split(".")[1]) if "." in pi else 0
        inst = FuturesContract.from_dict(d)
        engine.add_instrument(inst)
        instruments[sym] = inst
    durations = {s["key"]: int(s["duration_ns"]) for s in plan["streams"]}
    ordered = sort_bars_causal(bars, durations)
    # NT add_data tie-break at equal ts_init is insertion order: add per stream, shortest duration first
    for key in sorted(durations, key=lambda k: durations[k]):
        views = [b for b in ordered if b.stream == key]
        if views:
            engine.add_data(_nt_bars_from_views(views, plan, instruments))
    cfg = GovernedHostStrategyConfig(plan_json=json.dumps(plan, default=str), session_table_json=json.dumps(session_table_spec),
                                     primary_start_ts=(primary_interval[0] if primary_interval else None),
                                     primary_end_ts=(primary_interval[1] if primary_interval else None), ledger_enabled=ledger)
    strategy = GovernedHostStrategy(cfg)
    engine.add_strategy(strategy)
    t0 = time.perf_counter()
    engine.run()
    elapsed = time.perf_counter() - t0
    candidates = strategy.get_candidates_dataframe()
    observations = strategy.get_observations_dataframe()
    stats = strategy.core.stats()
    ledger_rows = strategy.ledger
    engine.dispose()
    return {"candidates": candidates, "observations": observations, "stats": stats, "elapsed_s": elapsed, "ledger": ledger_rows}


def _is_product_default_dataset(symbol: str, dataset_id: str) -> bool:
    from backtests.nt_runtime.data_plan import PRODUCT_CATALOGS
    prod = PRODUCT_CATALOGS.get(symbol.upper())
    return bool(prod and prod.get("dataset_id") == dataset_id)


def resolve_dataset_plan(dataset_id: str, start_date: str, end_date: str, *, warmup_days: int, repo_root: Path):
    """DataPlan for a committed DatasetSpec (research/datasets/<id>.yaml) resolved through machine-local roots.
    Used for datasets that are not a product's V0 default (Dataset V2); the V0 resolver is left untouched."""
    import pandas as pd
    import yaml
    from backtests.nt_runtime.data_plan import DataPlan
    from research_workflow.roots import committed_dataset_spec_path, resolve_dataset
    spec_path = committed_dataset_spec_path(dataset_id, repo_root)
    if not spec_path.is_file():
        raise RuntimeError(f"DATASET_SPEC_MISSING: {spec_path}")
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    inst = spec.get("instrument") or {}
    instrument_id = str(spec.get("instrument_id") or inst.get("instrument_id"))
    symbol, venue = instrument_id.split(".")[0], str(inst.get("venue") or instrument_id.split(".")[-1])
    resolved = resolve_dataset(dataset_id, repo_root, catalog_rel_path=spec.get("catalog_rel_path"))
    streams = spec.get("streams") or {}
    start_dt = pd.Timestamp(f"{start_date} 00:00:00", tz="UTC")
    end_dt = pd.Timestamp(f"{end_date} 23:59:59.999999999", tz="UTC")
    if start_dt > end_dt:
        raise ValueError(f"start_date ({start_date}) cannot be after end_date ({end_date})")
    return DataPlan(symbol=symbol, venue=venue, instrument_id=instrument_id, multiplier=str(inst.get("multiplier")), price_increment=str(inst.get("price_increment")),
                    catalog_path=resolved.catalog_path, bar_type_1s=streams["1s"]["bar_type"], bar_type_1m=streams["1m"]["bar_type"],
                    start_dt=start_dt, end_dt=end_dt, warmup_days=warmup_days, warmup_start_dt=start_dt - pd.Timedelta(days=warmup_days),
                    raw_timestamp_semantic="OPEN_STAMPED", ts_init_delta_1s_ns=int(streams["1s"]["ts_init_delta_ns"]), ts_init_delta_1m_ns=int(streams["1m"]["ts_init_delta_ns"]),
                    dataset_id=dataset_id, dataset_logical_digest=resolved.logical_digest, dataset_resolution=resolved.resolution)


def run_plan_on_catalog(plan: Mapping[str, Any], *, start_date: str, end_date: str, repo_root: Optional[Path] = None,
                        primary_interval: Optional[Tuple[int, int]] = None, warmup_days: int = 5, log_level: str = "ERROR",
                        session_table_spec: Optional[Mapping[str, Any]] = None, progress_path: Optional[Path] = None,
                        progress_every_bars: int = 200_000, ledger: bool = False, studies_root: Optional[Path] = None) -> Dict[str, Any]:
    """Governed-catalog run for the plan's execution instrument (single instrument this phase)."""
    from backtests.nt_runtime.data_plan import resolve_catalog_plan, verify_launch_dataset_bytes
    from backtests.nt_runtime.engine_builder import build_engine
    from research_workflow.host.strategy import GovernedHostStrategy, GovernedHostStrategyConfig

    repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    exec_symbol = next(sym for sym, f in plan["instruments"].items() if f["role"] == "execution")
    declared = plan["instruments"][exec_symbol]
    if declared.get("dataset_id") and not _is_product_default_dataset(exec_symbol, declared["dataset_id"]):
        data_plan = resolve_dataset_plan(declared["dataset_id"], start_date, end_date, warmup_days=warmup_days, repo_root=repo_root)
    else:
        data_plan = resolve_catalog_plan(exec_symbol, start_date, end_date, warmup_days=warmup_days, repo_root=repo_root)
    if declared.get("dataset_id") and data_plan.dataset_id != declared["dataset_id"]:
        raise RuntimeError(f"WRONG_PHYSICAL_DATASET: plan declares {declared['dataset_id']}, resolver gave {data_plan.dataset_id}")
    if declared.get("dataset_digest") and data_plan.dataset_logical_digest and declared["dataset_digest"] != data_plan.dataset_logical_digest:
        raise RuntimeError("DATASET_DIGEST_MISMATCH: plan digest != resolved catalog digest")
    bytes_check = verify_launch_dataset_bytes(data_plan)
    engine, _instrument = build_engine(data_plan, log_level=log_level)
    st_spec = dict(session_table_spec or plan.get("session") or {"kind": "legacy", "session": "RTH"})
    cfg = GovernedHostStrategyConfig(plan_json=json.dumps(plan, default=str), session_table_json=json.dumps(st_spec),
                                     primary_start_ts=(primary_interval[0] if primary_interval else None),
                                     primary_end_ts=(primary_interval[1] if primary_interval else None),
                                     progress_path=str(progress_path) if progress_path else "", progress_every_bars=progress_every_bars,
                                     ledger_enabled=ledger, studies_root=str(studies_root or (repo_root / "studies")))
    strategy = GovernedHostStrategy(cfg)
    engine.add_strategy(strategy)
    t0 = time.perf_counter()
    engine.run()
    elapsed = time.perf_counter() - t0
    candidates = strategy.get_candidates_dataframe()
    observations = strategy.get_observations_dataframe()
    stats = strategy.core.stats()
    ledger_rows = strategy.ledger
    engine.dispose()
    return {"candidates": candidates, "observations": observations, "stats": stats, "elapsed_s": elapsed,
            "dataset": {"dataset_id": data_plan.dataset_id, "logical_digest": data_plan.dataset_logical_digest,
                        "bytes_verification": bytes_check.get("status")},
            "window": {"start": start_date, "end": end_date, "warmup_days": warmup_days}, "ledger": ledger_rows}


__all__ = ["run_plan_on_bars", "run_plan_with_engine", "run_plan_on_catalog", "resolve_dataset_plan", "sort_bars_causal"]
