"""BacktestEngine runner for the reduced-model (F3_top25_gbt_v1) population-
parity smoke study.

CAVEAT (explicit, not to be silently dropped): the progress/checkpoint/
resume/shared-replay mechanics added to this file and to strategy.py have
been validated at the COMPONENT level only (CandidateTracker/
ReducedFeatureEngine/RegimeEngine pickle round-trips confirmed correct in
isolation, day-boundary detection logic reviewed) -- NOT yet exercised
end-to-end inside a real BacktestEngine run. Per explicit instruction, no
further BacktestEngine execution happens until the current (in-flight)
results have been reviewed. Treat the first real use of --resume as a
validation run, not a trusted-by-default code path.

add_data(bars_1s) BEFORE add_data(bars_1m), verbatim, per
nt_live_scoring_infra_prereqs's add_bars_causal_order() finding: coincident
1s/1m timestamp ordering is determined by data-registration call order, not
an automatic NT bar-type priority.

SHARED REPLAY (items 7/8): R5 and R2.5 cannot share one LIVE NT position
stream -- NT nets fills per (instrument, strategy), so two independently-
triggered short entries from the two variants would corrupt each other's
P&L/position accounting if both submitted real orders from the same
Strategy/account. Instead: ONE live NT pass (the "primary" variant, default
R5) does the expensive shared work ONCE -- candidate declaration, live
25-feature snapshots, live model scoring -- and ALSO submits real NT orders
for itself. The "secondary" variant's trades are then derived by a cheap
POST-HOC walk (reusing trade_state.FlipTradeState, the exact same logic
`offline_reference.py` already uses) over the primary run's OWN logged
candidate stream (which already carries both r5_trigger and r2_5_trigger
flags for every candidate) against the raw 1s bar array -- not a second full
BacktestEngine pass. This is a disclosed trade-off: the secondary variant's
trades are NOT literally NT order fills, only analytically equivalent
(same touch-detection, same next-bar-open fill convention). If exact NT-
native fills are required for BOTH variants, run each as its own primary
pass instead (--variant R5 then --variant R2.5 separately, as before).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
import os  # noqa: E402
os.chdir(PROJECT_ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nautilus_trader.backtest.engine import BacktestEngine  # noqa: E402
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig  # noqa: E402
from nautilus_trader.model.currencies import USD  # noqa: E402
from nautilus_trader.model.enums import AccountType, OmsType  # noqa: E402
from nautilus_trader.model.identifiers import Venue  # noqa: E402
from nautilus_trader.model.objects import Money  # noqa: E402
from nautilus_trader.persistence.catalog import ParquetDataCatalog  # noqa: E402

from studies.fable5_pre_flip_d10_reversal_entry.run_nt import create_instrument  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
from strategy import ReducedModelSmokeConfig, ReducedModelSmokeStrategy  # noqa: E402
from trade_state import FlipTradeState  # noqa: E402

LOAD_START = pd.Timestamp("2025-01-01", tz="UTC")
LOAD_END = pd.Timestamp("2025-12-31 23:59:59", tz="UTC")
TOTAL_DAYS_ESTIMATE = 365  # for ETA display only


def _checkpoint_dir(tag: str, variant: str) -> Path:
    return C.WORK / "checkpoints" / tag / variant


def _find_resume_state(tag: str, variant: str) -> tuple[Path | None, str | None]:
    """Returns (checkpoint_pkl_path, last_completed_day) if a checkpoint
    exists for this tag/variant, else (None, None)."""
    ckpt_dir = _checkpoint_dir(tag, variant)
    manifest_path = ckpt_dir / f"checkpoint_{variant}_manifest.json"
    ckpt_path = ckpt_dir / f"checkpoint_{variant}.pkl"
    if manifest_path.exists() and ckpt_path.exists():
        manifest = json.loads(manifest_path.read_text())
        return ckpt_path, manifest["last_completed_day"]
    return None, None


def run_primary(variant_label: str, start=None, end=None, log_guard=None, tag: str = "full_march",
                resume: bool = False):
    t0 = time.time()
    load_start = pd.Timestamp(start, tz="UTC") if start else LOAD_START
    load_end = pd.Timestamp(end, tz="UTC") if end else LOAD_END

    ckpt_dir = _checkpoint_dir(tag, variant_label)
    resume_state_path = None
    if resume:
        ckpt_path, last_day = _find_resume_state(tag, variant_label)
        if ckpt_path is not None:
            # Resume from the day AFTER the last completed one -- narrows the
            # catalog load window, avoiding re-processing already-checkpointed
            # days at either the NT engine level or the strategy level.
            resume_state_path = ckpt_path
            load_start = pd.Timestamp(last_day, tz="UTC") + pd.Timedelta(days=1)
            print(f"[{variant_label}/{tag}] RESUMING from checkpoint: last_completed_day={last_day}, "
                 f"new load_start={load_start}")

    catalog = ParquetDataCatalog(str(C.CATALOG_PATH))
    bars_1s = catalog.bars(bar_types=[C.BAR_1S], start=load_start, end=load_end)
    bars_1m = catalog.bars(bar_types=[C.BAR_1M], start=load_start, end=load_end)
    print(f"[{variant_label}/{tag}] {len(bars_1s):,} 1s bars, {len(bars_1m):,} 1m bars "
          f"({time.time()-t0:.0f}s)")
    if not bars_1s or not bars_1m:
        raise RuntimeError(f"catalog returned no bars for {variant_label}/{tag}")

    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id=f"NTSMOKE-{variant_label}",
        logging=LoggingConfig(log_level="ERROR", bypass_logging=False)))
    if log_guard is None:
        log_guard = engine.get_log_guard()
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(5_000_000, USD)],
        bar_execution=True, bar_adaptive_high_low_ordering=True)
    engine.add_instrument(create_instrument())
    # CRITICAL: 1s before 1m, verbatim -- see module docstring.
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)

    cfg = ReducedModelSmokeConfig(
        variant_label=variant_label,
        model_path=str(C.MODEL_PATH), feature_list_json_path=str(C.FEATURE_SETS_PATH),
        thresholds_path=str(C.CONFIG / "frozen_thresholds.json"),
        stop_atr_mult=C.STOP_ATR_MULT, multiplier=C.NQ_MULT, cost_rt=C.COST_RT,
        log_only_month=C.SELECTED_MONTH,
        checkpoint_dir=str(ckpt_dir), resume_state_path=str(resume_state_path or ""),
        total_days_estimate=TOTAL_DAYS_ESTIMATE)
    strat = ReducedModelSmokeStrategy(config=cfg)
    engine.add_strategy(strat)
    engine.run(start=load_start)

    out_dir = C.WORK / "nt_runs" / tag / variant_label
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(strat.trades).to_parquet(out_dir / "trades.parquet", index=False)
    pd.DataFrame(strat.flips).to_parquet(out_dir / "flips.parquet", index=False)
    pd.DataFrame(strat.skips).to_parquet(out_dir / "skips.parquet", index=False)
    candidates_df = strat._parity_logger.to_dataframe()
    candidates_df.to_parquet(out_dir / "candidates.parquet", index=False)

    meta = {
        "variant": variant_label, "tag": tag, "n_trades": len(strat.trades),
        "n_skips": len(strat.skips), "n_flips": len(strat.flips),
        "n_candidates_logged": len(strat._parity_logger.candidates),
        "bars_processed_1s": strat._bars_processed_1s, "bars_processed_1m": strat._bars_processed_1m,
        "n_days_completed": strat._n_days_completed,
        "strategy_sha256": C.sha256_file(Path(__file__).resolve().parent / "strategy.py"),
        "candidate_tracker_sha256": C.sha256_file(Path(__file__).resolve().parent / "candidate_tracker.py"),
        "runtime_s": time.time() - t0,
        "load_start": str(load_start), "load_end": str(load_end), "resumed": resume_state_path is not None,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    print(f"[{variant_label}/{tag}] {len(strat.trades)} trades, {len(strat.skips)} skips, "
          f"{len(strat._parity_logger.candidates)} candidates logged ({time.time()-t0:.0f}s)")
    engine.dispose()
    return log_guard, candidates_df


def derive_secondary_variant_trades(candidates_df: pd.DataFrame, secondary_label: str,
                                    tag: str = "full_march") -> pd.DataFrame:
    """Post-hoc derivation of the secondary variant's trades from the
    primary run's own logged candidate stream (NOT a second live NT pass).
    Reuses trade_state.FlipTradeState exactly as offline_reference.py's
    build_trades() does, against the same raw 1s bar array. See module
    docstring for the disclosed trade-off this implies."""
    trig_col = "r5_trigger" if secondary_label == "R5" else "r2_5_trigger"
    # Column is "established_regime_gate" (parity_logger.py/candidate_tracker.py's
    # actual field name) -- "established" never existed, a pre-existing bug
    # unrelated to the anchor/progress-window fixes, found when this path
    # first executed against a real run's output.
    established = candidates_df[candidates_df["established_regime_gate"] == True].copy()  # noqa: E712
    if trig_col not in established.columns or established.empty:
        return pd.DataFrame()
    triggered = established[established[trig_col] == True]  # noqa: E712
    if triggered.empty:
        return pd.DataFrame()
    first_per_regime = (triggered.sort_values(["regime_start_ns", "observation_time_ns"])
                        .groupby("regime_start_ns", as_index=False).first())

    raw = pd.read_parquet(C.ROOT / "data" / "raw" / "NQ_v0_1s_2025.parquet",
                          columns=["open", "high", "low", "close"])
    ts_all = raw.index.view("int64")
    opens, highs, lows = raw["open"].to_numpy(float), raw["high"].to_numpy(float), raw["low"].to_numpy(float)

    trades = []
    for row in first_per_regime.itertuples(index=False):
        fill_ts = int(row.fill_ts) if pd.notna(row.fill_ts) else int(row.observation_time_ns)
        i0 = int(np.searchsorted(ts_all, fill_ts, side="left"))
        if i0 >= len(ts_all) or int(ts_all[i0]) != fill_ts:
            continue
        entry_px = float(opens[i0]) if pd.isna(row.fill_px) else float(row.fill_px)
        atr = float(row.atr_at_entry)
        st = FlipTradeState(entry_direction=-1, entry_px=entry_px, atr=atr, stop_atr_mult=C.STOP_ATR_MULT)
        i = i0
        exit_reason, exit_px, exit_ts = None, None, None
        while i < len(ts_all):
            h, l = highs[i], lows[i]
            if st.stop_would_touch(h, l):
                if i + 1 >= len(ts_all):
                    break
                exit_reason, exit_px, exit_ts = st.on_stop_touch(), float(opens[i + 1]), int(ts_all[i + 1])
                break
            i += 1
        if exit_reason is None:
            continue
        gross = (exit_px - entry_px) * (-1) * C.NQ_MULT
        trades.append({
            "variant": secondary_label, "regime_start_ns": row.regime_start_ns,
            "entry_fill_time": fill_ts, "entry_price": entry_px, "atr_entry": atr,
            "exit_reason": exit_reason, "exit_price": exit_px, "exit_fill_time": exit_ts,
            "gross_pnl": gross, "net_pnl": gross - C.COST_RT,
            "derivation": "post_hoc_from_primary_candidate_log_not_live_nt_fill",
        })
    return pd.DataFrame(trades)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--primary-variant", choices=["R5", "R2.5"], default="R5",
                    help="which variant runs the real, live NT BacktestEngine pass")
    ap.add_argument("--both-live", action="store_true",
                    help="run BOTH variants as independent live NT passes (old behavior, replays the month twice)")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--tag", default="full_march")
    ap.add_argument("--resume", action="store_true", help="resume from the last checkpoint if one exists")
    args = ap.parse_args()

    if args.both_live:
        guard = None
        for label in ("R5", "R2.5"):
            guard, _ = run_primary(label, start=args.start, end=args.end, log_guard=guard,
                                   tag=args.tag, resume=args.resume)
        return

    guard, candidates_df = run_primary(args.primary_variant, start=args.start, end=args.end,
                                       tag=args.tag, resume=args.resume)
    secondary_label = "R2.5" if args.primary_variant == "R5" else "R5"
    secondary_trades = derive_secondary_variant_trades(candidates_df, secondary_label, tag=args.tag)
    out_dir = C.WORK / "nt_runs" / args.tag / secondary_label
    out_dir.mkdir(parents=True, exist_ok=True)
    secondary_trades.to_parquet(out_dir / "trades.parquet", index=False)
    # Secondary variant shares the SAME candidate log as the primary (both
    # r5_trigger/r2_5_trigger flags already present on every row) -- write a
    # copy so reconcile.py's per-variant-directory convention still works.
    candidates_df.to_parquet(out_dir / "candidates.parquet", index=False)
    (out_dir / "meta.json").write_text(json.dumps({
        "variant": secondary_label, "tag": args.tag, "n_trades": len(secondary_trades),
        "derivation": "post_hoc_from_primary_run", "primary_variant": args.primary_variant,
    }, indent=2))
    print(f"[{secondary_label}/{args.tag}] {len(secondary_trades)} trades derived post-hoc "
         f"from the {args.primary_variant} live run's candidate log (no second BacktestEngine pass)")


if __name__ == "__main__":
    main()
